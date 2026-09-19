"""The seam between agent logic and the outside world.

Everything that costs money or needs a network lives behind one of these two
protocols. Agent functions accept a provider argument, so tests and the
mock-mode build swap in stubs without touching business logic.
"""

from __future__ import annotations

from typing import Any, Protocol, Sequence, runtime_checkable


@runtime_checkable
class PlacesProvider(Protocol):
    """Finds real-world places near a coordinate."""

    def search_nearby(
        self,
        lat: float,
        lng: float,
        radius_km: float,
        queries: Sequence[str],
        max_results: int = 20,
    ) -> list[dict[str, Any]]:
        """Return raw place records.

        Each record uses these keys (missing values may be ``None``):
        ``name``, ``address``, ``lat``, ``lng``, ``types`` (list[str]),
        ``rating``, ``rating_count``, ``website``, ``business_status``,
        ``place_id``, ``matched_query``.
        """
        ...


@runtime_checkable
class LLMProvider(Protocol):
    """Runs a structured LLM request and returns parsed JSON."""

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
        """Send ``content`` (text and/or image blocks) and return a dict that
        validates against ``schema``.

        Implementations must raise :class:`ProviderError` on failure rather
        than returning a partial dict, so callers can apply their own fallback.
        """
        ...


class ProviderError(RuntimeError):
    """An external call failed in a way the caller should handle."""
