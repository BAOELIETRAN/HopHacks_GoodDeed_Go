"""The weekly recap.

A once-a-week look back is the cheapest retention mechanic there is: it
costs nothing to compute and gives someone a reason to reopen the app on a
day they had not planned to.

The copy is written here rather than in the client because it depends on
data the client would otherwise need three more requests to assemble, and
because a zero-deed week needs careful wording. That case is the one most
likely to be handled badly -- an empty recap that says "0 deeds, 0 points"
is a scolding, and scolding someone for a quiet week is how you lose them.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DbSession

from .. import db_models as m
from ..agent_client import points_to_next_tier, tier_for_points
from ..database import get_db
from ..deps import get_current_user
from ..schemas import WeeklyRecapOut

router = APIRouter(tags=["recap"])

WEEK_DAYS = 7


def _friend_ids(db: DbSession, user: m.User) -> list[str]:
    if not user.friend_group_id:
        return [user.id]
    rows = db.query(m.User.id).filter(m.User.friend_group_id == user.friend_group_id).all()
    return [r[0] for r in rows] or [user.id]


@router.get("/recap/weekly", response_model=WeeklyRecapOut)
def weekly_recap(
    db: DbSession = Depends(get_db), user: m.User = Depends(get_current_user)
) -> WeeklyRecapOut:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=WEEK_DAYS)

    subs = (
        db.query(m.Submission)
        .filter(
            m.Submission.user_id == user.id,
            m.Submission.points > 0,
            m.Submission.scored_at >= start,
        )
        .all()
    )
    micro = (
        db.query(m.MicroDeedDone)
        .filter(
            m.MicroDeedDone.user_id == user.id,
            m.MicroDeedDone.day >= start.date().isoformat(),
        )
        .all()
    )

    deed_points = sum(s.points for s in subs)
    micro_points = sum(d.points for d in micro)
    total = deed_points + micro_points
    deed_count = len(subs)

    # Busiest day, counting both kinds of deed.
    by_day: Counter[str] = Counter()
    for s in subs:
        when = s.scored_at if s.scored_at.tzinfo else s.scored_at.replace(tzinfo=timezone.utc)
        by_day[when.date().isoformat()] += s.points
    for d in micro:
        by_day[d.day] += d.points
    best_day = by_day.most_common(1)[0][0] if by_day else None

    types = Counter((s.deed_type or "volunteer") for s in subs)
    top_type = types.most_common(1)[0][0] if types else None

    # Rank among friends on this week's points.
    ids = _friend_ids(db, user)
    weekly: dict[str, int] = {}
    for uid, pts in (
        db.query(m.Submission.user_id, m.Submission.points)
        .filter(
            m.Submission.user_id.in_(ids),
            m.Submission.points > 0,
            m.Submission.scored_at >= start,
        )
        .all()
    ):
        weekly[uid] = weekly.get(uid, 0) + pts
    ordered = sorted(ids, key=lambda u: -weekly.get(u, 0))
    friend_rank = ordered.index(user.id) + 1 if len(ids) > 1 else None

    tier = tier_for_points(user.tier_points)
    tier_changed = tier_for_points(max(0, user.tier_points - total)) != tier

    headline, subline = _copy(
        total=total, deed_count=deed_count, micro_count=len(micro),
        tier=tier, tier_changed=tier_changed, streak=user.current_streak,
        friend_rank=friend_rank, friend_count=len(ids),
    )

    return WeeklyRecapOut(
        week_start=start.date().isoformat(),
        week_end=now.date().isoformat(),
        deed_count=deed_count,
        points=total,
        micro_deed_count=len(micro),
        best_day=best_day,
        top_deed_type=top_type,
        tier=tier,
        tier_points=user.tier_points,
        points_to_next_tier=points_to_next_tier(user.tier_points),
        tier_changed=tier_changed,
        current_streak=user.current_streak,
        friend_rank=friend_rank,
        friend_count=len(ids),
        headline=headline,
        subline=subline,
    )


def _copy(*, total, deed_count, micro_count, tier, tier_changed, streak,
          friend_rank, friend_count) -> tuple[str, str]:
    """One honest line about the week.

    The zero case gets the most care. It never opens with a zero, never
    implies failure, and gives one concrete thing to do -- a recap that
    makes someone feel bad about a hard week is worse than no recap.
    """
    if total == 0 and deed_count == 0 and micro_count == 0:
        return (
            "A quiet week",
            "Nothing logged — that's allowed. One small thing today starts it again.",
        )

    if tier_changed:
        return (f"You reached {tier}", f"{total} points across {deed_count + micro_count} good deeds this week.")

    if deed_count == 0:
        return (
            f"{micro_count} small {'thing' if micro_count == 1 else 'things'}",
            f"{total} points from everyday good. They add up.",
        )

    if friend_rank == 1 and friend_count > 1:
        return ("Top of your team", f"{total} points from {deed_count + micro_count} deeds — nobody did more.")

    if streak >= 7:
        return (f"{streak} days in a row", f"{total} points this week, and the streak's still going.")

    return (
        f"{deed_count + micro_count} good {'deed' if deed_count + micro_count == 1 else 'deeds'}",
        f"{total} points this week"
        + (f", {friend_rank} of {friend_count} in your team." if friend_rank else "."),
    )
