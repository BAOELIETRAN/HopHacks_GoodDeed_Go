from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session as DbSession

from .. import db_models as m
from ..agent_client import (
    multiplier_for_quest_type,
    score_submission_from_dict,
    tier_for_points,
)
from ..config import VERIFIED_PRESENCE_MULTIPLIER
from ..database import get_db
from ..deps import get_current_user
from ..gamification import record_activity
from ..schemas import SubmissionCreate, SubmissionOut
from .checkins import consume_for_submission

router = APIRouter(tags=["submissions"])


@router.post("/submissions", response_model=SubmissionOut)
def create_submission(
    body: SubmissionCreate,
    db: DbSession = Depends(get_db),
    user: m.User = Depends(get_current_user),
) -> SubmissionOut:
    # If we've seen this org via /quests recently, use its known category and
    # quest_type (daily vs monthly) instead of letting the model guess.
    matched = (
        db.query(m.Opportunity)
        .filter(func.lower(m.Opportunity.org_name) == body.org_name.strip().lower())
        .order_by(m.Opportunity.cached_at.desc())
        .first()
    )
    category = matched.category if matched else None
    quest_type = matched.quest_type if matched else "daily"

    # A presence-verified session overrides everything the client said about
    # time and category: the server measured it, so there is no reason to
    # trust the typed value over the recorded one.
    checkin = None
    minutes = body.time_spent_minutes
    if body.checkin_id:
        checkin = consume_for_submission(db, user, body.checkin_id)
        minutes = checkin.elapsed_seconds // 60
        category = checkin.category or category
        quest_type = checkin.quest_type or quest_type

    multiplier = multiplier_for_quest_type(quest_type)
    if checkin is not None:
        # Verified presence is worth more than an unverifiable claim. This
        # is the incentive that makes checking in worth the extra tap.
        multiplier *= VERIFIED_PRESENCE_MULTIPLIER

    submission_dict = {
        "user_id": user.id,
        "org_name": body.org_name,
        "photo_url": body.photo_url,
        "description": body.description,
        "time_spent_minutes": minutes,
        "lat": body.lat,
        "lng": body.lng,
        "submitted_at": body.submitted_at,
    }
    score = score_submission_from_dict(submission_dict, category=category, quest_multiplier=multiplier)

    row = m.Submission(
        user_id=user.id,
        org_name=body.org_name,
        photo_url=body.photo_url,
        description=body.description,
        time_spent_minutes=minutes,
        lat=body.lat,
        lng=body.lng,
        submitted_at=body.submitted_at,
        points=score["points"],
        tier_points=score["tier_points"],
        authenticity_confidence=score["authenticity_confidence"],
        rationale=score["rationale"],
        checkin_id=checkin.id if checkin else None,
        verified_presence=checkin is not None,
    )
    db.add(row)
    db.flush()
    if checkin is not None:
        # Bind the session to this submission so one shift can't be
        # submitted twice.
        checkin.submission_id = row.id

    user.tier_points += score["tier_points"]
    user.tier = tier_for_points(user.tier_points)
    user.lat = body.lat
    user.lng = body.lng

    # A rejected/zero-point submission doesn't extend the streak -- "only
    # verified completions count" per the leaderboard screen's own copy.
    is_personal_best = record_activity(user) if score["points"] > 0 else False

    db.commit()
    db.refresh(row)

    return SubmissionOut(
        id=row.id,
        user_id=row.user_id,
        org_name=row.org_name,
        photo_url=row.photo_url,
        description=row.description,
        time_spent_minutes=row.time_spent_minutes,
        lat=row.lat,
        lng=row.lng,
        submitted_at=row.submitted_at,
        points=row.points,
        tier_points=row.tier_points,
        authenticity_confidence=row.authenticity_confidence,
        rationale=row.rationale,
        user_tier=user.tier,
        user_tier_points=user.tier_points,
        current_streak=user.current_streak,
        is_personal_best=is_personal_best,
        verified_presence=row.verified_presence,
    )
