"""Backend-only constants. Tune here, not scattered through routers."""

from __future__ import annotations

import os
from pathlib import Path

# Load .env before reading anything out of the environment. Without this the
# settings below silently take their defaults locally -- DATABASE_URL would
# be invisible and the app would fall back to SQLite while appearing to work.
# Real environment variables (how Render supplies these) always win.
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
except ImportError:  # python-dotenv is optional; real env vars still work
    pass

DB_PATH = os.path.join(os.path.dirname(__file__), "gooddeed.db")

# Database. Set DATABASE_URL (Supabase, or any Postgres) in production;
# without it we fall back to a local SQLite file so nobody needs a hosted
# database just to run the app locally.
#
# Supabase hands you a URI starting "postgresql://". Use the **Session
# pooler** connection string (port 5432 on the pooler host), not the direct
# one -- Render's free tier is IPv4-only and Supabase's direct host is
# IPv6-only, which fails to connect with a confusing timeout.
DATABASE_URL = os.environ.get("DATABASE_URL") or ""

# Public origin of the deployed frontend, used for CORS. Comma-separated for
# more than one. Empty means "allow any origin", which is the local-dev case.
ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()
]

# Google OAuth client ID (the public one -- there is no secret in the
# ID-token flow). Leave unset to disable Google sign-in entirely.
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()

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
