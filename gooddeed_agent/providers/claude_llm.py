"""Claude-backed LLM provider (vision, web search, structured output).

One method, :meth:`ClaudeLLMProvider.complete_json`, covers all four agent
functions: it sends text and/or image blocks, optionally lets Claude run the
server-side web search tool, and constrains the answer to a JSON schema via
``output_config.format`` so callers always get a parseable dict.
"""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any

import anthropic

from ..config import REFUSAL_FALLBACK_BETA, WEB_SEARCH_TOOL_TYPE, Settings
from .base import ProviderError

log = logging.getLogger("gooddeed_agent.claude")

# A server-tool turn can stop with stop_reason "pause_turn"; resend to resume.
_MAX_PAUSE_RESUMES = 4

_SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}

# Magic-byte sniffing, because uploads routinely arrive with the wrong extension.
_MAGIC = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


def build_image_block(photo: str | bytes | Path) -> dict[str, Any]:
    """Turn a photo reference into an Anthropic image content block.

    Accepts an ``http(s)`` URL (passed through by reference), a filesystem
    path, a ``data:`` URL, a base64 string, or raw bytes.
    """
    if isinstance(photo, Path):
        return _image_from_bytes(photo.read_bytes())

    if isinstance(photo, bytes):
        return _image_from_bytes(photo)

    if isinstance(photo, str):
        value = photo.strip()
        if value.startswith(("http://", "https://")):
            return {"type": "image", "source": {"type": "url", "url": value}}
        if value.startswith("data:"):
            header, _, payload = value.partition(",")
            media_type = header[5:].split(";")[0] or "image/jpeg"
            return _image_block(media_type, payload)
        path = Path(value)
        if path.exists():
            return _image_from_bytes(path.read_bytes())
        # Last resort: assume it is already base64-encoded image data.
        try:
            return _image_from_bytes(base64.b64decode(value, validate=True))
        except Exception as exc:
            raise ValueError(
                "photo must be a URL, a readable file path, raw bytes, or base64 image data"
            ) from exc

    raise TypeError(f"Unsupported photo type: {type(photo).__name__}")


def _image_from_bytes(raw: bytes) -> dict[str, Any]:
    media_type = _sniff_media_type(raw)
    return _image_block(media_type, base64.standard_b64encode(raw).decode("utf-8"))


def _image_block(media_type: str, b64_data: str) -> dict[str, Any]:
    if media_type not in _SUPPORTED_IMAGE_TYPES:
        media_type = "image/jpeg"
    # The API rejects base64 containing newlines.
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": media_type, "data": b64_data.replace("\n", "")},
    }


def _sniff_media_type(raw: bytes) -> str:
    for prefix, media_type in _MAGIC:
        if raw.startswith(prefix):
            return media_type
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


class ClaudeLLMProvider:
    """Implements :class:`LLMProvider` against the Anthropic Messages API."""

    def __init__(self, settings: Settings, client: anthropic.Anthropic | None = None):
        if not settings.anthropic_api_key and client is None:
            raise ValueError("ClaudeLLMProvider requires ANTHROPIC_API_KEY")
        self._settings = settings
        self._client = client or anthropic.Anthropic(
            api_key=settings.anthropic_api_key, timeout=settings.request_timeout_s
        )
        # Flipped off permanently if the account/endpoint rejects the beta.
        self._fallbacks_enabled = settings.enable_refusal_fallback

    def complete_json(
        self,
        *,
        system: str,
        content: list[dict[str, Any]],
        schema: dict[str, Any],
        effort: str = "medium",
        use_web_search: bool = False,
        max_tokens: int = 8192,
    ) -> dict[str, Any]:
        messages: list[dict[str, Any]] = [{"role": "user", "content": content}]
        tools = (
            [{"type": WEB_SEARCH_TOOL_TYPE, "name": "web_search", "max_uses": 4}]
            if use_web_search
            else None
        )

        response = None
        for _ in range(_MAX_PAUSE_RESUMES + 1):
            response = self._create(
                system=system,
                messages=messages,
                schema=schema,
                effort=effort,
                tools=tools,
                max_tokens=max_tokens,
            )
            if response.stop_reason != "pause_turn":
                break
            # Server tool hit its iteration limit mid-turn: append the paused
            # assistant turn and resend so Claude picks up where it left off.
            messages.append({"role": "assistant", "content": response.content})
        else:
            raise ProviderError("Claude turn still paused after repeated resumes")

        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None)
            raise ProviderError(f"Claude declined the request (category={category})")

        return self._extract_json(response)

    def _create(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        schema: dict[str, Any],
        effort: str,
        tools: list[dict[str, Any]] | None,
        max_tokens: int,
    ):
        params: dict[str, Any] = {
            "model": self._settings.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
            "thinking": {"type": "adaptive"},
            "output_config": {
                "effort": effort,
                "format": {"type": "json_schema", "schema": schema},
            },
        }
        if tools:
            params["tools"] = tools

        if self._fallbacks_enabled:
            try:
                return self._client.beta.messages.create(
                    betas=[REFUSAL_FALLBACK_BETA], fallbacks="default", **params
                )
            except anthropic.BadRequestError as exc:
                # The beta isn't available here -- stop trying and use the
                # stable endpoint for the rest of this process.
                log.warning("Disabling refusal fallbacks (%s)", exc)
                self._fallbacks_enabled = False

        try:
            return self._client.messages.create(**params)
        except anthropic.APIStatusError as exc:
            raise ProviderError(f"Claude API error {exc.status_code}: {exc}") from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError(f"Could not reach the Claude API: {exc}") from exc

    @staticmethod
    def _extract_json(response) -> dict[str, Any]:
        """Pull the JSON payload out of the response.

        ``output_config.format`` guarantees a text block of valid JSON, but
        thinking and web-search result blocks share the content list, so scan
        for the last text block rather than assuming index 0.
        """
        texts = [block.text for block in response.content if getattr(block, "type", None) == "text"]
        for text in reversed(texts):
            candidate = text.strip()
            if not candidate:
                continue
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
        raise ProviderError(
            f"No JSON object in Claude response (stop_reason={response.stop_reason})"
        )
