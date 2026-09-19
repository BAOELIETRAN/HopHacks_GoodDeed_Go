from __future__ import annotations

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session as DbSession

from . import db_models as m
from .database import get_db


def get_current_user(
    authorization: str | None = Header(default=None),
    db: DbSession = Depends(get_db),
) -> m.User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    session = db.get(m.Session, token)
    if session is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = db.get(m.User, session.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="User no longer exists")
    return user
