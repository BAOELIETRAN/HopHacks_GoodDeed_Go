from __future__ import annotations

import uuid
from datetime import datetime, timezone
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
from ..database import get_db
from ..deps import get_current_user
from ..gamification import record_activity
from ..geo import haversine_km
from ..schemas import ReportCreate, ReportDetailOut, ReportOut, ReportProofSubmit

router = APIRouter(tags=["reports"])


def _user_name(db: DbSession, user_id: str | None) -> Optional[str]:
    if user_id is None:
        return None
    user = db.get(m.User, user_id)
    return user.name if user else None


def _to_out(db: DbSession, row: m.Report) -> ReportOut:
    return ReportOut(
        report_id=row.id,
        photo_url=row.photo_url,
        description=row.description,
        lat=row.lat,
        lng=row.lng,
        status=row.status,  # type: ignore[arg-type]
        claimed_by=row.claimed_by,
        created_at=row.created_at,
        reported_by=row.reported_by,
        reported_by_name=_user_name(db, row.reported_by) or "?",
        claimed_by_name=_user_name(db, row.claimed_by),
        estimated_points=estimate_points(row.category),
        awaiting_confirmation=row.status == "claimed" and row.proof_photo_url is not None,
        points_awarded=row.points_awarded,
    )


def _to_detail(db: DbSession, row: m.Report) -> ReportDetailOut:
    base = _to_out(db, row)
    return ReportDetailOut(
        **base.model_dump(),
        claimed_at=row.claimed_at,
        proof_photo_url=row.proof_photo_url,
        proof_description=row.proof_description,
        proof_submitted_at=row.proof_submitted_at,
        confirmed_at=row.confirmed_at,
    )


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
        raise HTTPException(
            status_code=422,
            detail={"message": classification["reason"], "category": classification["category"]},
        )

    row = m.Report(
        id=report_id,
        reported_by=user.id,
        photo_url=body.photo_url,
        description=body.description,
        lat=body.lat,
        lng=body.lng,
        status="open",
        created_at=datetime.now(timezone.utc).isoformat(),
        category=classification["category"],
        classification_confidence=classification.get("confidence"),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_out(db, row)


@router.get("/reports", response_model=list[ReportOut])
def list_reports(
    lat: float = Query(...),
    lng: float = Query(...),
    radius: float = Query(default=5.0, gt=0, le=50, description="km"),
    status: Optional[Literal["open", "claimed", "done"]] = Query(
        default=None, description="Omit for the general feed (open + claimed, i.e. not yet done)"
    ),
    db: DbSession = Depends(get_db),
    _user: m.User = Depends(get_current_user),
) -> list[ReportOut]:
    query = db.query(m.Report)
    query = query.filter(m.Report.status == status) if status else query.filter(m.Report.status != "done")

    nearby = [r for r in query.all() if haversine_km(lat, lng, r.lat, r.lng) <= radius]
    nearby.sort(key=lambda r: haversine_km(lat, lng, r.lat, r.lng))
    return [_to_out(db, r) for r in nearby]


@router.get("/reports/{report_id}", response_model=ReportDetailOut)
def get_report(
    report_id: str,
    db: DbSession = Depends(get_db),
    _user: m.User = Depends(get_current_user),
) -> ReportDetailOut:
    row = db.get(m.Report, report_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return _to_detail(db, row)


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
    if row.status != "open":
        raise HTTPException(status_code=409, detail=f"Report is already {row.status}")

    row.status = "claimed"
    row.claimed_by = user.id
    row.claimed_at = datetime.now(timezone.utc).isoformat()
    db.commit()
    db.refresh(row)
    return _to_out(db, row)


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
    if row.claimed_by != user.id:
        raise HTTPException(status_code=403, detail="Only the user who claimed this report can submit proof")
    if row.status != "claimed":
        raise HTTPException(status_code=409, detail=f"Report is {row.status}, not claimed")

    row.proof_photo_url = body.photo_url
    row.proof_description = body.description
    row.proof_time_spent_minutes = body.time_spent_minutes
    row.proof_submitted_at = datetime.now(timezone.utc).isoformat()
    db.commit()
    db.refresh(row)
    return _to_detail(db, row)


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

    claimant = db.get(m.User, row.claimed_by)
    if claimant is None:
        raise HTTPException(status_code=409, detail="The user who claimed this report no longer exists")

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

    db.add(
        m.Submission(
            user_id=claimant.id,
            org_name=submission_dict["org_name"],
            photo_url=row.proof_photo_url,
            description=row.proof_description or "",
            time_spent_minutes=row.proof_time_spent_minutes or 0,
            lat=row.lat,
            lng=row.lng,
            submitted_at=row.proof_submitted_at,
            points=score["points"],
            tier_points=score["tier_points"],
            authenticity_confidence=score["authenticity_confidence"],
            rationale=score["rationale"],
        )
    )

    claimant.tier_points += score["tier_points"]
    claimant.tier = tier_for_points(claimant.tier_points)
    if score["points"] > 0:
        record_activity(claimant)

    row.status = "done"
    row.confirmed_at = datetime.now(timezone.utc).isoformat()
    row.points_awarded = score["points"]

    db.commit()
    db.refresh(row)
    return _to_detail(db, row)
