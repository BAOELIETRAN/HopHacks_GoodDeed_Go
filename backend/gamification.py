"""Streaks and badges.

Both are derived purely from the user's own record (no agent calls), so they
live apart from agent_client.py. Badges are computed live from existing data
rather than stored, to avoid a whole new "achievements" subsystem for what
the UI shows as a handful of milestones.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import db_models as m


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def record_activity(user: m.User) -> bool:
    """Advance the user's streak for today's activity, at most once per day.

    Returns True if this pushes ``longest_streak`` to a new personal best.
    """
    today = _today_iso()
    if user.last_active_date == today:
        return False  # already counted today

    yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
    user.current_streak = user.current_streak + 1 if user.last_active_date == yesterday else 1
    user.last_active_date = today

    is_best = user.current_streak > user.longest_streak
    user.longest_streak = max(user.longest_streak, user.current_streak)
    return is_best


# code -> (label, predicate(user, verified_submission_count))
#
# Two kinds here: activity badges earned by doing a thing, and point
# milestones that unlock a profile frame. Milestones are spaced so the next
# one is always in sight -- the gap from 25 to 1000 is deliberately uneven,
# tightest early where a new user needs the encouragement most.
_BADGE_DEFS: list[tuple[str, str, "callable"]] = [
    ("first_shift", "First Shift", lambda user, verified_count: verified_count >= 1),
    ("ten_day_streak", "10-Day Streak", lambda user, verified_count: user.longest_streak >= 10),
    ("trusted_10", "Trusted 10", lambda user, verified_count: verified_count >= 10),
    ("thirty_day_streak", "30-Day Streak", lambda user, verified_count: user.longest_streak >= 30),
    ("trusted_50", "Trusted 50", lambda user, verified_count: verified_count >= 50),
]

#: Profile frames unlocked by cumulative tier points. Purely cosmetic --
#: they change the ring around the avatar and nothing else.
FRAMES: list[dict] = [
    {"code": "none",    "label": "No frame",  "at": 0,    "ring": "rgba(255,255,255,.28)"},
    {"code": "sprout",  "label": "Sprout",    "at": 25,   "ring": "#7ed393"},
    {"code": "leaf",    "label": "Leaf",      "at": 100,  "ring": "#5ccb7d"},
    {"code": "bloom",   "label": "Bloom",     "at": 250,  "ring": "#e8bd5c"},
    {"code": "gold",    "label": "Gold Ring", "at": 500,  "ring": "#edc45e"},
    {"code": "radiant", "label": "Radiant",   "at": 1000, "ring": "#ffe9a8"},
]


def frames_for(tier_points: int) -> list[dict]:
    """Every frame, flagged with whether it is unlocked.

    Locked ones are returned too: seeing what is coming is most of why a
    cosmetic unlock works at all.
    """
    return [
        {**f, "unlocked": (tier_points or 0) >= f["at"]}
        for f in FRAMES
    ]


def current_frame(tier_points: int) -> dict:
    """The best frame unlocked so far."""
    best = FRAMES[0]
    for f in FRAMES:
        if (tier_points or 0) >= f["at"]:
            best = f
    return best


def compute_badges(user: m.User, verified_count: int) -> list[dict[str, str]]:
    return [
        {"code": code, "label": label}
        for code, label, earned in _BADGE_DEFS
        if earned(user, verified_count)
    ]
