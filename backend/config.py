"""Backend-only constants. Tune here, not scattered through routers."""

from __future__ import annotations

import os

DB_PATH = os.path.join(os.path.dirname(__file__), "gooddeed.db")

# How long a cached /quests result for a given (lat, lng, radius) bucket stays
# fresh before we call the agent again. "Caches briefly" per the spec.
QUEST_CACHE_TTL_SECONDS = 5 * 60

# Grid size used to bucket lat/lng into a cache key, in degrees. ~0.01 deg is
# roughly 1.1km, tight enough that nearby users still share a cache entry.
QUEST_CACHE_GRID = 0.01

# Radius (km) used for the "nearby" leaderboard scope, since that endpoint
# takes no lat/lng of its own -- it uses the requester's last known location.
LEADERBOARD_NEARBY_RADIUS_KM = 15.0

# points multiplier by quest_type, applied to leaderboard `points` only
# (never `tier_points` -- see gooddeed_agent.scoring.compute_points).
QUEST_MULTIPLIERS = {"daily": 1.0, "monthly": 1.5}

# legitimacy_score at or above this shows a "verified" badge in the UI.
VERIFIED_LEGITIMACY_THRESHOLD = 0.7

# Nominal minutes assumed when showing an upfront point estimate on a quest
# or report card, before anyone has actually done it (so there's no real
# authenticity_confidence or claimed duration yet). Actual awarded points are
# always computed for real at submission time -- this is a preview only.
ESTIMATED_POINTS_NOMINAL_MINUTES = 60
