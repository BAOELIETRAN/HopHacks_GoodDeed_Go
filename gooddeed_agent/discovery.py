"""Opportunity discovery and organization trust checks.

``find_opportunities`` maps the area around a user; ``trust_check`` decides
whether an org is real enough to hand out quests for. They live together
because discovery calls trust checking to fill in ``legitimacy_score``.
"""

from __future__ import annotations

import logging
from typing import Any, Sequence

from .models import Opportunity, TrustResult
from .providers import LLMProvider, PlacesProvider, get_llm_provider, get_places_provider
from .scoring import normalize_category, quest_type_for

log = logging.getLogger("gooddeed_agent.discovery")

#: Text queries fanned out to Places. The Places type taxonomy has no
#: "nonprofit" type, so these carry the search.
DEFAULT_QUERIES: tuple[str, ...] = (
    "food bank",
    "homeless shelter",
    "animal shelter",
    "soup kitchen",
    "volunteer organization",
    "community center",
    "charity donation center",
    "senior center",
    "thrift store charity",
    "habitat for humanity",
)

#: Places API type -> our canonical category. First match wins.
_TYPE_TO_CATEGORY: tuple[tuple[str, str], ...] = (
    ("food_bank", "food_bank"),
    ("homeless_shelter", "homeless_shelter"),
    ("animal_shelter", "animal_shelter"),
    ("veterinary_care", "animal_shelter"),
    ("senior_center", "senior_care"),
    ("nursing_home", "senior_care"),
    ("hospital", "healthcare"),
    ("doctor", "healthcare"),
    ("clinic", "healthcare"),
    ("library", "education"),
    ("school", "education"),
    ("university", "education"),
    ("park", "environmental"),
    ("church", "religious"),
    ("mosque", "religious"),
    ("synagogue", "religious"),
    ("hindu_temple", "religious"),
    ("place_of_worship", "religious"),
    ("thrift_store", "thrift_donation"),
    ("store", "thrift_donation"),
    ("community_center", "community_center"),
)

#: Search-query keyword -> category. Ordered most-specific-first, because the
#: first match wins -- "animal shelter" must be tested before bare "shelter".
_QUERY_TO_CATEGORY: tuple[tuple[str, str], ...] = (
    ("animal shelter", "animal_shelter"),
    ("animal rescue", "animal_shelter"),
    ("humane society", "animal_shelter"),
    ("spca", "animal_shelter"),
    ("animal", "animal_shelter"),
    ("food bank", "food_bank"),
    ("soup kitchen", "food_bank"),
    ("food pantry", "food_bank"),
    ("pantry", "food_bank"),
    ("meals on wheels", "food_bank"),
    ("homeless", "homeless_shelter"),
    ("shelter", "homeless_shelter"),
    ("rescue mission", "homeless_shelter"),
    ("senior", "senior_care"),
    ("elder", "senior_care"),
    ("hospice", "senior_care"),
    ("free clinic", "healthcare"),
    ("clinic", "healthcare"),
    ("blood drive", "healthcare"),
    ("health", "healthcare"),
    ("literacy", "education"),
    ("tutor", "education"),
    ("library", "education"),
    ("youth", "youth_program"),
    ("mentor", "youth_program"),
    ("boys & girls club", "youth_program"),
    ("cleanup", "community_cleanup"),
    ("clean-up", "community_cleanup"),
    ("habitat for humanity", "community_cleanup"),
    ("conservation", "environmental"),
    ("environment", "environmental"),
    ("park", "environmental"),
    ("thrift", "thrift_donation"),
    ("donation center", "thrift_donation"),
    ("goodwill", "thrift_donation"),
    ("community center", "community_center"),
)


_TRUST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "legit": {"type": "boolean"},
        "confidence": {"type": "number"},
        "summary": {"type": "string"},
    },
    "required": ["legit", "confidence", "summary"],
    "additionalProperties": False,
}

_TRUST_SYSTEM = """You verify whether an organization is a real, operating \
nonprofit or volunteer site, for a volunteering app that will send users there \
in person.

Search the web for the organization, then judge:
- Does it exist at (or near) the stated address, and is it currently operating?
- Is there independent evidence: a registered charity listing (IRS 501(c)(3), \
Charity Navigator, GuideStar/Candid), news coverage, a maintained website, or \
a local government partner page?
- Does it actually accept volunteers or in-person visitors?
- Are there credible scam, fraud, or permanent-closure reports?

Set legit=true only when the evidence supports a real, operating organization. \
Set confidence to how sure you are, where 0.5 means genuinely uncertain. A \
common, generic name with no findable web presence is low confidence, not \
automatically illegitimate -- say so in the summary.

Never invent citations or facts you did not find. Keep the summary under 45 \
words and state what the evidence actually was."""


def categorize(types: Sequence[str], matched_query: str = "", name: str = "") -> str:
    """Best-effort mapping of a Places record onto a canonical category."""
    haystack = f"{matched_query} {name}".lower()
    # The query the org was found by is a stronger signal than Places types,
    # which are usually just "point_of_interest, establishment".
    for keyword, category in _QUERY_TO_CATEGORY:
        if keyword in haystack:
            return category
    lowered = {t.lower() for t in types}
    for place_type, category in _TYPE_TO_CATEGORY:
        if place_type in lowered:
            return category
    return "other"


def heuristic_legitimacy(place: dict[str, Any]) -> float:
    """Cheap legitimacy estimate from Places metadata alone.

    Used when web verification is off (the default, for speed). Starts at a
    neutral 0.5 and moves on review volume, review quality, and whether there
    is a website.

    Permanent closure is handled separately, as a hard floor rather than a
    penalty: a beloved food bank that shut down last year still has hundreds
    of five-star reviews, and no amount of good reputation should put a closed
    building back on the map.
    """
    status = (place.get("business_status") or "").upper()
    if status == "CLOSED_PERMANENTLY":
        return 0.0

    score = 0.5

    count = place.get("rating_count") or 0
    if count >= 500:
        score += 0.20
    elif count >= 100:
        score += 0.15
    elif count >= 25:
        score += 0.08
    elif count < 5:
        score -= 0.10

    rating = place.get("rating")
    if rating is not None:
        if rating >= 4.5:
            score += 0.10
        elif rating >= 4.0:
            score += 0.05
        elif rating < 3.0:
            score -= 0.15

    if place.get("website"):
        score += 0.10

    if status == "CLOSED_TEMPORARILY":
        score -= 0.15

    return round(max(0.0, min(1.0, score)), 2)


def trust_check(
    org_name: str,
    address: str,
    *,
    llm: LLMProvider | None = None,
) -> dict[str, Any]:
    """Decide whether an organization looks legitimate.

    Runs a web search and summarizes the evidence. Gates which orgs are
    allowed to appear as quests.

    Returns ``{"legit": bool, "confidence": float, "summary": str}``.

    On provider failure this returns a neutral, non-committal result rather
    than raising, so one bad lookup cannot take down a map request. Callers
    that need to distinguish "unverifiable" from "verified fake" should check
    ``confidence``: failures come back at 0.0.
    """
    llm = llm or get_llm_provider()
    prompt = (
        f"Organization name: {org_name}\n"
        f"Address: {address or 'unknown'}\n\n"
        "Search the web and report whether this is a real, operating "
        "organization that accepts volunteers or visitors."
    )
    try:
        raw = llm.complete_json(
            system=_TRUST_SYSTEM,
            content=[{"type": "text", "text": prompt}],
            schema=_TRUST_SCHEMA,
            effort="medium",
            use_web_search=True,
        )
    except Exception as exc:  # deliberately total: a failed lookup must not break the map
        log.warning("trust_check failed for %r: %s", org_name, exc)
        return TrustResult(
            legit=False,
            confidence=0.0,
            summary=f"Could not verify: {exc}",
        ).to_dict()

    return TrustResult(
        legit=bool(raw.get("legit", False)),
        confidence=round(max(0.0, min(1.0, float(raw.get("confidence", 0.0)))), 2),
        summary=str(raw.get("summary", "")).strip(),
    ).to_dict()


def find_opportunities(
    lat: float,
    lng: float,
    radius_km: float = 5.0,
    *,
    queries: Sequence[str] | None = None,
    max_results: int = 20,
    min_legitimacy: float = 0.4,
    verify: bool = False,
    max_verify: int = 5,
    places: PlacesProvider | None = None,
    llm: LLMProvider | None = None,
) -> list[dict[str, Any]]:
    """Find nearby volunteer opportunities and shape them into quests.

    Args:
        lat, lng: Center of the search.
        radius_km: Search radius; clamped to Google's 50km ceiling upstream.
        queries: Override the default nonprofit search terms.
        max_results: Cap on returned opportunities.
        min_legitimacy: Drop anything scoring below this. Keeps permanently
            closed and obviously-not-a-nonprofit results off the map.
        verify: Run a real web-search trust check on the top results. Off by
            default because it costs one LLM call per org; turn it on for a
            curated map refresh rather than every pan of the viewport.
        max_verify: How many of the top results to verify when ``verify`` is on.
        places, llm: Injected providers. Defaults come from the environment,
            falling back to mocks when keys are absent.

    Returns:
        A list of Opportunity dicts, highest legitimacy first.
    """
    places = places or get_places_provider()
    search_terms = tuple(queries) if queries else DEFAULT_QUERIES

    try:
        raw_places = places.search_nearby(lat, lng, radius_km, search_terms, max_results * 2)
    except Exception as exc:  # incl. raw connection errors, not just ProviderError
        log.error("Places lookup failed: %s", exc)
        return []

    scored: list[tuple[float, dict[str, Any]]] = []
    for place in raw_places:
        category = categorize(place.get("types") or [], place.get("matched_query", ""), place["name"])
        scored.append((heuristic_legitimacy(place), {**place, "category": category}))

    scored.sort(key=lambda item: -item[0])

    # Verification is the expensive step, so only spend it on the best
    # candidates -- and let it override the heuristic where it disagrees.
    if verify and max_verify > 0:
        llm = llm or get_llm_provider()
        for index in range(min(max_verify, len(scored))):
            heuristic, place = scored[index]
            result = trust_check(place["name"], place.get("address", ""), llm=llm)
            if result["confidence"] > 0.0:
                verified = result["confidence"] if result["legit"] else result["confidence"] * 0.3
                # Blend so a confident web verdict dominates but Places signal
                # still counts for something.
                scored[index] = (round(0.75 * verified + 0.25 * heuristic, 2), place)
        scored.sort(key=lambda item: -item[0])

    opportunities: list[dict[str, Any]] = []
    for legitimacy, place in scored:
        if legitimacy < min_legitimacy:
            continue
        category = normalize_category(place["category"])
        opportunities.append(
            Opportunity(
                org_name=place["name"],
                address=place.get("address") or "",
                lat=float(place["lat"]),
                lng=float(place["lng"]),
                category=category,
                legitimacy_score=legitimacy,
                quest_type=quest_type_for(category),
            ).to_dict()
        )
        if len(opportunities) >= max_results:
            break

    return opportunities
