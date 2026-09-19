"""Runtime configuration for the GoodDeed Go agent layer.

The guiding rule: the package must import and run with *zero* credentials so
the backend and UI can build against stub data. Missing keys downgrade the
relevant provider to its mock instead of raising.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("gooddeed_agent")

_dotenv_loaded = False
_warned_legacy_key = False

# The model every LLM call uses. It has to handle vision, hosted web search and
# strict structured output in a single request, which is what the agent
# functions assume.
DEFAULT_MODEL = "gpt-5"


def _load_dotenv_once() -> None:
    """Load a ``.env`` from the project root, if one exists.

    Values already in the real environment win, so an exported key always
    beats the file. python-dotenv is optional: without it, exported
    environment variables still work and we just skip the file.
    """
    global _dotenv_loaded
    if _dotenv_loaded:
        return
    _dotenv_loaded = True
    try:
        from dotenv import load_dotenv
    except ImportError:
        env_path = Path(__file__).resolve().parent.parent / ".env"
        if env_path.exists():
            log.warning(
                "Found %s but python-dotenv is not installed, so it was ignored. "
                "Run 'pip install python-dotenv' or export the variables instead.",
                env_path,
            )
        return
    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _warn_if_still_on_legacy_key(openai_key: str | None) -> None:
    """Say so, once, when only the retired ANTHROPIC_API_KEY is configured.

    Without this, a deployment that was never switched over quietly serves mock
    scoring: the app looks healthy while every photo gets a made-up verdict.
    """
    global _warned_legacy_key
    if _warned_legacy_key or openai_key or not os.environ.get("ANTHROPIC_API_KEY"):
        return
    _warned_legacy_key = True
    log.warning(
        "ANTHROPIC_API_KEY is set but no longer used. Set OPENAI_API_KEY instead; "
        "until then the agent serves mock data."
    )


@dataclass(frozen=True)
class Settings:
    openai_api_key: str | None
    google_maps_api_key: str | None
    model: str
    force_mocks: bool
    request_timeout_s: float

    @property
    def use_mock_llm(self) -> bool:
        """True when LLM calls should be served from stub data."""
        return self.force_mocks or not self.openai_api_key

    @property
    def use_mock_places(self) -> bool:
        """True when Google Places calls should be served from stub data."""
        return self.force_mocks or not self.google_maps_api_key


def load_settings() -> Settings:
    """Read settings from the environment on every call.

    Deliberately not cached: teammates set keys in a ``.env`` loaded after
    import, and a hot-reloading server should pick that up.
    """
    _load_dotenv_once()
    openai_key = os.environ.get("OPENAI_API_KEY") or None
    _warn_if_still_on_legacy_key(openai_key)

    model = os.environ.get("GOODDEED_MODEL") or DEFAULT_MODEL
    # A claude-* name left in an old .env or dashboard would 404 on OpenAI.
    if model.lower().startswith("claude"):
        log.warning("GOODDEED_MODEL=%s is not an OpenAI model; using %s instead", model, DEFAULT_MODEL)
        model = DEFAULT_MODEL

    return Settings(
        openai_api_key=openai_key,
        google_maps_api_key=(
            os.environ.get("GOOGLE_MAPS_API_KEY")
            or os.environ.get("GOOGLE_PLACES_API_KEY")
            or None
        ),
        model=model,
        force_mocks=_env_flag("GOODDEED_USE_MOCKS"),
        request_timeout_s=float(os.environ.get("GOODDEED_TIMEOUT_S", "60")),
    )
