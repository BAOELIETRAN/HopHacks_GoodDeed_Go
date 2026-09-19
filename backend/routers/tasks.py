"""Everyday good deeds: tap to complete, no evidence, no waiting.

The counterpart to /submissions. That endpoint judges evidence and takes
several seconds on a vision call; this one records an honour-system act in a
single round trip, because a kindness that needs an upload and a five-second
check is no longer a quick kindness.

Abuse is handled by economics rather than verification: small points, one
completion per task per day, and a daily ceiling that keeps a full sweep
worth less than a single real shift.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DbSession

from .. import db_models as m
from ..agent_client import tier_for_points
from ..database import get_db
from ..deps import get_current_user
from ..deletions import deduct
from ..gamification import record_activity
from ..wallet import earn_coins
from ..micro_deeds import BY_ID, DAILY_POINT_CAP, deeds_for_day
from ..schemas import MicroDeedDoneOut, MicroDeedOut, MicroDeedTodayOut, TaskCompleteIn

router = APIRouter(prefix="/tasks", tags=["everyday deeds"])


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _points_today(db: DbSession, user_id: str) -> int:
    rows = (
        db.query(m.MicroDeedDone)
        .filter(m.MicroDeedDone.user_id == user_id, m.MicroDeedDone.day == _today())
        .all()
    )
    return sum(r.points for r in rows)


@router.get("/today", response_model=MicroDeedTodayOut)
def todays_tasks(
    db: DbSession = Depends(get_db), user: m.User = Depends(get_current_user)
) -> MicroDeedTodayOut:
    day = _today()
    done_ids = {
        r.deed_id
        for r in db.query(m.MicroDeedDone).filter(
            m.MicroDeedDone.user_id == user.id, m.MicroDeedDone.day == day
        )
    }
    earned = _points_today(db, user.id)

    return MicroDeedTodayOut(
        day=day,
        points_today=earned,
        daily_cap=DAILY_POINT_CAP,
        deeds=[
            MicroDeedOut(
                id=d.id, text=d.text, icon=d.icon, points=d.points,
                theme=d.theme, done=d.id in done_ids,
            )
            for d in deeds_for_day(date.fromisoformat(day))
        ],
    )


@router.post("/{deed_id}/complete", response_model=MicroDeedDoneOut)
def complete_task(
    deed_id: str,
    body: TaskCompleteIn | None = None,
    db: DbSession = Depends(get_db),
    user: m.User = Depends(get_current_user),
) -> MicroDeedDoneOut:
    spec = BY_ID.get(deed_id)
    if spec is None:
        raise HTTPException(status_code=404, detail="No such everyday deed")

    day = _today()
    already = (
        db.query(m.MicroDeedDone)
        .filter(
            m.MicroDeedDone.user_id == user.id,
            m.MicroDeedDone.deed_id == deed_id,
            m.MicroDeedDone.day == day,
        )
        .first()
    )
    if already:
        raise HTTPException(status_code=409, detail="You've already done that one today")

    # Award up to the remaining daily allowance. Going over is not an error
    # -- the deed still counts and is still recorded, it just stops paying.
    remaining = max(0, DAILY_POINT_CAP - _points_today(db, user.id))
    awarded = min(spec.points, remaining)

    db.add(
        m.MicroDeedDone(
            user_id=user.id, deed_id=deed_id, day=day, points=awarded,
            note=(body.note if body else None),
        )
    )
    user.tier_points += awarded
    user.tier = tier_for_points(user.tier_points)
    earn_coins(db, user, awarded, note="Everyday deed")

    # Everyday deeds keep a streak alive. Requiring a verified shift every
    # single day to hold a streak would punish people for having a job.
    is_best = record_activity(user) if awarded > 0 else False

    db.commit()

    return MicroDeedDoneOut(
        deed_id=deed_id,
        points=awarded,
        capped=awarded < spec.points,
        points_today=_points_today(db, user.id),
        daily_cap=DAILY_POINT_CAP,
        user_tier=user.tier,
        user_tier_points=user.tier_points,
        current_streak=user.current_streak,
        is_personal_best=is_best,
    )


@router.get("/history", response_model=list[MicroDeedOut])
def recent(
    db: DbSession = Depends(get_db), user: m.User = Depends(get_current_user)
) -> list[MicroDeedOut]:
    """The last week of everyday deeds, for the profile screen."""
    since = (datetime.now(timezone.utc).date() - timedelta(days=7)).isoformat()
    rows = (
        db.query(m.MicroDeedDone)
        .filter(m.MicroDeedDone.user_id == user.id, m.MicroDeedDone.day >= since)
        .order_by(m.MicroDeedDone.created_at.desc())
        .all()
    )
    out = []
    for r in rows:
        spec = BY_ID.get(r.deed_id)
        if spec is None:
            continue  # a deed retired from the list
        out.append(
            MicroDeedOut(id=spec.id, text=spec.text, icon=spec.icon,
                         points=r.points, theme=spec.theme, done=True)
        )
    return out


@router.delete("/{deed_id}/complete", status_code=204)
def undo_task(
    deed_id: str,
    db: DbSession = Depends(get_db),
    user: m.User = Depends(get_current_user),
) -> None:
    """Untick an everyday deed, taking its points back with it."""
    row = (
        db.query(m.MicroDeedDone)
        .filter(
            m.MicroDeedDone.user_id == user.id,
            m.MicroDeedDone.deed_id == deed_id,
            m.MicroDeedDone.day == _today(),
        )
        .first()
    )
    if row is None:
        return
    deduct(db, user, row.points or 0, "this deed")
    db.delete(row)
    db.commit()
