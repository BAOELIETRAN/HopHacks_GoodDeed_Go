"""Google Places API (New) provider.

Uses Text Search (``places:searchText``) rather than Nearby Search: the Places
type taxonomy has no reliable "nonprofit" type, so a handful of text queries
("food bank", "homeless shelter", ...) biased to a circle around the user
returns far better volunteer-relevant coverage than a type filter would.

Requires a Google Maps Platform key with **Places API (New)** enabled.
"""

from __future__ import annotations

import logging
from typing import Any, Sequence

import requests

from .base import ProviderError

log = logging.getLogger("gooddeed_agent.places")

_ENDPOINT = "https://places.googleapis.com/v1/places:searchText"

# Only the fields we use -- the field mask directly controls billing tier.
_FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.location",
        "places.types",
        "places.rating",
        "places.userRatingCount",
        "places.websiteUri",
        "places.businessStatus",
    ]
)

# Google caps the location bias radius at 50km.
_MAX_RADIUS_M = 50_000


class GooglePlacesProvider:
    """Implements :class:`PlacesProvider` against Places API (New)."""

    def __init__(self, api_key: str, timeout_s: float = 20.0, session: requests.Session | None = None):
        if not api_key:
            raise ValueError("GooglePlacesProvider requires an API key")
        self._api_key = api_key
        self._timeout = timeout_s
        self._session = session or requests.Session()

    def search_nearby(
        self,
        lat: float,
        lng: float,
        radius_km: float,
        queries: Sequence[str],
        max_results: int = 20,
    ) -> list[dict[str, Any]]:
        radius_m = min(max(float(radius_km) * 1000.0, 100.0), _MAX_RADIUS_M)
        # Per-query cap: several queries fan out, so keep each one small and
        # let the caller's dedupe/ranking pick the winners.
        per_query = max(3, min(20, max_results))

        seen: dict[str, dict[str, Any]] = {}
        for query in queries:
            try:
                places = self._search_text(query, lat, lng, radius_m, per_query)
            except ProviderError:
                raise
            except Exception as exc:  # network hiccup on one query shouldn't kill the batch
                log.warning("Places query %r failed: %s", query, exc)
                continue
            for place in places:
                record = self._normalize(place, query)
                if record is None:
                    continue
                # First query to surface a place wins; it is the most relevant one.
                seen.setdefault(record["place_id"], record)

        return list(seen.values())[:max_results]

    def _search_text(
        self, query: str, lat: float, lng: float, radius_m: float, max_results: int
    ) -> list[dict[str, Any]]:
        response = self._session.post(
            _ENDPOINT,
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": self._api_key,
                "X-Goog-FieldMask": _FIELD_MASK,
            },
            json={
                "textQuery": query,
                "maxResultCount": max_results,
                "locationBias": {
                    "circle": {
                        "center": {"latitude": lat, "longitude": lng},
                        "radius": radius_m,
                    }
                },
            },
            timeout=self._timeout,
        )
        if response.status_code in (401, 403):
            raise ProviderError(
                f"Google Places rejected the key ({response.status_code}). "
                "Check that 'Places API (New)' is enabled and the key is unrestricted "
                "for this referrer/IP."
            )
        if response.status_code >= 400:
            raise ProviderError(f"Google Places error {response.status_code}: {response.text[:300]}")
        return response.json().get("places", []) or []

    @staticmethod
    def _normalize(place: dict[str, Any], query: str) -> dict[str, Any] | None:
        location = place.get("location") or {}
        name = (place.get("displayName") or {}).get("text")
        place_id = place.get("id")
        if not name or not place_id or "latitude" not in location:
            return None
        return {
            "name": name,
            "address": place.get("formattedAddress") or "",
            "lat": float(location["latitude"]),
            "lng": float(location["longitude"]),
            "types": list(place.get("types") or []),
            "rating": place.get("rating"),
            "rating_count": place.get("userRatingCount"),
            "website": place.get("websiteUri"),
            "business_status": place.get("businessStatus"),
            "place_id": place_id,
            "matched_query": query,
        }
