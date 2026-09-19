"""Optional HTTP wrapper around the agent functions.

The agent layer is importable Python first -- if the backend runs Python, call
the functions directly and skip this file entirely. This exists for the case
where the backend is a different process or language and wants HTTP.

Run it with:

    pip install fastapi uvicorn
    uvicorn gooddeed_agent.service:app --reload --port 8100

Endpoints mirror the four agent functions one-to-one and return the exact
contract shapes. Photos are accepted as a URL or base64 string in JSON, or as
a multipart file upload on the ``/*/upload`` variants.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from . import classify_report, find_opportunities, score_submission, trust_check
from .config import load_settings
from .scoring import points_to_next_tier, tier_for_points

app = FastAPI(
    title="GoodDeed Go - AI agent",
    version="0.1.0",
    description="Opportunity discovery, submission scoring, org trust checks, report triage.",
)


class OpportunityRequest(BaseModel):
    lat: float
    lng: float
    radius_km: float = 5.0
    max_results: int = Field(default=20, ge=1, le=60)
    min_legitimacy: float = Field(default=0.4, ge=0.0, le=1.0)
    verify: bool = False


class SubmissionRequest(BaseModel):
    photo_url: str = Field(description="URL, or a base64 / data: image string")
    description: str
    org_name: str
    time_spent_minutes: int = Field(ge=0)
    category: Optional[str] = None
    quest_multiplier: float = 1.0
    include_debug: bool = False


class TrustRequest(BaseModel):
    org_name: str
    address: str = ""


class ReportRequest(BaseModel):
    photo_url: str
    description: str = ""


@app.get("/health")
def health() -> dict[str, Any]:
    """Liveness plus which providers are live vs mocked -- check this first
    when results look like stub data."""
    settings = load_settings()
    return {
        "status": "ok",
        "model": settings.model,
        "places_provider": "mock" if settings.use_mock_places else "google",
        "llm_provider": "mock" if settings.use_mock_llm else "openai",
    }


@app.post("/opportunities")
def opportunities(req: OpportunityRequest) -> dict[str, Any]:
    return {
        "opportunities": find_opportunities(
            req.lat,
            req.lng,
            req.radius_km,
            max_results=req.max_results,
            min_legitimacy=req.min_legitimacy,
            verify=req.verify,
        )
    }


@app.post("/score")
def score(req: SubmissionRequest) -> dict[str, Any]:
    return score_submission(
        req.photo_url,
        req.description,
        req.org_name,
        req.time_spent_minutes,
        category=req.category,
        quest_multiplier=req.quest_multiplier,
        include_debug=req.include_debug,
    )


@app.post("/score/upload")
async def score_upload(
    photo: UploadFile = File(...),
    description: str = Form(...),
    org_name: str = Form(...),
    time_spent_minutes: int = Form(...),
    category: Optional[str] = Form(None),
    quest_multiplier: float = Form(1.0),
) -> dict[str, Any]:
    raw = await photo.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty photo upload")
    return score_submission(
        raw,
        description,
        org_name,
        time_spent_minutes,
        category=category,
        quest_multiplier=quest_multiplier,
    )


@app.post("/trust")
def trust(req: TrustRequest) -> dict[str, Any]:
    return trust_check(req.org_name, req.address)


@app.post("/reports/classify")
def reports_classify(req: ReportRequest) -> dict[str, Any]:
    return classify_report(req.photo_url, req.description)


@app.post("/reports/classify/upload")
async def reports_classify_upload(
    photo: UploadFile = File(...), description: str = Form("")
) -> dict[str, Any]:
    raw = await photo.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty photo upload")
    return classify_report(raw, description)


@app.get("/tier/{total_tier_points}")
def tier(total_tier_points: int) -> dict[str, Any]:
    """Convenience for the backend: tier + distance to the next one."""
    return {
        "tier": tier_for_points(total_tier_points),
        "tier_points": total_tier_points,
        "points_to_next_tier": points_to_next_tier(total_tier_points),
    }
