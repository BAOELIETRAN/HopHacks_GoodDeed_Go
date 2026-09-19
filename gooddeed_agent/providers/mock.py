"""Deterministic stub providers.

These exist so the backend and UI are never blocked on API keys. Output is
seeded from the inputs, so the same request always returns the same data --
a map that reshuffles on every refresh is useless for UI work.
"""

from __future__ import annotations

import hashlib
import random
from typing import Any, Sequence

# Fixture orgs, placed as small offsets from whatever coordinate is requested
# so they always land near the caller's map viewport.
_FIXTURE_ORGS: list[dict[str, Any]] = [
    {"name": "Riverside Community Food Bank", "query": "food bank", "types": ["food_bank"], "rating": 4.7,
     "rating_count": 312, "website": "https://riverside-foodbank.example.org", "d_lat": 0.006, "d_lng": 0.004},
    {"name": "Hope Street Shelter", "query": "homeless shelter", "types": ["homeless_shelter", "charity"], "rating": 4.5,
     "rating_count": 198, "website": "https://hopestreet.example.org", "d_lat": -0.009, "d_lng": 0.011},
    {"name": "Second Chance Animal Rescue", "query": "animal shelter", "types": ["animal_shelter"], "rating": 4.8,
     "rating_count": 540, "website": "https://secondchancerescue.example.org", "d_lat": 0.013, "d_lng": -0.007},
    {"name": "Green City Parks Alliance", "query": "park conservation", "types": ["environmental", "park"], "rating": 4.4,
     "rating_count": 87, "website": "https://greencity.example.org", "d_lat": -0.004, "d_lng": -0.014},
    {"name": "Eastside Senior Center", "query": "senior center", "types": ["senior_care", "community_center"], "rating": 4.6,
     "rating_count": 121, "website": "https://eastsideseniors.example.org", "d_lat": 0.018, "d_lng": 0.002},
    {"name": "Lincoln Library Literacy Program", "query": "library literacy", "types": ["education", "library"], "rating": 4.9,
     "rating_count": 233, "website": "https://lincolnlit.example.org", "d_lat": -0.015, "d_lng": 0.016},
    {"name": "Harbor Free Clinic", "query": "free clinic", "types": ["healthcare", "charity"], "rating": 4.3,
     "rating_count": 64, "website": "https://harborclinic.example.org", "d_lat": 0.021, "d_lng": -0.019},
    {"name": "Northgate Thrift & Donation Center", "query": "thrift store charity", "types": ["thrift_donation", "store"], "rating": 4.1,
     "rating_count": 405, "website": None, "d_lat": -0.022, "d_lng": -0.003},
    {"name": "Sunrise Youth Mentors", "query": "youth mentor", "types": ["youth_program"], "rating": 4.6,
     "rating_count": 45, "website": "https://sunriseyouth.example.org", "d_lat": 0.008, "d_lng": 0.024},
    {"name": "Bayview Cleanup Crew", "query": "community cleanup", "types": ["community_cleanup", "environmental"], "rating": 4.2,
     "rating_count": 29, "website": None, "d_lat": -0.011, "d_lng": -0.021},
]

_STREETS = ["Maple Ave", "3rd St", "Harbor Blvd", "Lincoln Way", "Cedar Ln", "Market St"]


def _seed(*parts: Any) -> random.Random:
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


class MockPlacesProvider:
    """Stands in for Google Places. Implements :class:`PlacesProvider`."""

    def search_nearby(
        self,
        lat: float,
        lng: float,
        radius_km: float,
        queries: Sequence[str],
        max_results: int = 20,
    ) -> list[dict[str, Any]]:
        rng = _seed(round(lat, 3), round(lng, 3), radius_km)
        results: list[dict[str, Any]] = []
        for index, org in enumerate(_FIXTURE_ORGS):
            # Scale the fixture offsets so results stay inside the radius.
            scale = min(1.0, radius_km / 3.0)
            plat = lat + org["d_lat"] * scale
            plng = lng + org["d_lng"] * scale
            results.append(
                {
                    "name": org["name"],
                    "address": f"{rng.randint(100, 3999)} {_STREETS[index % len(_STREETS)]}",
                    "lat": round(plat, 6),
                    "lng": round(plng, 6),
                    "types": list(org["types"]),
                    "rating": org["rating"],
                    "rating_count": org["rating_count"],
                    "website": org["website"],
                    "business_status": "OPERATIONAL",
                    "place_id": f"mock_{hashlib.md5(org['name'].encode()).hexdigest()[:12]}",
                    # Each fixture carries the query it would realistically
                    # have been found by, so categorization behaves like production.
                    "matched_query": org["query"],
                }
            )
        return results[:max_results]


class MockLLMProvider:
    """Stands in for Claude. Implements :class:`LLMProvider`.

    It inspects the JSON schema it was handed and produces a plausible,
    schema-shaped answer. Text in the prompt containing obvious spam markers
    steers it toward a rejection so the UI can exercise both branches.
    """

    #: Substrings that make the mock return a low-confidence / invalid verdict.
    REJECT_MARKERS = ("test test", "lorem ipsum", "asdf", "spam", "xxxxx")

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
        text = " ".join(
            block.get("text", "") for block in content if block.get("type") == "text"
        ).lower()
        has_image = any(block.get("type") == "image" for block in content)
        rng = _seed(text, has_image, use_web_search)

        looks_bad = any(marker in text for marker in self.REJECT_MARKERS) or len(text.strip()) < 15
        properties: dict[str, Any] = schema.get("properties", {})
        out: dict[str, Any] = {}

        for key, spec in properties.items():
            out[key] = self._value_for(key, spec, rng, looks_bad, has_image)
        return out

    def _value_for(
        self, key: str, spec: dict[str, Any], rng: random.Random, looks_bad: bool, has_image: bool
    ) -> Any:
        kind = spec.get("type")
        if "enum" in spec:
            choices = list(spec["enum"])
            if looks_bad and "other" in choices:
                return "other"
            return choices[rng.randrange(len(choices))]
        if kind == "boolean":
            # legit / is_valid / photo_matches_description all read the same way.
            return not looks_bad
        if kind == "number":
            if looks_bad:
                return round(rng.uniform(0.05, 0.3), 2)
            low = 0.7 if has_image else 0.6
            return round(rng.uniform(low, 0.95), 2)
        if kind == "integer":
            return rng.randint(1, 5)
        if kind == "array":
            return []
        # string
        if looks_bad:
            return f"[mock] Low-signal input; '{key}' could not be established."
        return f"[mock] Plausible '{key}' generated by MockLLMProvider (no API key set)."
