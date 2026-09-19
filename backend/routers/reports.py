from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session as DbSession

from .. import db_models as m
from ..agent_client import (
    classify_report_from_dict,
    estimate_points,
    score_submission_from_dict,
    tier_for_points,
)
from ..config import CLAIM_EXPIRY_HOURS, COMPLETION_MIN_POINTS, REPORTER_POINTS
from ..deletions import deduct, purge_submission
from ..database import get_db
from ..deps import get_current_user
from ..gamification import record_activity
from ..wallet import earn_coins
from ..geo import haversine_km
from ..schemas import ReportCreate, ReportDetailOut, ReportOut, ReportProofSubmit
from ..textclean import public_text

router = APIRouter(tags=["reports"])


def _user_name(db: DbSession, user_id: str | None) -> Optional[str]:
    if user_id is None:
        return None
    user = db.get(m.User, user_id)
    return user.name if user else None


def _is_helper(db: DbSession, report_id: str, user_id: str) -> bool:
    return (
        db.query(m.ReportHelper)
        .filter(m.ReportHelper.report_id == report_id, m.ReportHelper.user_id == user_id)
        .first()
        is not None
    )


def _claim_expires_at(row: m.Report) -> str | None:
    """When an untouched claim returns to the feed, or None if it won't."""
    if row.status != "claimed" or row.proof_submitted_at or not row.claimed_at:
        return None
    try:
        claimed = datetime.fromisoformat(row.claimed_at)
    except (TypeError, ValueError):
        return None
    if claimed.tzinfo is None:
        claimed = claimed.replace(tzinfo=timezone.utc)
    return (claimed + timedelta(hours=CLAIM_EXPIRY_HOURS)).isoformat()


def _to_out(db: DbSession, row: m.Report, viewer: m.User | None = None) -> ReportOut:
    return ReportOut(
        report_id=row.id,
        photo_url=row.photo_url,
        description=row.description,
        lat=row.lat,
        lng=row.lng,
        status=row.status,  # type: ignore[arg-type]
        claimed_by=None,  # never exposed; see ReportHelper
        created_at=row.created_at,
        reported_by=row.reported_by,
        reported_by_name=_user_name(db, row.reported_by) or "?",
        claimed_by_name=None,  # helpers stay anonymous
        estimated_points=estimate_points(row.category),
        awaiting_confirmation=row.status == "claimed" and row.proof_photo_url is not None,
        points_awarded=row.points_awarded,
        # Posts confirmed before this was stored all paid the poster REPORTER_POINTS.
        reporter_points_awarded=(
            row.reporter_points
            if row.reporter_points is not None
            else (REPORTER_POINTS if row.status == "done" else None)
        ),
        award_rationale=row.award_rationale,
        is_mine=bool(viewer and row.reported_by == viewer.id),
        claimed_by_me=bool(viewer and _is_helper(db, row.id, viewer.id)),
        total_slots=row.total_slots or 1,
        filled_slots=row.filled_slots or 0,
        slots_left=max(0, (row.total_slots or 1) - (row.filled_slots or 0)),
        is_full=(row.filled_slots or 0) >= (row.total_slots or 1),
        claim_expires_at=_claim_expires_at(row),
    )


def _to_detail(db: DbSession, row: m.Report, viewer: m.User | None = None) -> ReportDetailOut:
    base = _to_out(db, row, viewer)
    return ReportDetailOut(
        **base.model_dump(),
        claimed_at=row.claimed_at,
        proof_photo_url=row.proof_photo_url,
        proof_description=row.proof_description,
        proof_submitted_at=row.proof_submitted_at,
        confirmed_at=row.confirmed_at,
    )



def _payout_note(helper_points: int, reporter_points: int, helper_count: int) -> str:
    """The plain-language line on a finished card. Written here rather than
    taken from the model, so it is always true, always readable, and never
    exposes raw model text (or placeholder text) on a public feed."""
    who = "The helper earned" if helper_count == 1 else "Each helper earned"
    return (
        f"Confirmed by the poster. {who} +{helper_points} pts, and the poster "
        f"earned +{reporter_points} pts for reporting it."
    )


def release_expired_claims(db: DbSession) -> int:
    """Return abandoned claims to the feed.

    Lazy expiry, run on every list: a background scheduler would be a whole
    extra moving part for a rule this simple, and a claim only matters when
    somebody is looking at the feed.

    A claim with proof already submitted is never released -- that one is
    waiting on the original poster, not on the claimant.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=CLAIM_EXPIRY_HOURS)
    stale = (
        db.query(m.Report)
        .filter(
            m.Report.status == "claimed",
            m.Report.proof_submitted_at.is_(None),
            m.Report.claimed_at.isnot(None),
        )
        .all()
    )
    released = 0
    for row in stale:
        try:
            claimed_at = datetime.fromisoformat(row.claimed_at)
        except (TypeError, ValueError):
            continue
        if claimed_at.tzinfo is None:
            claimed_at = claimed_at.replace(tzinfo=timezone.utc)
        if claimed_at < cutoff:
            row.status = "open"
            row.claimed_by = None
            row.claimed_at = None
            released += 1
    if released:
        db.commit()
    return released


@router.post("/reports", response_model=ReportOut, status_code=201)
def create_report(
    body: ReportCreate,
    db: DbSession = Depends(get_db),
    user: m.User = Depends(get_current_user),
) -> ReportOut:
    report_id = uuid.uuid4().hex
    classification = classify_report_from_dict(
        {
            "report_id": report_id,
            "photo_url": body.photo_url,
            "description": body.description,
            "lat": body.lat,
            "lng": body.lng,
        }
    )

    if not classification["is_valid"]:
        # 400, not 422: the request was well-formed, the content was
        # declined. 422 is what FastAPI returns for schema violations, and
        # sharing it made an explainable rejection look like a client bug.
        raise HTTPException(
            status_code=400,
            detail=classification["reason"] or "That doesn't look like a community need we can post.",
        )

    row = m.Report(
        id=report_id,
        reported_by=user.id,
        photo_url=body.photo_url,
        description=body.description,
        lat=body.lat,
        lng=body.lng,
        status="open",
        total_slots=body.total_slots,
        filled_slots=0,
        created_at=datetime.now(timezone.utc).isoformat(),
        category=classification["category"],
        classification_confidence=classification.get("confidence"),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_out(db, row, user)


@router.get("/reports", response_model=list[ReportOut])
def list_reports(
    lat: float = Query(...),
    lng: float = Query(...),
    radius: float = Query(default=16.0, gt=0, le=50, description="km (~10 miles)"),
    status: Optional[Literal["open", "claimed", "done"]] = Query(
        default=None, description="Omit for the general feed (open + claimed, i.e. not yet done)"
    ),
    db: DbSession = Depends(get_db),
    user: m.User = Depends(get_current_user),
) -> list[ReportOut]:
    release_expired_claims(db)

    query = db.query(m.Report)
    # Finished reports are kept, not dropped. "done" is a filter you choose,
    # not something the feed decides for you -- people want to see what
    # their neighbourhood actually got fixed.
    query = query.filter(m.Report.status == status) if status else query.filter(m.Report.status != "done")

    nearby = [r for r in query.all() if haversine_km(lat, lng, r.lat, r.lng) <= radius]
    nearby.sort(key=lambda r: haversine_km(lat, lng, r.lat, r.lng))

    # A post with every spot taken drops out of browsing -- showing needs
    # nobody can act on is just noise -- but stays visible to the poster
    # and to the people who joined, who still have to finish it.
    mine = {h.report_id for h in db.query(m.ReportHelper).filter(m.ReportHelper.user_id == user.id)}
    visible = [
        r for r in nearby
        if (r.filled_slots or 0) < (r.total_slots or 1)
        or r.reported_by == user.id
        or r.id in mine
    ]
    return [_to_out(db, r, user) for r in visible]


@router.get("/reports/{report_id}", response_model=ReportDetailOut)
def get_report(
    report_id: str,
    db: DbSession = Depends(get_db),
    user: m.User = Depends(get_current_user),
) -> ReportDetailOut:
    row = db.get(m.Report, report_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return _to_detail(db, row, user)


@router.post("/reports/{report_id}/claim", response_model=ReportOut)
def claim_report(
    report_id: str,
    db: DbSession = Depends(get_db),
    user: m.User = Depends(get_current_user),
) -> ReportOut:
    row = db.get(m.Report, report_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Report not found")
    if row.reported_by == user.id:
        raise HTTPException(status_code=400, detail="You can't claim your own report")
    if row.status == "done":
        raise HTTPException(status_code=409, detail="That one's already finished")
    if _is_helper(db, row.id, user.id):
        raise HTTPException(status_code=409, detail="You've already joined this one")

    total = row.total_slots or 1
    if (row.filled_slots or 0) >= total:
        raise HTTPException(status_code=409, detail="All the spots are taken")

    db.add(m.ReportHelper(report_id=row.id, user_id=user.id))
    row.filled_slots = (row.filled_slots or 0) + 1

    # claimed_by holds the *first* helper, for the existing proof flow.
    # It is never returned to clients -- see _to_out.
    if row.claimed_by is None:
        row.claimed_by = user.id
        row.claimed_at = datetime.now(timezone.utc).isoformat()
    row.status = "claimed"

    db.commit()
    db.refresh(row)
    return _to_out(db, row, user)


@router.post("/reports/{report_id}/proof", response_model=ReportDetailOut)
def submit_proof(
    report_id: str,
    body: ReportProofSubmit,
    db: DbSession = Depends(get_db),
    user: m.User = Depends(get_current_user),
) -> ReportDetailOut:
    """The claimant's "after" photo + write-up. Stored but not scored yet --
    the original poster confirms first (see complete_report), same as the
    "AWAITING REPORTER CONFIRMATION" state on the claimed-report detail screen.
    """
    row = db.get(m.Report, report_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Report not found")
    if not _is_helper(db, row.id, user.id):
        raise HTTPException(
            status_code=403, detail="Only someone who joined this one can submit proof"
        )
    if row.status != "claimed":
        raise HTTPException(status_code=409, detail=f"Report is {row.status}, not claimed")

    row.proof_photo_url = body.photo_url
    row.proof_description = body.description
    row.proof_time_spent_minutes = body.time_spent_minutes
    row.proof_submitted_at = datetime.now(timezone.utc).isoformat()
    db.commit()
    db.refresh(row)
    return _to_detail(db, row, user)


@router.post("/reports/{report_id}/complete", response_model=ReportDetailOut)
def complete_report(
    report_id: str,
    db: DbSession = Depends(get_db),
    user: m.User = Depends(get_current_user),
) -> ReportDetailOut:
    """The original poster confirms the claimant's proof. This is also when
    points post -- to the claimant, graded the same way an org-quest
    submission is (score_submission judges authenticity of a claimed deed,
    which is exactly what an "after" photo + description is)."""
    row = db.get(m.Report, report_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Report not found")
    if row.reported_by != user.id:
        raise HTTPException(status_code=403, detail="Only the original poster can confirm this report")
    if row.status == "done":
        raise HTTPException(status_code=409, detail="Report is already done")
    if row.proof_photo_url is None:
        raise HTTPException(status_code=409, detail="Waiting on completion proof from the claimant")

    # Everyone who took a slot gets credited, not only the first. With
    # multi-slot posts the old behaviour paid one person and silently gave
    # the rest nothing for the same work.
    helper_ids = [
        h.user_id
        for h in db.query(m.ReportHelper).filter(m.ReportHelper.report_id == row.id)
    ] or ([row.claimed_by] if row.claimed_by else [])
    helpers = [u for u in (db.get(m.User, hid) for hid in helper_ids) if u is not None]
    if not helpers:
        raise HTTPException(status_code=409, detail="Nobody is recorded as having helped")
    claimant = helpers[0]

    submission_dict = {
        "user_id": claimant.id,
        "org_name": f"Community report: {row.description[:80]}" if row.description else "Community report",
        "photo_url": row.proof_photo_url,
        "description": row.proof_description or "",
        "time_spent_minutes": row.proof_time_spent_minutes or 0,
        "lat": row.lat,
        "lng": row.lng,
        "submitted_at": row.proof_submitted_at,
    }
    score = score_submission_from_dict(submission_dict)

    # The scorer was unreachable, which is not the helper's fault. Leave the
    # report claimed with its proof intact so the poster can confirm again
    # once the service is back, rather than burning the work on a zero.
    if score.get("scoring_unavailable"):
        raise HTTPException(
            status_code=503,
            detail=(
                "We can't verify the photo right now, so we haven't scored this yet. "
                "Your proof is saved — try confirming again shortly."
            ),
        )

    # A confirmed task always pays both people. The AI still scores the proof
    # and can pay a helper more than the floor, but not less: the poster has
    # looked at the result and signed off, and "I did the work and got nothing"
    # is the outcome that makes people stop helping.
    helper_points = max(score["points"], COMPLETION_MIN_POINTS)
    helper_tier_points = max(score["tier_points"], COMPLETION_MIN_POINTS)
    helper_note = public_text(score["rationale"], "Reviewed automatically.") or ""
    if helper_points > score["points"] or helper_tier_points > score["tier_points"]:
        helper_note = f"{helper_note} The poster confirmed the cleanup, so it still counts.".strip()

    # One scored submission per helper, so the deed shows up on each of
    # their profiles and feeds, and every one of them moves their companion.
    for helper in helpers:
        db.add(
            m.Submission(
                user_id=helper.id,
                org_name=submission_dict["org_name"],
                photo_url=row.proof_photo_url,
                description=row.proof_description or "",
                time_spent_minutes=row.proof_time_spent_minutes or 0,
                lat=row.lat,
                lng=row.lng,
                submitted_at=row.proof_submitted_at,
                points=helper_points,
                tier_points=helper_tier_points,
                authenticity_confidence=score["authenticity_confidence"],
                rationale=helper_note,
                deed_type="community_cleanup",
                report_id=row.id,
            )
        )
        helper.tier_points += helper_tier_points
        helper.tier = tier_for_points(helper.tier_points)
        earn_coins(db, helper, helper_tier_points, note="Fixed a community report")
        record_activity(helper)

    # The poster did something too -- they spotted a real problem and wrote
    # it up, and that post already passed its own AI check when it was
    # created. Their award does not hang on how good someone else's
    # after-photo turned out; that would penalise them for another
    # person's camera work.
    #
    # It is recorded as a scored entry, not only added to their total: the
    # leaderboards, the activity feed and "recent impact" all read scored
    # entries, so a bare tier bump left the poster's credit invisible.
    db.add(
        m.Submission(
            user_id=user.id,
            org_name=f"Community report: {row.description[:80]}" if row.description else "Community report",
            photo_url="",  # the photo already lives on the report; don't store it twice
            description=row.description or "",
            time_spent_minutes=0,
            lat=row.lat,
            lng=row.lng,
            submitted_at=row.created_at,
            points=REPORTER_POINTS,
            tier_points=REPORTER_POINTS,
            authenticity_confidence=row.classification_confidence or 1.0,
            rationale="Your report was confirmed fixed.",
            deed_type="community_report",
            report_id=row.id,
        )
    )
    user.tier_points += REPORTER_POINTS
    user.tier = tier_for_points(user.tier_points)
    earn_coins(db, user, REPORTER_POINTS, note="Your report was confirmed fixed")
    record_activity(user)

    row.status = "done"
    row.confirmed_at = datetime.now(timezone.utc).isoformat()
    row.points_awarded = helper_points
    row.reporter_points = REPORTER_POINTS
    row.award_rationale = _payout_note(helper_points, REPORTER_POINTS, len(helpers))

    db.commit()
    db.refresh(row)
    return _to_detail(db, row, user)


@router.delete("/reports/{report_id}", status_code=204)
def delete_report(
    report_id: str,
    db: DbSession = Depends(get_db),
    user: m.User = Depends(get_current_user),
) -> None:
    """Take down a community post you made.

    Helpers keep whatever they earned. They went out and did the work; the
    poster changing their mind about the post does not undo that, and
    clawing it back would be the app taking points off someone for
    somebody else's decision.

    The poster's own reporter award is returned, since the post is gone.
    """
    row = db.get(m.Report, report_id)
    if row is None:
        return
    if row.reported_by != user.id:
        raise HTTPException(status_code=403, detail="That isn't your post")

    if row.status == "done":
        # Every confirmed post paid its poster, whatever the helper scored.
        award = row.reporter_points if row.reporter_points is not None else REPORTER_POINTS
        deduct(db, user, award, "this post")
        # Take back the poster's own entry so the leaderboard agrees with their
        # balance. The helpers' entries stay: they did the work.
        for entry in (
            db.query(m.Submission)
            .filter(
                m.Submission.report_id == row.id,
                m.Submission.user_id == user.id,
                m.Submission.deed_type == "community_report",
            )
            .all()
        ):
            purge_submission(db, entry)

    db.query(m.ReportHelper).filter(m.ReportHelper.report_id == row.id).delete(
        synchronize_session=False
    )
    db.delete(row)
    db.commit()
