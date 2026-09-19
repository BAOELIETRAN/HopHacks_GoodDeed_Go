"""Presence-verified volunteering sessions.

The problem this solves: `time_spent_minutes` used to be typed in by the
person claiming the points, and nothing could check it. Here the server
starts the clock only when the user is demonstrably at the organization, and
accumulates time from location heartbeats, so the number attached to a
submission is measured rather than asserted.

Design notes worth keeping:

* **Time accrues between heartbeats, not from (end - start).** If someone
  walks off and comes back an hour later, the gap is not credited.
* **Two radii.** You must be within CHECKIN_RADIUS_M to start, but you are
  only dropped past the wider LEAVE_RADIUS_M. Without that hysteresis, GPS
  jitter alone would end a session while somebody stands still.
* **Everything is evaluated server-side.** A client that lies about its
  coordinates is a different problem (and one this design cannot fully
  solve), but a client that simply claims "I was there four hours" no longer
  works.
* **Sweeping is lazy.** Stale sessions are closed when anyone touches the
  endpoints, rather than by a scheduler -- one fewer moving part, and an
  abandoned session only matters when someone looks.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DbSession

from .. import db_models as m
from ..agent_client import estimate_points
from ..config import (
    CHECKIN_RADIUS_M,
    HEARTBEAT_GRACE_SECONDS,
    LEAVE_RADIUS_M,
    MAX_SESSION_MINUTES,
    MIN_SESSION_MINUTES,
)
from ..database import get_db
from ..deps import get_current_user
from ..geo import haversine_km
from ..schemas import CheckInOut, CheckInStart, HeartbeatIn

router = APIRouter(prefix="/checkins", tags=["checkins"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _metres(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    return haversine_km(lat1, lng1, lat2, lng2) * 1000.0


def _to_out(row: m.CheckIn) -> CheckInOut:
    started = _aware(row.started_at)
    return CheckInOut(
        checkin_id=row.id,
        org_name=row.org_name,
        org_lat=row.org_lat,
        org_lng=row.org_lng,
        category=row.category,
        quest_type=row.quest_type,  # type: ignore[arg-type]
        status=row.status,  # type: ignore[arg-type]
        started_at=started.isoformat() if started else "",
        elapsed_seconds=row.elapsed_seconds,
        elapsed_minutes=row.elapsed_seconds // 60,
        end_reason=row.end_reason,
        estimated_points=estimate_points(row.category, row.quest_type),
        checkin_radius_m=CHECKIN_RADIUS_M,
        leave_radius_m=LEAVE_RADIUS_M,
        already_submitted=row.submission_id is not None,
    )


def _close(row: m.CheckIn, reason: str) -> None:
    row.status = "done" if reason == "completed" else "abandoned"
    row.end_reason = reason
    row.ended_at = _now()


def sweep_stale(db: DbSession, user_id: str) -> None:
    """Close sessions whose heartbeats stopped, or that ran absurdly long.

    A phone that dies mid-shift would otherwise leave a session open
    forever, blocking the next check-in.
    """
    cutoff = _now() - timedelta(seconds=HEARTBEAT_GRACE_SECONDS)
    for row in db.query(m.CheckIn).filter(
        m.CheckIn.user_id == user_id, m.CheckIn.status == "active"
    ):
        last_seen = _aware(row.last_seen_at)
        started = _aware(row.started_at)
        if last_seen and last_seen < cutoff:
            _close(row, "timed_out")
        elif started and (_now() - started).total_seconds() > MAX_SESSION_MINUTES * 60:
            _close(row, "too_long")
    db.commit()


@router.get("/active", response_model=CheckInOut | None)
def active_checkin(
    db: DbSession = Depends(get_db), user: m.User = Depends(get_current_user)
) -> CheckInOut | None:
    """The session in progress, if any. The app calls this on load so a
    refresh or a backgrounded phone doesn't lose the running clock."""
    sweep_stale(db, user.id)
    row = (
        db.query(m.CheckIn)
        .filter(m.CheckIn.user_id == user.id, m.CheckIn.status == "active")
        .order_by(m.CheckIn.started_at.desc())
        .first()
    )
    return _to_out(row) if row else None


@router.post("", response_model=CheckInOut, status_code=201)
def start_checkin(
    body: CheckInStart,
    db: DbSession = Depends(get_db),
    user: m.User = Depends(get_current_user),
) -> CheckInOut:
    sweep_stale(db, user.id)

    existing = (
        db.query(m.CheckIn)
        .filter(m.CheckIn.user_id == user.id, m.CheckIn.status == "active")
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"You're already checked in at {existing.org_name}. Finish that first.",
        )

    distance = _metres(body.lat, body.lng, body.org_lat, body.org_lng)
    if distance > CHECKIN_RADIUS_M:
        raise HTTPException(
            status_code=403,
            detail=(
                f"You need to be at {body.org_name} to start this quest. "
                f"You're about {round(distance)}m away — get within {CHECKIN_RADIUS_M}m and try again."
            ),
        )

    row = m.CheckIn(
        user_id=user.id,
        org_name=body.org_name,
        org_lat=body.org_lat,
        org_lng=body.org_lng,
        category=body.category,
        quest_type=body.quest_type or "daily",
        status="active",
        last_lat=body.lat,
        last_lng=body.lng,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_out(row)


@router.post("/{checkin_id}/heartbeat", response_model=CheckInOut)
def heartbeat(
    checkin_id: str,
    body: HeartbeatIn,
    db: DbSession = Depends(get_db),
    user: m.User = Depends(get_current_user),
) -> CheckInOut:
    """Accrue time if the user is still in range; auto-stop if they left."""
    row = db.get(m.CheckIn, checkin_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="No such check-in")
    if row.status != "active":
        return _to_out(row)

    now = _now()
    last_seen = _aware(row.last_seen_at) or now
    distance = _metres(body.lat, body.lng, row.org_lat, row.org_lng)

    if distance > LEAVE_RADIUS_M:
        # Credit nothing for this interval: we do not know when in it they
        # left, and rounding in the user's favour is what invites abuse.
        _close(row, "left_area")
        db.commit()
        db.refresh(row)
        return _to_out(row)

    # Only count a plausible interval. A phone waking from sleep can report
    # a huge gap, which would otherwise be credited in one jump.
    gap = (now - last_seen).total_seconds()
    if 0 < gap <= HEARTBEAT_GRACE_SECONDS:
        row.elapsed_seconds += int(gap)

    row.last_seen_at = now
    row.last_lat = body.lat
    row.last_lng = body.lng

    if row.elapsed_seconds > MAX_SESSION_MINUTES * 60:
        _close(row, "too_long")

    db.commit()
    db.refresh(row)
    return _to_out(row)


@router.post("/{checkin_id}/stop", response_model=CheckInOut)
def stop_checkin(
    checkin_id: str,
    db: DbSession = Depends(get_db),
    user: m.User = Depends(get_current_user),
) -> CheckInOut:
    row = db.get(m.CheckIn, checkin_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="No such check-in")
    if row.status == "active":
        _close(row, "completed")
        db.commit()
        db.refresh(row)
    return _to_out(row)


def consume_for_submission(db: DbSession, user: m.User, checkin_id: str) -> m.CheckIn:
    """Validate a finished session and hand back its measured time.

    Raises rather than silently falling back to client-supplied minutes: a
    submission that claims verified presence must actually have it.
    """
    row = db.get(m.CheckIn, checkin_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="No such check-in")
    if row.submission_id is not None:
        raise HTTPException(status_code=409, detail="That session has already been submitted")
    if row.status == "active":
        _close(row, "completed")
        db.commit()
    if row.elapsed_seconds < MIN_SESSION_MINUTES * 60:
        raise HTTPException(
            status_code=400,
            detail=(
                f"That session only lasted {row.elapsed_seconds // 60} minutes. "
                f"Stay at least {MIN_SESSION_MINUTES} to log a quest."
            ),
        )
    return row
