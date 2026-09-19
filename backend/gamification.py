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
_BADGE_DEFS: list[tuple[str, str, "callable"]] = [
    ("first_shift", "First Shift", lambda user, verified_count: verified_count >= 1),
    ("ten_day_streak", "10-Day Streak", lambda user, verified_count: user.longest_streak >= 10),
    ("trusted_10", "Trusted 10", lambda user, verified_count: verified_count >= 10),
]


def compute_badges(user: m.User, verified_count: int) -> list[dict[str, str]]:
    return [
        {"code": code, "label": label}
        for code, label, earned in _BADGE_DEFS
        if earned(user, verified_count)
    ]
