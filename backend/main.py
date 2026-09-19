"""GoodDeed Go -- backend entrypoint.

Run with:

    pip install -r requirements.txt
    uvicorn backend.main:app --reload --port 8000

Interactive docs at http://localhost:8000/docs
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .agent_client import agent_health
from .database import Base, engine
from .routers import auth, friends, leaderboard, quests, reports, submissions

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="GoodDeed Go - backend",
    version="0.1.0",
    description="Data, auth, and leaderboard/tier logic for GoodDeed Go. "
    "Opportunity discovery and scoring are delegated to gooddeed_agent.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(quests.router)
app.include_router(submissions.router)
app.include_router(leaderboard.router)
app.include_router(friends.router)
app.include_router(reports.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "agent": agent_health()}
