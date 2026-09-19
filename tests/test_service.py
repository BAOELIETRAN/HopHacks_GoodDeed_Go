"""The optional FastAPI wrapper. Skipped entirely if FastAPI isn't installed."""

from __future__ import annotations

import base64

import pytest

fastapi = pytest.importorskip("fastapi", reason="FastAPI is optional")
pytest.importorskip("httpx", reason="TestClient needs httpx")

from fastapi.testclient import TestClient  # noqa: E402

from conftest import TINY_PNG  # noqa: E402
from gooddeed_agent.service import app  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


DESCRIPTION = "Sorted canned goods into family boxes with two other volunteers all morning."


def test_health_reports_which_providers_are_live(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    # conftest forces mocks, so this is the expected state under test.
    assert body["places_provider"] == "mock"
    assert body["llm_provider"] == "mock"


def test_opportunities_returns_contract_shapes(client):
    response = client.post("/opportunities", json={"lat": 39.29, "lng": -76.61, "radius_km": 5})
    assert response.status_code == 200
    opportunities = response.json()["opportunities"]
    assert opportunities
    for opportunity in opportunities:
        assert set(opportunity) == {
            "org_name", "address", "lat", "lng", "category", "legitimacy_score", "quest_type"
        }


def test_opportunities_validates_its_input(client):
    assert client.post("/opportunities", json={"lat": 39.29}).status_code == 422


def test_score_accepts_a_base64_photo(client):
    response = client.post(
        "/score",
        json={
            "photo_url": base64.standard_b64encode(TINY_PNG).decode(),
            "description": DESCRIPTION,
            "org_name": "Riverside Food Bank",
            "time_spent_minutes": 90,
            "category": "food_bank",
        },
    )
    assert response.status_code == 200
    assert set(response.json()) == {
        "points", "tier_points", "authenticity_confidence", "rationale"
    }


def test_score_rejects_negative_time(client):
    response = client.post(
        "/score",
        json={
            "photo_url": "https://example.com/a.jpg",
            "description": DESCRIPTION,
            "org_name": "Org",
            "time_spent_minutes": -5,
        },
    )
    assert response.status_code == 422


def test_score_upload_accepts_multipart(client):
    response = client.post(
        "/score/upload",
        files={"photo": ("deed.png", TINY_PNG, "image/png")},
        data={"description": DESCRIPTION, "org_name": "Riverside Food Bank", "time_spent_minutes": "90"},
    )
    assert response.status_code == 200
    assert "points" in response.json()


def test_score_upload_rejects_an_empty_file(client):
    response = client.post(
        "/score/upload",
        files={"photo": ("empty.png", b"", "image/png")},
        data={"description": DESCRIPTION, "org_name": "Org", "time_spent_minutes": "10"},
    )
    assert response.status_code == 400


def test_trust_endpoint(client):
    body = client.post("/trust", json={"org_name": "Riverside Food Bank", "address": "1 Maple Ave"}).json()
    assert set(body) == {"legit", "confidence", "summary"}


def test_report_classification_endpoint(client):
    body = client.post(
        "/reports/classify",
        json={
            "photo_url": base64.standard_b64encode(TINY_PNG).decode(),
            "description": "Overflowing trash bins at the corner of 3rd and Maple",
        },
    ).json()
    assert "category" in body and "is_valid" in body


def test_report_upload_endpoint(client):
    response = client.post(
        "/reports/classify/upload",
        files={"photo": ("report.png", TINY_PNG, "image/png")},
        data={"description": "Graffiti on the underpass wall near the park entrance"},
    )
    assert response.status_code == 200
    assert "is_valid" in response.json()


@pytest.mark.parametrize(
    "points,tier,to_next", [(0, "Bronze", 100), (150, "Silver", 350), (900, "Gold", None)]
)
def test_tier_endpoint(client, points, tier, to_next):
    body = client.get(f"/tier/{points}").json()
    assert body["tier"] == tier
    assert body["points_to_next_tier"] == to_next
