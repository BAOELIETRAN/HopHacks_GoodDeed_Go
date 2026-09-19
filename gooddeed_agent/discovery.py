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

#: Philanthropic search queries, grouped by domain.
#:
#: The Places taxonomy has no "nonprofit" type -- most charities come back as
#: ``point_of_interest, establishment`` -- so these text queries carry the
#: search. Each one is a separate Places request, which is what makes breadth
#: cost money; see ``DEFAULT_QUERIES`` below.
QUERY_PACKS: dict[str, tuple[str, ...]] = {
    "food": (
        "food bank",
        "soup kitchen",
        "food pantry",
        "community fridge",
        "meal delivery charity",
    ),
    "housing": (
        "homeless shelter",
        "rescue mission",
        "transitional housing nonprofit",
        "habitat for humanity",
    ),
    "animals": (
        "animal shelter",
        "animal rescue",
        "humane society",
        "wildlife rehabilitation center",
    ),
    "environment": (
        "environmental nonprofit",
        "conservation organization",
        "community garden",
        "park conservancy",
        "nature center",
    ),
    "health": (
        "free clinic",
        "blood donation center",
        "hospice",
        "health nonprofit",
    ),
    "seniors": (
        "senior center",
        "meals on wheels",
        "senior services nonprofit",
    ),
    "youth_education": (
        "youth mentoring program",
        "boys and girls club",
        "literacy program",
        "tutoring nonprofit",
        "public library",
        "after school program",
    ),
    "crisis": (
        "crisis center",
        "domestic violence shelter",
        "addiction recovery center",
        "community mental health nonprofit",
    ),
    "veterans": (
        "veterans organization",
        "veterans service center",
    ),
    "disability": (
        "disability services nonprofit",
        "special needs organization",
    ),
    "immigrant": (
        "refugee resettlement agency",
        "immigrant services nonprofit",
    ),
    "goods": (
        "thrift store charity",
        "donation center",
        "goodwill",
        "salvation army",
    ),
    "community": (
        "community center",
        "volunteer organization",
        "nonprofit organization",
        "mutual aid group",
        "charity",
    ),
    "disaster": (
        "red cross",
        "disaster relief organization",
    ),
    "arts": (
        "museum",
        "community arts nonprofit",
    ),
    # Small, local, often unincorporated. These rarely rank in a generic
    # "charity" search but are most of what philanthropy actually looks like.
    "grassroots": (
        "mutual aid",
        "community fridge",
        "little free library",
        "neighborhood association",
        "tool library",
        "free store",
        "community land trust",
        "block association",
    ),
}

#: The default fan-out: the broadest one or two queries from every domain.
#:
#: This is a deliberate cost/coverage tradeoff. Every query is one billed
#: Places request, so searching all of ``QUERY_PACKS`` costs roughly three
#: times as much per map refresh. Start here; reach for ``packs=`` or
#: ``queries=`` when a demo needs depth in one area.
DEFAULT_QUERIES: tuple[str, ...] = (
    "food bank",
    "soup kitchen",
    "homeless shelter",
    "animal shelter",
    "environmental nonprofit",
    "community garden",
    "free clinic",
    "senior center",
    "youth mentoring program",
    "literacy program",
    "crisis center",
    "veterans organization",
    "disability services nonprofit",
    "refugee resettlement agency",
    "thrift store charity",
    "volunteer organization",
    "nonprofit organization",
    "community center",
    "mutual aid",
    "community fridge",
)


def all_queries() -> tuple[str, ...]:
    """Every query in every pack, deduped, order preserved."""
    seen: dict[str, None] = {}
    for pack in QUERY_PACKS.values():
        for query in pack:
            seen.setdefault(query, None)
    return tuple(seen)


def queries_for_packs(packs: Sequence[str]) -> tuple[str, ...]:
    """Queries for the named domains. Unknown names raise, rather than
    silently searching for nothing."""
    unknown = [p for p in packs if p not in QUERY_PACKS]
    if unknown:
        raise ValueError(
            f"Unknown query pack(s): {', '.join(unknown)}. "
            f"Available: {', '.join(sorted(QUERY_PACKS))}"
        )
    seen: dict[str, None] = {}
    for pack in packs:
        for query in QUERY_PACKS[pack]:
            seen.setdefault(query, None)
    return tuple(seen)


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
#: first match wins -- "animal shelter" must beat bare "shelter", and
#: "domestic violence shelter" must beat both.
_QUERY_TO_CATEGORY: tuple[tuple[str, str], ...] = (
    # Animals first: "wildlife rehabilitation" contains "rehab", and
    # "animal rescue" contains "rescue". Both would otherwise be captured
    # by the crisis and housing entries below.
    ("animal shelter", "animal_shelter"),
    ("animal rescue", "animal_shelter"),
    ("humane society", "animal_shelter"),
    ("wildlife", "animal_shelter"),
    ("spca", "animal_shelter"),
    ("animal", "animal_shelter"),
    # Crisis work -- before the generic "shelter".
    ("domestic violence", "crisis_support"),
    ("crisis", "crisis_support"),
    ("suicide prevention", "crisis_support"),
    ("addiction recovery", "crisis_support"),
    ("addiction", "crisis_support"),
    ("drug rehab", "crisis_support"),
    ("alcohol rehab", "crisis_support"),
    ("substance abuse", "crisis_support"),
    ("mental health", "crisis_support"),
    ("womens shelter", "crisis_support"),
    # Housing -- "rescue mission" must beat the "rescue" above it being
    # animal-only, so it is spelled out here.
    ("rescue mission", "homeless_shelter"),
    ("homeless", "homeless_shelter"),
    ("transitional housing", "homeless_shelter"),
    ("habitat for humanity", "homeless_shelter"),
    ("shelter", "homeless_shelter"),
    # Food.
    ("food bank", "food_bank"),
    ("soup kitchen", "food_bank"),
    ("food pantry", "food_bank"),
    ("community fridge", "food_bank"),
    ("meals on wheels", "senior_care"),
    ("meal delivery", "food_bank"),
    ("pantry", "food_bank"),
    # Veterans, disability, immigrants -- before generic "services".
    ("veteran", "veterans"),
    ("vfw", "veterans"),
    ("american legion", "veterans"),
    ("disability", "disability_services"),
    ("special needs", "disability_services"),
    ("refugee", "refugee_services"),
    ("immigrant", "refugee_services"),
    ("asylum", "refugee_services"),
    # Seniors.
    ("senior", "senior_care"),
    ("elder", "senior_care"),
    ("hospice", "senior_care"),
    ("nursing home", "senior_care"),
    # Health.
    ("free clinic", "healthcare"),
    ("blood donation", "healthcare"),
    ("blood drive", "healthcare"),
    ("clinic", "healthcare"),
    ("health", "healthcare"),
    # Youth and education.
    ("youth mentoring", "youth_program"),
    ("boys and girls club", "youth_program"),
    ("boys & girls club", "youth_program"),
    ("after school", "youth_program"),
    ("youth", "youth_program"),
    ("mentor", "youth_program"),
    ("tool library", "community_center"),
    ("literacy", "education"),
    ("tutoring", "education"),
    ("tutor", "education"),
    ("library", "education"),
    ("school", "education"),
    # Environment.
    ("community garden", "environmental"),
    ("conservation", "environmental"),
    ("environmental", "environmental"),
    ("park conservancy", "environmental"),
    ("nature center", "environmental"),
    ("watershed", "environmental"),
    ("park", "environmental"),
    ("cleanup", "community_cleanup"),
    ("clean-up", "community_cleanup"),
    # Disaster.
    ("red cross", "disaster_relief"),
    ("disaster relief", "disaster_relief"),
    ("disaster", "disaster_relief"),
    # Goods.
    ("thrift", "thrift_donation"),
    ("goodwill", "thrift_donation"),
    ("salvation army", "thrift_donation"),
    ("donation center", "thrift_donation"),
    # Arts and culture.
    ("museum", "arts_culture"),
    ("arts nonprofit", "arts_culture"),
    ("community arts", "arts_culture"),
    ("historical society", "arts_culture"),
    # Faith.
    ("church", "religious"),
    ("mosque", "religious"),
    ("synagogue", "religious"),
    ("temple", "religious"),
    # Grassroots terms. "community fridge" and "free store" are food and
    # goods respectively; the rest are neighborhood infrastructure.
    ("little free library", "education"),
    ("free store", "thrift_donation"),
    ("community land trust", "community_center"),
    ("neighborhood association", "community_center"),
    ("block association", "community_center"),
    # Generic catch-alls -- last, so anything specific wins first.
    ("mutual aid", "community_center"),
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

Small is not suspicious. Most philanthropy is small: neighborhood mutual aid \
groups, community fridges, church pantries, volunteer-run gardens. These \
often have no 501(c)(3) status, no press coverage, and nothing but a Facebook \
page or a flyer -- that is normal, not a red flag. Judge whether the thing \
exists and helps people, not whether it is large, incorporated or well known. \
A verifiable local group with a modest footprint should score legit=true.

Do set legit=false for an organization that is real but not philanthropic -- \
a for-profit business, a private contractor, a government office with no \
volunteer program -- and say which it is.

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


#: Below this many reviews we treat an org as grassroots: a neighborhood
#: garden, a mutual aid group, a church pantry. Small is not suspicious.
GRASSROOTS_REVIEW_THRESHOLD = 25


def heuristic_legitimacy(place: dict[str, Any]) -> float:
    """Cheap estimate of whether an org is *real*, not whether it is *famous*.

    Used when web verification is off (the default, for speed).

    The distinction matters for a philanthropy app. An earlier version gave
    +0.20 for 500+ reviews and -0.10 for under 5, a 0.30 spread that made
    review count the dominant term -- so a huge institution always outranked
    the neighborhood community fridge, and half the orgs discovered never
    reached the map. Review count is now weak, saturating evidence: twenty
    reviews confirm a place exists about as well as nine hundred do. A new or
    tiny org is *unknown*, never *illegitimate*, so a low count is never a
    penalty.

    Permanent closure is the one hard gate: a beloved food bank that shut
    down last year still has hundreds of five-star reviews, and no amount of
    reputation should put a closed building back on the map.
    """
    status = (place.get("business_status") or "").upper()
    if status == "CLOSED_PERMANENTLY":
        return 0.0

    # A Places listing at all is weak evidence the place exists.
    score = 0.55

    # Evidence of a real operation, saturating fast and never negative.
    count = place.get("rating_count") or 0
    if count >= 20:
        score += 0.12
    elif count >= 5:
        score += 0.08
    elif count >= 1:
        score += 0.04

    # Reputation. Only a genuinely bad record counts against an org.
    rating = place.get("rating")
    if rating is not None:
        if rating >= 4.5:
            score += 0.10
        elif rating >= 4.0:
            score += 0.06
        elif rating < 3.0:
            score -= 0.15

    if place.get("website"):
        score += 0.10

    if status == "CLOSED_TEMPORARILY":
        score -= 0.15

    return round(max(0.0, min(1.0, score)), 2)


def is_grassroots(place: dict[str, Any]) -> bool:
    """True for small, local organizations -- the ones an app about
    philanthropy should surface, not bury."""
    return (place.get("rating_count") or 0) < GRASSROOTS_REVIEW_THRESHOLD


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


def _interleave_by_category(
    entries: list[tuple[dict[str, Any], bool]], max_results: int
) -> list[dict[str, Any]]:
    """Rank for a map, not for a leaderboard.

    Takes ``(opportunity, is_grassroots)`` pairs and applies two passes of
    mixing:

    1. **Across categories.** A pure legitimacy sort means big well-reviewed
       food banks sweep the top of the list and the player never sees the
       animal shelter two blocks away. Categories are visited round-robin, in
       order of their best-scoring member, so the single strongest org
       overall still leads.
    2. **Within a category, across org size.** Even with popularity mostly
       removed from the score, established orgs still edge out small ones, so
       each category alternates grassroots and established. Philanthropy is
       mostly small organizations; a map that only shows the famous ones has
       the wrong idea of the subject.

    Repeat org names are pushed later within each sub-list, so one thrift
    chain's four branches cannot take every slot in their category. All four
    are still returned -- they are separate map pins.
    """
    buckets: dict[str, list[tuple[dict[str, Any], bool]]] = {}
    for entry in entries:
        buckets.setdefault(entry[0]["category"], []).append(entry)

    def demote_repeat_names(
        group: list[tuple[dict[str, Any], bool]]
    ) -> list[tuple[dict[str, Any], bool]]:
        counts: dict[str, int] = {}
        ranked = []
        for entry in group:
            name = entry[0]["org_name"].casefold()
            ranked.append((counts.get(name, 0), entry))
            counts[name] = counts.get(name, 0) + 1
        return [entry for _rank, entry in sorted(ranked, key=lambda r: r[0])]

    def mix_by_size(
        group: list[tuple[dict[str, Any], bool]], grassroots_first: bool
    ) -> list[dict[str, Any]]:
        grassroots = demote_repeat_names([e for e in group if e[1]])
        established = demote_repeat_names([e for e in group if not e[1]])
        first, second = (
            (grassroots, established) if grassroots_first else (established, grassroots)
        )
        mixed: list[dict[str, Any]] = []
        for index in range(max(len(first), len(second))):
            if index < len(first):
                mixed.append(first[index][0])
            if index < len(second):
                mixed.append(second[index][0])
        return mixed

    # Order categories by their strongest member, so the best org overall
    # still leads the whole list.
    order = sorted(
        buckets,
        key=lambda c: -max(e[0]["legitimacy_score"] for e in buckets[c]),
    )

    # Alternate which side leads, category by category. Without this the
    # category round-robin shows every category's established org before any
    # grassroots one, pushing small orgs past the end of a short list.
    mixed_buckets = {
        category: mix_by_size(buckets[category], grassroots_first=(position % 2 == 1))
        for position, category in enumerate(order)
    }

    interleaved: list[dict[str, Any]] = []
    while len(interleaved) < max_results:
        progressed = False
        for category in order:
            bucket = mixed_buckets[category]
            if not bucket:
                continue
            interleaved.append(bucket.pop(0))
            progressed = True
            if len(interleaved) >= max_results:
                break
        if not progressed:
            break  # every bucket drained
    return interleaved


def find_opportunities(
    lat: float,
    lng: float,
    radius_km: float = 5.0,
    *,
    queries: Sequence[str] | None = None,
    packs: Sequence[str] | None = None,
    max_queries: int = 24,
    max_results: int = 20,
    min_legitimacy: float = 0.4,
    diversify: bool = True,
    verify: bool = False,
    max_verify: int = 5,
    include_description: bool = False,
    places: PlacesProvider | None = None,
    llm: LLMProvider | None = None,
) -> list[dict[str, Any]]:
    """Find nearby volunteer opportunities and shape them into quests.

    Args:
        lat, lng: Center of the search.
        radius_km: Search radius; clamped to Google's 50km ceiling upstream.
        queries: Explicit search terms, overriding everything else.
        packs: Names from ``QUERY_PACKS`` to search instead of the default
            fan-out, e.g. ``["food", "animals"]``. Pass ``["all"]`` for every
            philanthropic domain -- broadest coverage, highest cost.
        max_queries: Hard cap on how many Places requests one call may make.
            Each query is separately billed, so this is the cost guard; raise
            it deliberately rather than by accident.
        max_results: Cap on returned opportunities.
        min_legitimacy: Drop anything scoring below this. Keeps permanently
            closed and obviously-not-a-nonprofit results off the map.
        diversify: Interleave results across categories so the map shows a
            mix rather than 20 food banks. On by default. Set False for a
            strict legitimacy ranking.
        verify: Run a real web-search trust check on the top results. Off by
            default because it costs one LLM call per org; turn it on for a
            curated map refresh rather than every pan of the viewport.
        max_verify: How many of the top results to verify when ``verify`` is on.
        include_description: Add a ``description`` key carrying the one-line
            web-search summary of the org. Requires ``verify=True`` to be
            populated (that search is where the text comes from); otherwise it
            is an empty string. Off by default so the returned dict matches
            the seven-field Opportunity contract exactly.
        places, llm: Injected providers. Defaults come from the environment,
            falling back to mocks when keys are absent.

    Returns:
        A list of Opportunity dicts, highest legitimacy first.
    """
    places = places or get_places_provider()

    if queries:
        search_terms = tuple(queries)
    elif packs:
        search_terms = all_queries() if "all" in packs else queries_for_packs(packs)
    else:
        search_terms = DEFAULT_QUERIES

    if len(search_terms) > max_queries:
        log.info(
            "Trimming %d queries to max_queries=%d (each one is a billed Places request)",
            len(search_terms),
            max_queries,
        )
        search_terms = search_terms[:max_queries]

    try:
        # Pull a generous candidate pool: diversification and the legitimacy
        # filter both need more to work with than the final count.
        raw_places = places.search_nearby(
            lat, lng, radius_km, search_terms, max(max_results * 4, 80)
        )
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
                # still counts for something. Keep the summary -- it is the
                # short description the web search was run for.
                place = {**place, "web_summary": result["summary"]}
                scored[index] = (round(0.75 * verified + 0.25 * heuristic, 2), place)
        scored.sort(key=lambda item: -item[0])

    opportunities: list[tuple[dict[str, Any], bool]] = []
    for legitimacy, place in scored:
        if legitimacy < min_legitimacy:
            continue

        category = normalize_category(place["category"])
        record = Opportunity(
            org_name=place["name"],
            address=place.get("address") or "",
            lat=float(place["lat"]),
            lng=float(place["lng"]),
            category=category,
            legitimacy_score=legitimacy,
            quest_type=quest_type_for(category),
        ).to_dict()
        if include_description:
            # Extra key, never a renamed one -- consumers expecting the bare
            # seven-field contract are unaffected.
            record["description"] = place.get("web_summary", "")
        opportunities.append((record, is_grassroots(place)))

    # Rank last, over everything that qualified, so diversification has the
    # full candidate pool to draw from rather than a pre-truncated list.
    if diversify:
        return _interleave_by_category(opportunities, max_results)
    return [record for record, _grassroots in opportunities[:max_results]]
