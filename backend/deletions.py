"""Shared rules for deleting your own content.

Three things every delete path here has to get right:

* **Reverse your own points, never anyone else's.** Removing a deed you
  logged should remove the points it earned you. It must not touch points
  other people earned from the same event -- if four of you cleaned a
  street and one deletes their record, the other three still did the work.
* **Never leave the wallet incoherent.** Points held against an open
  campaign bounty are promised to someone. A deletion that would drop your
  total below what you have escrowed is refused, with an explanation,
  rather than silently producing a negative balance.
* **Keep the ledger.** PointsTransaction rows survive the deletion of the
  campaign they refer to. "Where did those points go" has to stay
  answerable after the fact, or the audit trail is decorative.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException
from sqlalchemy.orm import Session as DbSession

from . import db_models as m
from .agent_client import tier_for_points

log = logging.getLogger("gooddeed.deletions")


def deduct(db: DbSession, user: m.User, points: int, what: str) -> None:
    """Take back points from the person who earned them.

    Refuses if it would leave less than they have escrowed -- those points
    are already promised to whoever completes the campaign.
    """
    if points <= 0:
        return
    held = user.escrow_points or 0
    remaining = (user.tier_points or 0) - points
    if remaining < held:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Deleting {what} would take you below the {held} points you have "
                "held against open campaigns. Cancel a campaign first."
            ),
        )
    user.tier_points = max(0, remaining)
    user.tier = tier_for_points(user.tier_points)

    # Take the store coins back too, or deleting and re-logging the same
    # deed would mint coins on every round trip. Clamped at zero rather
    # than refused: the coins may already be spent on something that has
    # since hatched, and clawing back a fox nobody can un-see is worse
    # than letting a balance bottom out.
    spent_already = max(0, points - (user.coins or 0))
    user.coins = max(0, (user.coins or 0) - points)
    if spent_already:
        log.info(
            "%s deleted %s worth %d coins but had already spent %d of them",
            user.id, what, points, spent_already,
        )


def purge_submission(db: DbSession, submission: m.Submission) -> None:
    """Remove a deed and everything hanging off it."""
    db.query(m.Reaction).filter(m.Reaction.submission_id == submission.id).delete(
        synchronize_session=False
    )
    db.query(m.Comment).filter(m.Comment.submission_id == submission.id).delete(
        synchronize_session=False
    )
    # A check-in bound to this submission becomes reusable again; the
    # session genuinely happened, it just is not claimed any more.
    if submission.checkin_id:
        checkin = db.get(m.CheckIn, submission.checkin_id)
        if checkin is not None:
            checkin.submission_id = None
    db.delete(submission)
