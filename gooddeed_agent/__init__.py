"""GoodDeed Go -- AI agent layer.

Four public functions, all callable with zero configuration (they fall back to
deterministic stub data when API keys are absent):

    find_opportunities(lat, lng, radius_km) -> list[Opportunity dict]
    score_submission(photo, description, org_name, time_spent_minutes) -> Score dict
    trust_check(org_name, address) -> {legit, confidence, summary}
    classify_report(photo, description) -> {category, is_valid, ...}

Plus the pure scoring helpers the backend needs for tiers and leaderboards:
``compute_points``, ``tier_for_points``, ``points_to_next_tier``, ``leaderboard``.

Set OPENAI_API_KEY and GOOGLE_MAPS_API_KEY to use the real APIs, or
GOODDEED_USE_MOCKS=1 to force stub data. See README.md.
"""

from __future__ import annotations

from .config import Settings, load_settings
from .discovery import categorize, find_opportunities, heuristic_legitimacy, trust_check
from .models import (
    CommunityReport,
    Opportunity,
    ReportClassification,
    ScoreResult,
    Submission,
    TrustResult,
)
from .providers import (
    LLMProvider,
    MockLLMProvider,
    MockPlacesProvider,
    PlacesProvider,
    ProviderError,
    get_llm_provider,
    get_places_provider,
)
from .scoring import (
    CATEGORY_BASE_POINTS,
    MAX_POINTS_PER_SUBMISSION,
    MIN_AUTHENTICITY,
    compute_points,
    leaderboard,
    normalize_category,
    points_to_next_tier,
    quest_type_for,
    tier_for_points,
    time_bonus,
)
from .campaigns import PLATFORMS, verify_donation_link
from .vision import (
    REPORT_CATEGORIES,
    classify_report,
    classify_report_from_dict,
    score_submission,
    score_campaign_proof,
    score_submission_from_dict,
)

__version__ = "0.1.0"

__all__ = [
    # The four agent entry points
    "find_opportunities",
    "score_submission",
    "trust_check",
    "classify_report",
    "verify_donation_link",
    "score_campaign_proof",
    "PLATFORMS",
    # Data shapes
    "Opportunity",
    "ScoreResult",
    "TrustResult",
    "ReportClassification",
    "Submission",
    "CommunityReport",
    # Adapters for stored backend records
    "score_submission_from_dict",
    "classify_report_from_dict",
    # Pure scoring / tier helpers for the backend
    "compute_points",
    "tier_for_points",
    "points_to_next_tier",
    "leaderboard",
    "normalize_category",
    "quest_type_for",
    "time_bonus",
    "CATEGORY_BASE_POINTS",
    "MAX_POINTS_PER_SUBMISSION",
    "MIN_AUTHENTICITY",
    "REPORT_CATEGORIES",
    # Providers / config
    "LLMProvider",
    "PlacesProvider",
    "ProviderError",
    "MockLLMProvider",
    "MockPlacesProvider",
    "get_llm_provider",
    "get_places_provider",
    "Settings",
    "load_settings",
    # Discovery internals worth reusing
    "categorize",
    "heuristic_legitimacy",
]
