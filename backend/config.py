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

DB_PATH = os.environ.get("GOODDEED_DB_PATH") or os.path.join(os.path.dirname(__file__), "gooddeed.db")

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

# How long a cached /quests result stays fresh. Nonprofits do not move and
# rarely close, so a five-minute TTL meant almost every map load paid the
# full four-second Places fan-out for data that had not changed. Expired
# entries are still served immediately and refreshed in the background
# (see routers/quests.py), so this is an upper bound on staleness, not on
# response time.
QUEST_CACHE_TTL_SECONDS = 6 * 60 * 60

# Grid size used to bucket lat/lng into a cache key, in degrees. At 0.01
# (~1.1km) walking two blocks produced a fresh cache key and another cold
# load. 0.02 (~2.2km) against an 8km search radius keeps results well
# centred while letting a neighbourhood share one entry.
QUEST_CACHE_GRID = 0.02

# How long a claim on a community report holds before it is released back
# to the feed. Someone who claims a need and never follows through would
# otherwise lock it forever, and nobody else can help. Proof submitted at
# any point stops the clock -- only untouched claims expire.
CLAIM_EXPIRY_HOURS = 3

# Awarded to whoever posted a community report, once it is confirmed done.
# Spotting a problem and writing it up is a contribution; it is just worth
# less than going out and fixing it.
REPORTER_POINTS = 5

# --- Presence-verified check-ins ----------------------------------------
# You must actually be at an organization to start a quest there, and the
# clock is kept by the server from location heartbeats rather than typed in
# afterwards. Self-reported minutes were the one input nothing could check.

# How close you must be to start. Consumer GPS is good to ~10-20m outdoors
# and much worse beside tall buildings, so this is generous on purpose --
# too tight and real volunteers get locked out of their own shift.
CHECKIN_RADIUS_M = 200

# How far you can drift before the session auto-stops. Deliberately wider
# than CHECKIN_RADIUS_M: without that gap, GPS jitter alone would end a
# session while someone stands still in a doorway.
LEAVE_RADIUS_M = 350

# Heartbeats arrive every ~30s. Miss this many seconds and we assume the app
# was closed or the phone lost signal, and close the session at the last
# position we trusted rather than billing time nobody was there for.
HEARTBEAT_GRACE_SECONDS = 5 * 60

# Sessions longer than this are almost certainly a forgotten timer.
MAX_SESSION_MINUTES = 8 * 60

# Below this, a session is treated as a mis-tap rather than a shift.
MIN_SESSION_MINUTES = 2

# Leaderboard points multiplier for a submission backed by a verified
# session. Applied to `points` only, never `tier_points` -- the same rule
# that keeps quest multipliers out of the tier ladder.
VERIFIED_PRESENCE_MULTIPLIER = 1.5

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

# Shared secret for POST /admin/refresh-opportunities, so a Render Cron Job
# (or a laptop during a demo) can trigger the daily opportunity refresh.
# Unset means the endpoint is disabled entirely rather than open: an
# unauthenticated endpoint that burns Places quota is a free DoS on the
# project's billing.
REFRESH_TOKEN = os.environ.get("REFRESH_TOKEN", "").strip()
