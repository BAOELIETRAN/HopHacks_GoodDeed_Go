from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session as DbSession

from .. import db_models as m
from ..agent_client import estimate_points, find_opportunities
from ..config import QUEST_CACHE_GRID, QUEST_CACHE_TTL_SECONDS, VERIFIED_LEGITIMACY_THRESHOLD
from ..database import get_db
from ..deps import get_current_user
from ..geo import haversine_km
from ..schemas import OpportunityOut

router = APIRouter(tags=["quests"])


def _cache_key(lat: float, lng: float, radius_km: float) -> str:
    bucket_lat = round(lat / QUEST_CACHE_GRID) * QUEST_CACHE_GRID
    bucket_lng = round(lng / QUEST_CACHE_GRID) * QUEST_CACHE_GRID
    return f"{bucket_lat:.3f}:{bucket_lng:.3f}:{radius_km:g}"


@router.get("/quests", response_model=list[OpportunityOut])
def get_quests(
    lat: float = Query(...),
    lng: float = Query(...),
    radius: float = Query(default=5.0, gt=0, le=50, description="km"),
    db: DbSession = Depends(get_db),
    _user: m.User = Depends(get_current_user),
) -> list[OpportunityOut]:
    key = _cache_key(lat, lng, radius)
    fresh_cutoff = datetime.now(timezone.utc) - timedelta(seconds=QUEST_CACHE_TTL_SECONDS)

    cached = (
        db.query(m.Opportunity)
        .filter(m.Opportunity.cache_key == key, m.Opportunity.cached_at >= fresh_cutoff)
        .all()
    )
    if cached:
        return [_to_out(row, lat, lng) for row in cached]

    opportunities = find_opportunities(lat, lng, radius)

    db.query(m.Opportunity).filter(m.Opportunity.cache_key == key).delete()
    rows = [
        m.Opportunity(
            org_name=o["org_name"],
            address=o["address"],
            lat=o["lat"],
            lng=o["lng"],
            category=o["category"],
            legitimacy_score=o["legitimacy_score"],
            quest_type=o["quest_type"],
            cache_key=key,
        )
        for o in opportunities
    ]
    db.add_all(rows)
    db.commit()
    return [_to_out(row, lat, lng) for row in rows]


def _to_out(row: m.Opportunity, requester_lat: float, requester_lng: float) -> OpportunityOut:
    return OpportunityOut(
        org_name=row.org_name,
        address=row.address,
        lat=row.lat,
        lng=row.lng,
        category=row.category,
        legitimacy_score=row.legitimacy_score,
        quest_type=row.quest_type,  # type: ignore[arg-type]
        verified=row.legitimacy_score >= VERIFIED_LEGITIMACY_THRESHOLD,
        estimated_points=estimate_points(row.category, row.quest_type),
        distance_km=round(haversine_km(requester_lat, requester_lng, row.lat, row.lng), 2),
    )
