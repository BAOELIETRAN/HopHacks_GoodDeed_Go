from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session as DbSession

from .. import db_models as m
from ..agent_client import estimate_points, find_opportunities
from ..config import QUEST_CACHE_GRID, QUEST_CACHE_TTL_SECONDS, VERIFIED_LEGITIMACY_THRESHOLD
from ..database import SessionLocal, get_db
from ..deps import get_current_user
from ..geo import haversine_km
from ..schemas import OpportunityOut

log = logging.getLogger("gooddeed.quests")

router = APIRouter(tags=["quests"])


def _cache_key(lat: float, lng: float, radius_km: float) -> str:
    bucket_lat = round(lat / QUEST_CACHE_GRID) * QUEST_CACHE_GRID
    bucket_lng = round(lng / QUEST_CACHE_GRID) * QUEST_CACHE_GRID
    return f"{bucket_lat:.3f}:{bucket_lng:.3f}:{radius_km:g}"


# One refresh per cache key at a time. Without this, a burst of map loads on
# an expired key would each kick off its own Places fan-out.
_refreshing: set[str] = set()
_refresh_lock = threading.Lock()


def _refresh_in_background(key: str, lat: float, lng: float, radius: float) -> None:
    with _refresh_lock:
        if key in _refreshing:
            return
        _refreshing.add(key)

    def run() -> None:
        # Its own session: the request's session closes when the response is
        # returned, which is the point of doing this off the request path.
        db = SessionLocal()
        try:
            opportunities = find_opportunities(lat, lng, radius)
            if not opportunities:
                return  # keep the stale rows rather than emptying the map
            _replace_cache(db, key, opportunities)
            db.commit()
        except Exception:
            log.exception("Background quest refresh failed for %s", key)
            db.rollback()
        finally:
            db.close()
            with _refresh_lock:
                _refreshing.discard(key)

    threading.Thread(target=run, name=f"quest-refresh-{key}", daemon=True).start()


def _replace_cache(db: DbSession, key: str, opportunities: list[dict]) -> None:
    db.query(m.Opportunity).filter(m.Opportunity.cache_key == key).delete()
    db.add_all([
        m.Opportunity(
            org_name=o["org_name"], address=o["address"], lat=o["lat"], lng=o["lng"],
            category=o["category"], legitimacy_score=o["legitimacy_score"],
            quest_type=o["quest_type"], cache_key=key,
        )
        for o in opportunities
    ])


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

    cached = db.query(m.Opportunity).filter(m.Opportunity.cache_key == key).all()
    if cached:
        newest = max((r.cached_at for r in cached if r.cached_at), default=None)
        if newest is not None and newest.tzinfo is None:
            newest = newest.replace(tzinfo=timezone.utc)

        if newest is not None and newest < fresh_cutoff:
            # Stale-while-revalidate: hand back what we have and refresh off
            # the request path. Waiting four seconds to redraw a map that is
            # already correct is the worse trade -- the data is nonprofits,
            # which do not move.
            _refresh_in_background(key, lat, lng, radius)
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
