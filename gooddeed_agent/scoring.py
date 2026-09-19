"""Pure point math. No network, no LLM -- every function here is deterministic.

Keeping the arithmetic separate from the model call means the economy can be
tuned and unit-tested without spending tokens, and the backend can re-derive a
score from stored fields if it ever needs to.
"""

from __future__ import annotations

from typing import Iterable

from .models import Tier

# --- Categories -------------------------------------------------------------
# Base points per visit, roughly ordered by how much a shift actually costs the
# volunteer. Keys are the canonical category strings used in Opportunity.category.
CATEGORY_BASE_POINTS: dict[str, int] = {
    # Highest: emotionally demanding, training-gated, or acute-need work.
    "crisis_support": 35,
    "homeless_shelter": 35,
    "disaster_relief": 30,
    "food_bank": 30,
    "healthcare": 30,
    "senior_care": 30,
    "disability_services": 30,
    "refugee_services": 30,
    "veterans": 30,
    # Mid: sustained but lower-intensity commitments.
    "animal_shelter": 25,
    "education": 25,
    "environmental": 25,
    "youth_program": 20,
    "community_cleanup": 20,
    "community_center": 20,
    "arts_culture": 20,
    # Lowest: valuable, but usually a short drop-in.
    "thrift_donation": 15,
    "religious": 15,
    "other": 20,
}

DEFAULT_CATEGORY = "other"

# Categories whose meaningful contribution is a recurring commitment rather
# than a one-off drop-in get monthly quests.
MONTHLY_CATEGORIES = frozenset(
    {
        "homeless_shelter",
        "healthcare",
        "senior_care",
        "education",
        "youth_program",
        "crisis_support",
        "disability_services",
        "refugee_services",
        "veterans",
    }
)

# --- Economy knobs ----------------------------------------------------------
MINUTES_PER_TIME_POINT = 10

# Time actually spent gates the base points for deeds that are about being
# somewhere. Under ten minutes you did not really do the thing, so it scores
# nothing; past that the ramp is deliberately generous, because a short but
# real shift is still a real shift and arguing over minutes is not what this
# app is for.
TIME_GATE_MINUTES = 10
_TIME_RAMP: tuple[tuple[int, float], ...] = (
    (10, 0.0),    # under 10 minutes -> nothing
    (20, 0.55),
    (45, 0.80),
    (10**9, 1.0),  # 45 minutes or more -> full value
)


def time_factor(minutes: float | int | None) -> float:
    """How much of the base points a stay of this length earns, 0.0-1.0."""
    m = max(0, int(minutes or 0))
    if m < TIME_GATE_MINUTES:
        return 0.0
    for threshold, factor in _TIME_RAMP:
        if m < threshold:
            return factor
    return 1.0
MAX_TIME_BONUS = 30          # reached at 300 minutes
MAX_POINTS_PER_SUBMISSION = 100
# Below this authenticity confidence the submission earns nothing. Set low
# enough that a blurry-but-real photo still counts; high enough that a random
# selfie does not.
MIN_AUTHENTICITY = 0.45
# Anything past this is almost certainly a mistyped duration; it stops earning.
PLAUSIBLE_MAX_MINUTES = 480

TIER_THRESHOLDS: tuple[tuple[int, Tier], ...] = ((500, "Gold"), (100, "Silver"), (0, "Bronze"))


def normalize_category(category: str | None) -> str:
    """Map a free-form category string onto a known key.

    Unknown categories fall back to ``other`` rather than raising, because the
    Places API and the LLM both occasionally invent labels.
    """
    if not category:
        return DEFAULT_CATEGORY
    key = category.strip().lower().replace(" ", "_").replace("-", "_")
    return key if key in CATEGORY_BASE_POINTS else DEFAULT_CATEGORY


def base_points_for(category: str | None) -> int:
    return CATEGORY_BASE_POINTS[normalize_category(category)]


def time_bonus(time_spent_minutes: float | int | None) -> int:
    """One point per 10 minutes, capped, and ignoring implausible durations."""
    if not time_spent_minutes or time_spent_minutes <= 0:
        return 0
    minutes = min(float(time_spent_minutes), PLAUSIBLE_MAX_MINUTES)
    return int(min(minutes // MINUTES_PER_TIME_POINT, MAX_TIME_BONUS))


def quest_type_for(category: str | None) -> str:
    """Pick daily vs monthly for a category.

    Driven purely by category, so it is deterministic (the map never
    reshuffles between refreshes) and explainable: categories that only mean
    something as a recurring commitment get the monthly quest, drop-in
    categories get the daily one.
    """
    return "monthly" if normalize_category(category) in MONTHLY_CATEGORIES else "daily"


def compute_points(
    category: str | None,
    time_spent_minutes: float | int | None,
    authenticity_confidence: float,
    quest_multiplier: float = 1.0,
    deed_type: str | None = None,
) -> tuple[int, int]:
    """Turn a graded submission into ``(points, tier_points)``.

    The formula, in words: base points for the category, plus a time bonus,
    scaled by how confident we are the submission is genuine, capped. Anything
    under ``MIN_AUTHENTICITY`` scores zero -- we would rather miss a real deed
    than pay out for a fake one.

    ``quest_multiplier`` (e.g. 1.5 for a monthly quest, or a weekend bonus)
    affects leaderboard ``points`` only, never ``tier_points``.
    """
    confidence = max(0.0, min(1.0, float(authenticity_confidence)))
    if confidence < MIN_AUTHENTICITY:
        return 0, 0

    # A deed type sets its own floor and ceiling. A signed petition and a
    # morning at a shelter are both worth recognising, and obviously not
    # worth the same; the category scale alone cannot express that.
    if deed_type:
        from .deeds import get_deed

        spec = get_deed(deed_type)
        base = spec.base_points
        cap = spec.max_points
        # Only deeds that take time earn a time bonus -- a donation receipt
        # has no duration, and inviting one would just invite inflation.
        bonus = time_bonus(time_spent_minutes) if spec.time_required else 0
    else:
        base = base_points_for(category)
        cap = MAX_POINTS_PER_SUBMISSION
        bonus = time_bonus(time_spent_minutes)

    # For deeds that are about time on site, a very short stay earns
    # nothing however good the photo is.
    if deed_type:
        from .deeds import get_deed as _get

        if _get(deed_type).time_required:
            factor = time_factor(time_spent_minutes)
            if factor == 0.0:
                return 0, 0
            base = int(round(base * factor))

    scaled = (base + bonus) * confidence

    tier_points = int(round(min(scaled, cap)))
    points = int(round(min(scaled * max(0.0, quest_multiplier), cap)))
    return points, tier_points


def tier_for_points(total_tier_points: int | float) -> Tier:
    """Bronze 0-99, Silver 100-499, Gold 500+ (cumulative, per user)."""
    total = max(0, int(total_tier_points))
    for threshold, tier in TIER_THRESHOLDS:
        if total >= threshold:
            return tier
    return "Bronze"


def points_to_next_tier(total_tier_points: int | float) -> int | None:
    """Points still needed to reach the next tier, or None at Gold."""
    total = max(0, int(total_tier_points))
    for threshold, _tier in reversed(TIER_THRESHOLDS):
        if total < threshold:
            return threshold - total
    return None


def leaderboard(entries: Iterable[tuple[str, int]]) -> list[dict[str, object]]:
    """Rank ``(user_id, points)`` pairs. A convenience for the backend.

    Ties share a rank (1, 2, 2, 4) so two users on the same score are not
    ordered arbitrarily.
    """
    ordered = sorted(entries, key=lambda e: (-e[1], e[0]))
    ranked: list[dict[str, object]] = []
    last_points: int | None = None
    last_rank = 0
    for index, (user_id, points) in enumerate(ordered, start=1):
        rank = last_rank if points == last_points else index
        ranked.append({"rank": rank, "user_id": user_id, "points": points})
        last_points, last_rank = points, rank
    return ranked
