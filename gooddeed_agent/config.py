"""Runtime configuration for the GoodDeed Go agent layer.

The guiding rule: the package must import and run with *zero* credentials so
the backend and UI can build against stub data. Missing keys downgrade the
relevant provider to its mock instead of raising.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

log = logging.getLogger("gooddeed_agent")

# Claude model used for every LLM call. Opus 5 handles vision, web search and
# structured output in one request.
DEFAULT_MODEL = "claude-opus-5"

# Server-side web search tool version. Bump this one constant when a newer
# variant ships.
WEB_SEARCH_TOOL_TYPE = "web_search_20260209"

# Server-side refusal fallback: if a safety classifier declines a request,
# Anthropic reroutes it instead of handing us an empty response.
REFUSAL_FALLBACK_BETA = "server-side-fallback-2026-07-01"


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str | None
    google_maps_api_key: str | None
    model: str
    force_mocks: bool
    enable_refusal_fallback: bool
    request_timeout_s: float

    @property
    def use_mock_llm(self) -> bool:
        """True when Claude calls should be served from stub data."""
        return self.force_mocks or not self.anthropic_api_key

    @property
    def use_mock_places(self) -> bool:
        """True when Google Places calls should be served from stub data."""
        return self.force_mocks or not self.google_maps_api_key


def load_settings() -> Settings:
    """Read settings from the environment on every call.

    Deliberately not cached: teammates set keys in a ``.env`` loaded after
    import, and a hot-reloading server should pick that up.
    """
    return Settings(
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
        google_maps_api_key=(
            os.environ.get("GOOGLE_MAPS_API_KEY")
            or os.environ.get("GOOGLE_PLACES_API_KEY")
            or None
        ),
        model=os.environ.get("GOODDEED_MODEL", DEFAULT_MODEL),
        force_mocks=_env_flag("GOODDEED_USE_MOCKS"),
        enable_refusal_fallback=_env_flag("GOODDEED_REFUSAL_FALLBACK", True),
        request_timeout_s=float(os.environ.get("GOODDEED_TIMEOUT_S", "60")),
    )
