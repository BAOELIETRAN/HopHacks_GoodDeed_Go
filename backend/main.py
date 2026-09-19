"""GoodDeed Go -- backend entrypoint.

Run with:

    pip install -r requirements.txt
    uvicorn backend.main:app --reload --port 8000

Interactive docs at http://localhost:8000/docs
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .agent_client import agent_health
from .config import ALLOWED_ORIGINS
from .database import Base, engine
import os

from .migrate import backfill_coins, ensure_schema, relax_password_columns
from .routers import (
    admin, auth, campaigns, checkins, friends, leaderboard, quests, recap,
    reports, social, store, submissions, tasks,
)

Base.metadata.create_all(bind=engine)
ensure_schema(engine)
backfill_coins(engine)
relax_password_columns(engine)

app = FastAPI(
    title="GoodDeed Go - backend",
    version="0.1.0",
    description="Data, auth, and leaderboard/tier logic for GoodDeed Go. "
    "Opportunity discovery and scoring are delegated to gooddeed_agent.",
)

# In production set ALLOWED_ORIGINS to the deployed frontend URL. Left unset
# (local dev) we allow any origin, which keeps file-served and differently
# ported frontends working without configuration.
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS or ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def no_cache_frontend(request, call_next):
    """Stop the browser caching frontend assets.

    Without this, an edited .js or .css keeps serving from cache until a hard
    refresh -- which cost us an hour chasing a map fix that was already
    deployed. The payload is small and the API responses are dynamic anyway,
    so there is nothing worth caching here.
    """
    response = await call_next(request)
    path = request.url.path
    if not path.startswith("/api") and any(
        path.endswith(ext) for ext in (".js", ".css", ".html", "/")
    ):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    return response


app.include_router(auth.router)
app.include_router(quests.router)
app.include_router(checkins.router)
app.include_router(tasks.router)
app.include_router(social.router)
app.include_router(recap.router)
app.include_router(campaigns.router)
app.include_router(store.router)
app.include_router(submissions.router)
app.include_router(leaderboard.router)
app.include_router(friends.router)
app.include_router(reports.router)
app.include_router(admin.router)


@app.on_event("startup")
def _warn_if_scoring_is_stubbed() -> None:
    """Say so loudly. With no OPENAI_API_KEY the app still works, but every
    photo is "scored" by a stub, and that is easy to miss until users notice."""
    if agent_health()["llm_provider"] == "mock":
        logging.getLogger("gooddeed").warning(
            "AI scoring is running on STUB data (no OPENAI_API_KEY, or GOODDEED_USE_MOCKS is set). "
            "Points are placeholders."
        )


@app.on_event("startup")
def _start_daily_refresh() -> None:
    """Arm the 8am opportunity refresh.

    Skipped under pytest: a background timer that outlives the test process
    and reaches for the network has no business in a test run.
    """
    if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("GOODDEED_USE_MOCKS"):
        return
    from .refresh import start_scheduler
    start_scheduler()


# Serve the frontend from the same origin as the API. One deployed service
# instead of two: no CORS, no API base URL to configure per environment, and
# a single origin to register with Google OAuth.
#
# Mounted last so every API route above takes precedence over the catch-all.
_FRONTEND = Path(__file__).resolve().parent.parent / "frontend"


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "agent": agent_health(),
        "database": engine.url.drivername,
    }


if _FRONTEND.is_dir():
    app.mount("/", StaticFiles(directory=_FRONTEND, html=True), name="frontend")
