from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import insert
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


def _cap_for(radius_km: float) -> int:
    """More area searched, more pins. A fixed cap meant a 25-mile search
    returned the same twenty results as a 1-mile one, which makes the radius
    control look broken even when it is working."""
    return max(20, min(60, int(radius_km * 4)))


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
            opportunities = find_opportunities(lat, lng, radius, max_results=_cap_for(radius))
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
    """Swap the cached rows for this key in as few round trips as possible.

    A 25-mile search caches 60 rows. Inserting them one ORM object at a time
    cost 1.5s against Supabase -- more than the Google fan-out that produced
    them. A single bulk insert is one round trip.
    """
    db.query(m.Opportunity).filter(m.Opportunity.cache_key == key).delete()
    if not opportunities:
        return
    now = datetime.now(timezone.utc)
    db.execute(
        insert(m.Opportunity),
        [
            {
                "id": uuid.uuid4().hex,
                "org_name": o["org_name"], "address": o["address"],
                "lat": o["lat"], "lng": o["lng"], "category": o["category"],
                "legitimacy_score": o["legitimacy_score"],
                "quest_type": o["quest_type"], "cache_key": key, "cached_at": now,
            }
            for o in opportunities
        ],
    )


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

    opportunities = find_opportunities(lat, lng, radius, max_results=_cap_for(radius))

    # Answer from what we already have in memory, and persist the cache off
    # the response path. Writing 60 rows to a hosted Postgres took longer
    # than the Google fan-out that produced them, and the user is waiting on
    # a map, not on our cache being warm.
    _cache_in_background(key, opportunities)
    return _sorted_dicts(opportunities, lat, lng)



def _cache_in_background(key: str, opportunities: list[dict]) -> None:
    """Persist a fresh result set without making the caller wait for it."""
    if not opportunities:
        return

    def run() -> None:
        db = SessionLocal()
        try:
            _replace_cache(db, key, opportunities)
            db.commit()
        except Exception:
            log.exception("Caching quests for %s failed", key)
            db.rollback()
        finally:
            db.close()

    threading.Thread(target=run, name=f"quest-cache-{key}", daemon=True).start()


def _sorted_dicts(opportunities: list[dict], lat: float, lng: float) -> list[OpportunityOut]:
    """Shape agent dicts straight into the response, skipping the DB.

    The rows we just fetched are the same rows we would read back; going via
    Postgres only to re-read them is a round trip for nothing.
    """
    out = [
        OpportunityOut(
            org_name=o["org_name"],
            address=o["address"],
            lat=o["lat"],
            lng=o["lng"],
            category=o["category"],
            legitimacy_score=o["legitimacy_score"],
            quest_type=o["quest_type"],
            verified=o["legitimacy_score"] >= VERIFIED_LEGITIMACY_THRESHOLD,
            estimated_points=estimate_points(o["category"], o["quest_type"]),
            distance_km=round(haversine_km(lat, lng, o["lat"], o["lng"]), 2),
        )
        for o in opportunities
    ]
    out.sort(key=lambda o: o.distance_km)
    return out


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
