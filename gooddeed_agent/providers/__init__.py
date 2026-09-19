"""Provider implementations and the factories that pick real or mock."""

from __future__ import annotations

import logging

from ..config import Settings, load_settings
from .base import LLMProvider, PlacesProvider, ProviderError
from .mock import MockLLMProvider, MockPlacesProvider

log = logging.getLogger("gooddeed_agent.providers")

__all__ = [
    "LLMProvider",
    "PlacesProvider",
    "ProviderError",
    "MockLLMProvider",
    "MockPlacesProvider",
    "get_places_provider",
    "get_llm_provider",
]


def get_places_provider(settings: Settings | None = None) -> PlacesProvider:
    """Real Google Places provider, or the mock when no key is configured."""
    settings = settings or load_settings()
    if settings.use_mock_places:
        log.info("Using MockPlacesProvider (no GOOGLE_MAPS_API_KEY, or mocks forced)")
        return MockPlacesProvider()
    from .google_places import GooglePlacesProvider

    return GooglePlacesProvider(settings.google_maps_api_key or "", settings.request_timeout_s)


def get_llm_provider(settings: Settings | None = None) -> LLMProvider:
    """The OpenAI provider, or the mock when no OPENAI_API_KEY is set."""
    settings = settings or load_settings()
    if settings.use_mock_llm:
        log.info("Using MockLLMProvider (no OPENAI_API_KEY, or mocks forced)")
        return MockLLMProvider()

    from .openai_llm import OpenAILLMProvider

    log.info("Using OpenAI (%s)", settings.model)
    return OpenAILLMProvider(settings)
