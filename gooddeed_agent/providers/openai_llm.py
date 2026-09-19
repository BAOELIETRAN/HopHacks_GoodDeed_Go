"""OpenAI-backed LLM provider (vision, web search, structured output).

The mirror of :mod:`claude_llm`, implementing the same
:class:`~.base.LLMProvider` protocol so the agent functions above it do not
change. Built on the Responses API rather than Chat Completions, because it
is the only one of the two that offers the hosted ``web_search`` tool, and
``trust_check`` and ``verify_donation_link`` are worthless without search.

Three shape differences from Anthropic have to be absorbed here:

* **Content blocks.** Callers build Anthropic-shaped blocks (and
  ``build_image_block`` is shared, so photo sniffing and the HEIC message stay
  in one place). They are translated on the way out.
* **Structured output.** ``text.format`` with ``strict: true`` is the
  equivalent of ``output_config.format``. Strict mode is fussier than
  Anthropic's -- every object needs ``additionalProperties: false`` and a
  ``required`` naming every property -- so the schema is normalised rather
  than trusted.
* **Reasoning effort.** Only reasoning models accept it; sending it to a
  gpt-4o-class model is a 400, so it is sent conditionally.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..config import Settings
from .base import ProviderError

log = logging.getLogger("gooddeed_agent.openai")

# Keywords JSON-schema strict mode rejects. The agent clamps numbers itself
# (see ScoreResult), so dropping bounds costs nothing but a 400.
_UNSUPPORTED_KEYWORDS = frozenset({
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
    "minLength", "maxLength", "pattern", "minItems", "maxItems", "default", "format",
})

# Model families that accept a reasoning effort.
_REASONING_PREFIXES = ("o1", "o3", "o4", "gpt-5")


def _is_reasoning_model(model: str) -> bool:
    name = model.lower().removeprefix("openai/")
    return name.startswith(_REASONING_PREFIXES)


def to_openai_content(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate Anthropic content blocks into Responses API input parts."""
    out: list[dict[str, Any]] = []
    for block in blocks:
        kind = block.get("type")
        if kind == "text":
            out.append({"type": "input_text", "text": block.get("text", "")})
        elif kind == "image":
            source = block.get("source") or {}
            if source.get("type") == "url":
                url = source.get("url", "")
            elif source.get("type") == "base64":
                media = source.get("media_type") or "image/jpeg"
                url = f"data:{media};base64,{source.get('data', '')}"
            else:
                raise ProviderError(f"Unsupported image source: {source.get('type')!r}")
            out.append({"type": "input_image", "image_url": url})
        else:
            raise ProviderError(f"Unsupported content block: {kind!r}")
    return out


def to_strict_schema(schema: Any) -> Any:
    """Normalise a JSON schema for strict structured output.

    Every object gets ``additionalProperties: false`` and a ``required``
    listing all of its properties, and unsupported validation keywords are
    dropped. The agent's own schemas already satisfy this; normalising anyway
    means a future schema cannot break the provider from a distance.
    """
    if isinstance(schema, list):
        return [to_strict_schema(s) for s in schema]
    if not isinstance(schema, dict):
        return schema

    out = {k: to_strict_schema(v) for k, v in schema.items() if k not in _UNSUPPORTED_KEYWORDS}
    if out.get("type") == "object":
        out["additionalProperties"] = False
        props = out.get("properties")
        if isinstance(props, dict):
            # Strict mode has no notion of an optional field; every key must
            # be required. Callers already treat missing keys defensively.
            out["required"] = list(props)
    return out


class OpenAILLMProvider:
    """Implements :class:`LLMProvider` against the OpenAI Responses API."""

    def __init__(self, settings: Settings, client: Any | None = None):
        if not settings.openai_api_key and client is None:
            raise ValueError("OpenAILLMProvider requires OPENAI_API_KEY")
        self._settings = settings
        if client is not None:
            self._client = client
        else:
            try:
                from openai import OpenAI
            except ImportError as exc:  # pragma: no cover - import-time guard
                raise ProviderError(
                    "The 'openai' package is not installed. Run: pip install openai"
                ) from exc
            self._client = OpenAI(
                api_key=settings.openai_api_key, timeout=settings.request_timeout_s
            )

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
        params: dict[str, Any] = {
            "model": self._settings.model,
            "instructions": system,
            "input": [{"role": "user", "content": to_openai_content(content)}],
            "max_output_tokens": max_tokens,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "gooddeed_result",
                    "schema": to_strict_schema(schema),
                    "strict": True,
                }
            },
        }
        if use_web_search:
            params["tools"] = [{"type": "web_search"}]
        if _is_reasoning_model(self._settings.model):
            params["reasoning"] = {"effort": effort}

        try:
            response = self._client.responses.create(**params)
        except Exception as exc:
            # The SDK's typed errors are not imported here so the module stays
            # importable without the package; the status code is read off the
            # exception when it carries one.
            status = getattr(exc, "status_code", None)
            raise ProviderError(
                f"OpenAI API error{f' {status}' if status else ''}: {exc}"
            ) from exc

        return self._extract_json(response)

    @staticmethod
    def _extract_json(response: Any) -> dict[str, Any]:
        """Pull the JSON payload out of the response.

        ``output_text`` is the documented shortcut, but it is empty when the
        model stops early (a hit ``max_output_tokens``, or a refusal), so the
        output list is walked as a fallback before giving up. Reasoning and
        web-search items share that list, hence scanning for the last usable
        text rather than taking the first.
        """
        texts: list[str] = []
        shortcut = getattr(response, "output_text", None)
        if isinstance(shortcut, str) and shortcut.strip():
            texts.append(shortcut)

        for item in getattr(response, "output", None) or []:
            for part in getattr(item, "content", None) or []:
                if getattr(part, "type", None) == "refusal":
                    raise ProviderError(
                        f"OpenAI declined the request: {getattr(part, 'refusal', '')}"
                    )
                text = getattr(part, "text", None)
                if isinstance(text, str) and text.strip():
                    texts.append(text)

        for text in reversed(texts):
            try:
                parsed = json.loads(text.strip())
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed

        status = getattr(response, "status", None)
        incomplete = getattr(response, "incomplete_details", None)
        raise ProviderError(
            f"No JSON object in OpenAI response (status={status}, incomplete={incomplete})"
        )
