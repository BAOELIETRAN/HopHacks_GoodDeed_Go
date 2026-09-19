from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DbSession

from .. import db_models as m
from ..agent_client import points_to_next_tier
from ..database import get_db
from ..deps import get_current_user
from ..gamification import compute_badges
from ..schemas import AuthResponse, LoginRequest, SignupRequest, UserOut
from ..security import hash_password, new_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


def _verified_submission_count(db: DbSession, user_id: str) -> int:
    return (
        db.query(m.Submission)
        .filter(m.Submission.user_id == user_id, m.Submission.points > 0)
        .count()
    )


def _user_out(db: DbSession, user: m.User) -> UserOut:
    verified_count = _verified_submission_count(db, user.id)
    return UserOut(
        id=user.id,
        name=user.name,
        email=user.email,
        username=user.username,
        city=user.city,
        tier=user.tier,
        tier_points=user.tier_points,
        points_to_next_tier=points_to_next_tier(user.tier_points),
        current_streak=user.current_streak,
        longest_streak=user.longest_streak,
        badges=compute_badges(user, verified_count),
    )


def _issue_session(db: DbSession, user: m.User) -> str:
    token = new_token()
    db.add(m.Session(token=token, user_id=user.id))
    db.commit()
    return token


@router.post("/signup", response_model=AuthResponse)
def signup(body: SignupRequest, db: DbSession = Depends(get_db)) -> AuthResponse:
    email = body.email.strip().lower()
    if db.query(m.User).filter(m.User.email == email).first() is not None:
        raise HTTPException(status_code=409, detail="An account with that email already exists")

    password_hash, salt = hash_password(body.password)
    user = m.User(
        name=body.name.strip(),
        email=email,
        password_hash=password_hash,
        password_salt=salt,
        username=body.username.strip() if body.username else None,
        city=body.city.strip() if body.city else None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = _issue_session(db, user)
    return AuthResponse(token=token, user=_user_out(db, user))


@router.post("/login", response_model=AuthResponse)
def login(body: LoginRequest, db: DbSession = Depends(get_db)) -> AuthResponse:
    email = body.email.strip().lower()
    user = db.query(m.User).filter(m.User.email == email).first()
    if user is None or not verify_password(body.password, user.password_hash, user.password_salt):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = _issue_session(db, user)
    return AuthResponse(token=token, user=_user_out(db, user))


@router.get("/me", response_model=UserOut)
def me(db: DbSession = Depends(get_db), user: m.User = Depends(get_current_user)) -> UserOut:
    return _user_out(db, user)
