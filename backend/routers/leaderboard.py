from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session as DbSession

from .. import db_models as m
from ..agent_client import leaderboard as rank_entries
from ..config import LEADERBOARD_NEARBY_RADIUS_KM
from ..database import get_db
from ..deps import get_current_user
from ..geo import haversine_km
from ..schemas import LeaderboardEntry

router = APIRouter(tags=["leaderboard"])


def _period_cutoff(period: Literal["daily", "weekly"]) -> datetime:
    now = datetime.now(timezone.utc)
    return now - timedelta(days=1 if period == "daily" else 7)


def _candidate_ids(db: DbSession, user: m.User, scope: Literal["friends", "nearby"]) -> list[str]:
    if scope == "friends":
        if user.friend_group_id is None:
            return [user.id]
        rows = db.query(m.User.id).filter(m.User.friend_group_id == user.friend_group_id).all()
        return [r[0] for r in rows]

    # nearby: everyone with a known location, within radius of the requester's
    # last known location (set on their most recent submission).
    if user.lat is None or user.lng is None:
        return [user.id]
    rows = db.query(m.User.id, m.User.lat, m.User.lng).filter(m.User.lat.isnot(None)).all()
    return [
        uid
        for uid, lat, lng in rows
        if haversine_km(user.lat, user.lng, lat, lng) <= LEADERBOARD_NEARBY_RADIUS_KM
    ]


@router.get("/leaderboard", response_model=list[LeaderboardEntry])
def get_leaderboard(
    scope: Literal["friends", "nearby"] = Query(...),
    period: Literal["daily", "weekly"] = Query(...),
    db: DbSession = Depends(get_db),
    user: m.User = Depends(get_current_user),
) -> list[LeaderboardEntry]:
    candidate_ids = _candidate_ids(db, user, scope)
    cutoff = _period_cutoff(period)

    # "Only verified completions count" (leaderboard screen copy) -- exclude
    # zero-point submissions from both the point sum and the deed count.
    rows = (
        db.query(
            m.Submission.user_id,
            func.sum(m.Submission.points),
            func.count(m.Submission.id),
        )
        .filter(
            m.Submission.user_id.in_(candidate_ids),
            m.Submission.scored_at >= cutoff,
            m.Submission.points > 0,
        )
        .group_by(m.Submission.user_id)
        .all()
    )
    sums = {uid: int(total) for uid, total, _count in rows}
    counts = {uid: int(count) for uid, _total, count in rows}

    entries = [(uid, sums.get(uid, 0)) for uid in candidate_ids]
    ranked = rank_entries(entries)

    names = dict(db.query(m.User.id, m.User.name).filter(m.User.id.in_(candidate_ids)).all())
    return [
        LeaderboardEntry(
            rank=r["rank"],
            user_id=r["user_id"],
            name=names.get(r["user_id"], "?"),
            points=r["points"],
            deed_count=counts.get(r["user_id"], 0),
            is_you=r["user_id"] == user.id,
        )
        for r in ranked
    ]
