"""Turn a place name into coordinates, and coordinates back into a place name.

The app's real source of location is the browser's own fix, but that is
unavailable far more often than it looks: browsers block geolocation outright
on an insecure origin (which includes the plain http:// LAN address run.sh
prints for testing on a phone), most desktops have no GPS at all, and a denied
permission prompt never asks again. Every one of those cases used to fall
through to a hardcoded Baltimore coordinate, so the app described the wrong
city and never said so. These two endpoints are the way back: type where you
are, and see the name of wherever the app currently thinks you are.

Nominatim (OpenStreetMap) rather than Google Geocoding: there is no extra API
to enable on the key, and the map tiles are already OSM. Its usage policy asks
for an identifying User-Agent, at most one request a second, and that results
be cached. All three are handled here -- the alternative is getting the
project's IP blocked in the middle of a demo.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import OrderedDict
from typing import Any

import requests
from fastapi import APIRouter, Depends, HTTPException, Query

from .. import db_models as m
from ..deps import get_current_user

log = logging.getLogger("gooddeed.geo")

router = APIRouter(prefix="/geo", tags=["geo"])

_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
_TIMEOUT_S = 8.0

# Nominatim rejects requests without a real User-Agent, and asks that it name
# the application and a way to reach whoever runs it.
_USER_AGENT = (
    os.environ.get("GEOCODE_USER_AGENT", "").strip()
    or "GoodDeedGo/0.1 (set GEOCODE_USER_AGENT to a contact address)"
)

# One request a second, enforced for the whole process rather than trusted to
# callers. FastAPI runs sync endpoints on a thread pool, so this needs a lock.
_MIN_INTERVAL_S = 1.1
_pace_lock = threading.Lock()
_last_call_at = 0.0

# Places do not move, so a hit here is as good as a fresh call and costs
# nothing. Bounded so a stream of junk queries cannot grow it without limit.
_CACHE_MAX = 512
_cache: "OrderedDict[str, Any]" = OrderedDict()
_cache_lock = threading.Lock()


def _cache_get(key: str) -> Any:
    with _cache_lock:
        if key not in _cache:
            return None
        _cache.move_to_end(key)
        return _cache[key]


def _cache_put(key: str, value: Any) -> None:
    with _cache_lock:
        _cache[key] = value
        _cache.move_to_end(key)
        while len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)


def _call(url: str, params: dict) -> Any:
    """One paced, identified call to Nominatim."""
    global _last_call_at
    with _pace_lock:
        wait = _MIN_INTERVAL_S - (time.monotonic() - _last_call_at)
        if wait > 0:
            time.sleep(wait)
        _last_call_at = time.monotonic()

    try:
        res = requests.get(
            url,
            params=params,
            timeout=_TIMEOUT_S,
            headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
        )
        res.raise_for_status()
        return res.json()
    except (requests.RequestException, ValueError) as exc:
        log.warning("Place lookup failed (%s): %s", url, exc)
        raise HTTPException(
            status_code=503,
            detail="Couldn't reach the place lookup service. Try again in a moment.",
        ) from exc


@router.get("/search")
def search_places(
    q: str = Query(..., min_length=2, max_length=120),
    limit: int = Query(default=5, ge=1, le=10),
    _user: m.User = Depends(get_current_user),
) -> list[dict]:
    """Coordinates for a typed place: a city, a postcode, a street, a campus."""
    query = q.strip()
    key = f"s:{query.lower()}:{limit}"
    hit = _cache_get(key)
    if hit is not None:
        return hit

    rows = _call(_SEARCH_URL, {"q": query, "format": "jsonv2", "limit": limit})
    out = []
    for row in rows or []:
        try:
            out.append(
                {
                    "label": row.get("display_name") or query,
                    "lat": float(row["lat"]),
                    "lng": float(row["lon"]),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue  # a result we can't place is not a result

    _cache_put(key, out)
    return out


@router.get("/reverse")
def describe_point(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    _user: m.User = Depends(get_current_user),
) -> dict:
    """A short place name for a coordinate -- "Cambridge, Massachusetts".

    This exists because the whole class of bug it was added for was invisible:
    nothing on screen ever named the place the app had decided you were in, so
    a default coordinate looked exactly like a working app.
    """
    # ~110m of rounding. Standing still should hit the cache; walking a block
    # should not need a new name for the same town.
    key = f"r:{round(lat, 3)}:{round(lng, 3)}"
    hit = _cache_get(key)
    if hit is not None:
        return hit

    data = _call(_REVERSE_URL, {"lat": lat, "lon": lng, "format": "jsonv2", "zoom": 12}) or {}
    addr = data.get("address") or {}
    town = (
        addr.get("city")
        or addr.get("town")
        or addr.get("village")
        or addr.get("suburb")
        or addr.get("county")
        or ""
    )
    region = addr.get("state") or addr.get("region") or addr.get("country") or ""
    label = ", ".join(p for p in (town, region) if p) or data.get("display_name") or ""

    out = {"label": label}
    _cache_put(key, out)
    return out
