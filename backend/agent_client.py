"""The seam between this backend and the AI agent teammate's code.

``gooddeed_agent`` is a plain importable Python package (see its README) that
already runs against deterministic mock data with zero API keys and switches
to live OpenAI/Places calls the moment ``OPENAI_API_KEY`` /
``GOOGLE_MAPS_API_KEY`` are set -- so there is no separate hand-rolled stub
here. Routers should import from this module, not from ``gooddeed_agent``
directly, so the seam stays in one place if that ever needs to change (e.g.
swapping to the HTTP wrapper in ``gooddeed_agent.service``).
"""

from __future__ import annotations

from typing import Any

from gooddeed_agent import (
    classify_report_from_dict,
    compute_points,
    find_opportunities,
    leaderboard,
    load_settings,
    normalize_category,
    points_to_next_tier,
    score_submission_from_dict,
    tier_for_points,
)

from .config import ESTIMATED_POINTS_NOMINAL_MINUTES, QUEST_MULTIPLIERS

__all__ = [
    "find_opportunities",
    "score_submission_from_dict",
    "classify_report_from_dict",
    "tier_for_points",
    "points_to_next_tier",
    "leaderboard",
    "multiplier_for_quest_type",
    "estimate_points",
    "agent_health",
]


def multiplier_for_quest_type(quest_type: str | None) -> float:
    return QUEST_MULTIPLIERS.get(quest_type or "daily", 1.0)


def estimate_points(category: str | None, quest_type: str | None = None) -> int:
    """Upfront point preview shown on a quest/report card, before anyone has
    done it (so there's no real duration or authenticity_confidence yet --
    those only exist once a submission is actually scored)."""
    points, _tier_points = compute_points(
        normalize_category(category),
        ESTIMATED_POINTS_NOMINAL_MINUTES,
        authenticity_confidence=1.0,
        quest_multiplier=multiplier_for_quest_type(quest_type),
    )
    return points


def agent_health() -> dict[str, Any]:
    settings = load_settings()
    return {
        "places_provider": "mock" if settings.use_mock_places else "google",
        "llm_provider": "mock" if settings.use_mock_llm else "openai",
    }
