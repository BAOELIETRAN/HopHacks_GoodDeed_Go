"""Team impact: the points, translated into something real.

Read-only maths over data that already exists, plus one setter so a team
can pick what they are working toward.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session as DbSession

from .. import db_models as m
from ..causes import CAUSES, get_cause, units_from_points
from ..database import get_db
from ..deps import get_current_user
from ..schemas import CauseOut, SetCauseIn, TeamImpactOut

router = APIRouter(prefix="/team", tags=["team impact"])


def _members(db: DbSession, user: m.User) -> list[str]:
    if not user.friend_group_id:
        return [user.id]
    rows = db.query(m.User.id).filter(m.User.friend_group_id == user.friend_group_id).all()
    return [r[0] for r in rows] or [user.id]


def _total_points(db: DbSession, ids: list[str]) -> int:
    """Lifetime points across both kinds of deed.

    Uses tier_points from the user row for scored submissions -- that total
    is already maintained on every submission and every everyday deed, so
    re-summing the tables would be slower and could disagree with it.
    """
    total = db.query(func.coalesce(func.sum(m.User.tier_points), 0)).filter(
        m.User.id.in_(ids)
    ).scalar()
    return int(total or 0)


def _cause_out(cause, selected_key: str) -> CauseOut:
    return CauseOut(**{**vars(cause), "selected": cause.key == selected_key})


@router.get("/impact", response_model=TeamImpactOut)
def team_impact(
    db: DbSession = Depends(get_db), user: m.User = Depends(get_current_user)
) -> TeamImpactOut:
    ids = _members(db, user)
    group = db.get(m.FriendGroup, user.friend_group_id) if user.friend_group_id else None
    selected = (group.cause_key if group else None) or "meals"
    cause = get_cause(selected)

    team_points = _total_points(db, ids)
    units = units_from_points(team_points, cause)
    remainder = team_points % cause.points_per_unit

    return TeamImpactOut(
        has_team=bool(user.friend_group_id) and len(ids) > 1,
        member_count=len(ids),
        team_points=team_points,
        your_points=user.tier_points or 0,
        cause=_cause_out(cause, cause.key),
        units=units,
        unit_label=cause.unit if units == 1 else cause.unit_plural,
        points_to_next_unit=cause.points_per_unit - remainder,
        causes=[_cause_out(c, cause.key) for c in CAUSES],
    )


@router.post("/cause", response_model=TeamImpactOut)
def set_cause(
    body: SetCauseIn,
    db: DbSession = Depends(get_db),
    user: m.User = Depends(get_current_user),
) -> TeamImpactOut:
    if body.cause_key not in {c.key for c in CAUSES}:
        raise HTTPException(status_code=400, detail="Unknown cause")
    if not user.friend_group_id:
        raise HTTPException(
            status_code=400,
            detail="Start or join a team first — a cause is something you work toward together.",
        )
    group = db.get(m.FriendGroup, user.friend_group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Team not found")
    group.cause_key = body.cause_key
    db.commit()
    return team_impact(db, user)
