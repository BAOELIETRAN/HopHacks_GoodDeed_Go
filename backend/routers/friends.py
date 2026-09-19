"""Invite-code friend groups.

Simplification for a hackathon: each user belongs to at most one group at a
time. Inviting reuses the caller's existing group (creating one if needed);
joining a code moves the caller into that group. This keeps the "friends"
leaderboard scope a single join instead of a friend graph traversal.
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DbSession

from .. import db_models as m
from ..database import get_db
from ..deps import get_current_user
from ..schemas import FriendGroupOut, InviteOut, JoinRequest

router = APIRouter(prefix="/friends", tags=["friends"])


def _generate_code() -> str:
    return secrets.token_hex(3).upper()  # e.g. "A1B2C3"


@router.post("/invite", response_model=InviteOut)
def invite(db: DbSession = Depends(get_db), user: m.User = Depends(get_current_user)) -> InviteOut:
    if user.friend_group is None:
        group = m.FriendGroup(invite_code=_generate_code(), created_by=user.id)
        db.add(group)
        db.flush()
        user.friend_group_id = group.id
        db.commit()
        db.refresh(user)

    return InviteOut(invite_code=user.friend_group.invite_code)


@router.post("/join", response_model=FriendGroupOut)
def join(
    body: JoinRequest,
    db: DbSession = Depends(get_db),
    user: m.User = Depends(get_current_user),
) -> FriendGroupOut:
    code = body.invite_code.strip().upper()
    group = db.query(m.FriendGroup).filter(m.FriendGroup.invite_code == code).first()
    if group is None:
        raise HTTPException(status_code=404, detail="No friend group with that invite code")

    user.friend_group_id = group.id
    db.commit()

    member_count = db.query(m.User).filter(m.User.friend_group_id == group.id).count()
    return FriendGroupOut(invite_code=group.invite_code, member_count=member_count)
