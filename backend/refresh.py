"""Daily refresh of the cached opportunity areas.

Quest results are cached per (lat, lng, radius) bucket and served
stale-while-revalidate, so the first person into an area each morning pays a
multi-second Google fan-out. This walks every area anyone has already looked
at and refreshes it before the day starts, so that cost lands on a scheduled
job instead of on a user.

It refreshes only areas already in the cache. Guessing at cities nobody uses
would burn Places quota on empty maps.

Two ways in, deliberately:

* an in-process timer thread, which is enough when the process stays up;
* ``POST /admin/refresh-opportunities``, for an external scheduler.

On Render's free tier the web service sleeps when idle, so the in-process
timer cannot be relied on to fire at 08:00 -- the HTTP endpoint driven by a
Render Cron Job is the one that actually holds. Both call the same function.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, time as dtime, timedelta

from sqlalchemy.orm import Session as DbSession

from . import db_models as m
from .database import SessionLocal

log = logging.getLogger("gooddeed.refresh")

# Local wall-clock hour to run at.
REFRESH_HOUR = 8


def _parse_cache_key(key: str) -> tuple[float, float, float] | None:
    """``"39.330:-76.620:16"`` -> ``(39.33, -76.62, 16.0)``.

    The bucket coordinates are the only record of which areas are in use, so
    the key is parsed back rather than stored twice and risk drift.
    """
    parts = key.split(":")
    if len(parts) != 3:
        return None
    try:
        return float(parts[0]), float(parts[1]), float(parts[2])
    except ValueError:
        return None


def refresh_cached_areas(db: DbSession, limit: int = 50) -> dict:
    """Re-fetch every cached area. Idempotent: running it twice in a row
    leaves the same rows, because each area's cache is replaced wholesale
    rather than appended to.

    Returns a small summary so the endpoint and the logs can say what
    happened instead of just "ok".
    """
    # Imported here: quests imports config and the agent, and importing it at
    # module scope would make this module part of that cycle.
    from .routers.quests import _cap_for, _replace_cache
    from .agent_client import find_opportunities

    keys = [k for (k,) in db.query(m.Opportunity.cache_key).distinct().limit(limit)]
    summary = {"areas": len(keys), "refreshed": 0, "skipped": 0, "failed": 0, "rows": 0}

    for key in keys:
        parsed = _parse_cache_key(key)
        if parsed is None:
            summary["skipped"] += 1
            continue
        lat, lng, radius = parsed
        try:
            found = find_opportunities(
                lat, lng, radius, max_results=_cap_for(radius), include_website=True
            )
        except Exception:
            # One bad area must not abort the rest of the sweep.
            log.exception("Refresh failed for %s", key)
            summary["failed"] += 1
            continue
        if not found:
            # Keep yesterday's rows rather than emptying someone's map.
            summary["skipped"] += 1
            continue
        _replace_cache(db, key, found)
        db.commit()
        summary["refreshed"] += 1
        summary["rows"] += len(found)

    log.info("Daily opportunity refresh: %s", summary)
    return summary


def run_refresh_now() -> dict:
    """Refresh on a session of our own, for callers outside a request."""
    db = SessionLocal()
    try:
        return refresh_cached_areas(db)
    finally:
        db.close()


def _seconds_until_next_run() -> float:
    now = datetime.now().astimezone()
    target = datetime.combine(now.date(), dtime(REFRESH_HOUR), tzinfo=now.tzinfo)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def start_scheduler() -> threading.Timer:
    """Fire ``run_refresh_now`` at the next 08:00, then every 24h.

    A plain timer thread rather than APScheduler: one scheduled job does not
    justify a dependency, and a daemon thread dies with the process, which is
    the behaviour wanted on a platform that restarts freely.
    """

    def tick() -> None:
        try:
            run_refresh_now()
        except Exception:
            log.exception("Scheduled refresh failed")
        finally:
            start_scheduler()  # re-arm even if this run blew up

    delay = _seconds_until_next_run()
    timer = threading.Timer(delay, tick)
    timer.daemon = True
    timer.name = "opportunity-refresh"
    timer.start()
    log.info("Next opportunity refresh in %.1f h", delay / 3600)
    return timer
