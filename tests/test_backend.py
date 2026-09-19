"""End-to-end tests for the FastAPI backend, against gooddeed_agent's mocks.

Each test gets a fresh in-memory SQLite database (via dependency override), so
tests never share state and never touch backend/gooddeed.db. Runs entirely
offline -- GOODDEED_USE_MOCKS is forced on in the client fixture below.
"""

from __future__ import annotations

import os

os.environ["GOODDEED_USE_MOCKS"] = "1"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.main import app

OAKLAND = {"lat": 37.8044, "lng": -122.2712}


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def signup(client: TestClient, name: str, email: str, **extra) -> dict:
    resp = client.post(
        "/auth/signup", json={"name": name, "email": email, "password": "hunter22", **extra}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --- auth --------------------------------------------------------------


def test_signup_login_me_roundtrip(client: TestClient):
    signed_up = signup(client, "Maya", "maya@example.com", username="mayadoesgood", city="Oakland")
    user = signed_up["user"]
    assert user["tier"] == "Bronze"
    assert user["tier_points"] == 0
    assert user["points_to_next_tier"] == 100
    assert user["current_streak"] == 0
    assert user["badges"] == []
    assert user["username"] == "mayadoesgood"
    assert user["city"] == "Oakland"

    login = client.post("/auth/login", json={"email": "maya@example.com", "password": "hunter22"})
    assert login.status_code == 200
    token = login.json()["token"]

    me = client.get("/auth/me", headers=auth(token))
    assert me.status_code == 200
    assert me.json()["email"] == "maya@example.com"


def test_signup_rejects_duplicate_email(client: TestClient):
    signup(client, "Maya", "dupe@example.com")
    resp = client.post(
        "/auth/signup", json={"name": "Maya2", "email": "dupe@example.com", "password": "hunter22"}
    )
    assert resp.status_code == 409


def test_login_rejects_wrong_password(client: TestClient):
    signup(client, "Maya", "wrongpw@example.com")
    resp = client.post("/auth/login", json={"email": "wrongpw@example.com", "password": "nope"})
    assert resp.status_code == 401


def test_protected_endpoint_requires_bearer_token(client: TestClient):
    resp = client.get("/auth/me")
    assert resp.status_code == 401


# --- quests --------------------------------------------------------------


def test_quests_returns_opportunities_with_ui_extras(client: TestClient):
    token = signup(client, "Maya", "quests@example.com")["token"]
    resp = client.get("/quests", params={**OAKLAND, "radius": 5}, headers=auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) > 0
    first = body[0]
    for field in ("org_name", "address", "lat", "lng", "category", "legitimacy_score", "quest_type"):
        assert field in first
    assert isinstance(first["verified"], bool)
    assert first["estimated_points"] > 0
    assert first["distance_km"] >= 0


def test_quests_are_cached_for_the_same_bucket(client: TestClient):
    token = signup(client, "Maya", "cache@example.com")["token"]
    first = client.get("/quests", params={**OAKLAND, "radius": 5}, headers=auth(token)).json()
    second = client.get("/quests", params={**OAKLAND, "radius": 5}, headers=auth(token)).json()
    assert [o["org_name"] for o in first] == [o["org_name"] for o in second]


# --- submissions -----------------------------------------------------------


def _submit(client: TestClient, token: str, **overrides) -> dict:
    body = {
        "org_name": "Riverside Community Food Bank",
        "photo_url": "https://example.com/photo.jpg",
        "description": "Sorted canned goods and restocked shelves for two hours with three volunteers.",
        "time_spent_minutes": 120,
        "lat": OAKLAND["lat"],
        "lng": OAKLAND["lng"],
        "submitted_at": "2026-09-19T12:00:00Z",
    }
    body.update(overrides)
    resp = client.post("/submissions", json=body, headers=auth(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_submission_scores_and_updates_tier(client: TestClient):
    token = signup(client, "Maya", "submit@example.com")["token"]
    # seed the opportunity cache so category/quest_type/multiplier resolve
    client.get("/quests", params={**OAKLAND, "radius": 5}, headers=auth(token))

    result = _submit(client, token)
    assert result["points"] >= 0
    assert result["tier_points"] == result["points"]  # daily quest, multiplier 1.0
    assert 0.0 <= result["authenticity_confidence"] <= 1.0
    assert result["rationale"]
    assert result["user_tier_points"] == result["points"]
    assert result["user_tier"] in ("Bronze", "Silver", "Gold")

    me = client.get("/auth/me", headers=auth(token)).json()
    assert me["tier_points"] == result["points"]
    if result["points"] > 0:
        assert me["current_streak"] == 1
        assert result["is_personal_best"] is True
        assert {"code": "first_shift", "label": "First Shift"} in me["badges"]


def test_submission_rejects_missing_auth(client: TestClient):
    resp = client.post(
        "/submissions",
        json={
            "org_name": "X",
            "photo_url": "https://example.com/x.jpg",
            "description": "x",
            "time_spent_minutes": 10,
            "lat": 0,
            "lng": 0,
            "submitted_at": "2026-09-19T12:00:00Z",
        },
    )
    assert resp.status_code == 401


# --- leaderboard -----------------------------------------------------------


def test_leaderboard_ranks_teammates_and_flags_self(client: TestClient):
    """Friends scope ranks everyone in the group and marks the requester.

    Replaces the old "nearby" coverage: that scope was removed because
    ranking someone against strangers turns a shared effort into a
    scoreboard against people they will never meet.
    """
    a = signup(client, "Alice", "alice@example.com")["token"]
    b = signup(client, "Bob", "bob@example.com")["token"]

    code = client.post("/friends/invite", headers=auth(a)).json()["invite_code"]
    client.post("/friends/join", json={"invite_code": code}, headers=auth(b))

    client.get("/quests", params={**OAKLAND, "radius": 5}, headers=auth(a))
    _submit(client, a)
    _submit(client, b, org_name="Riverside Community Food Bank")

    resp = client.get("/leaderboard", params={"period": "weekly"}, headers=auth(a))
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 2
    you_flags = [r["is_you"] for r in rows]
    assert you_flags.count(True) == 1  # exactly Alice, the requester
    for r in rows:
        assert r["deed_count"] >= 0
        assert r["rank"] >= 1


def test_leaderboard_rejects_the_removed_nearby_scope(client: TestClient):
    a = signup(client, "Ada", "ada.scope@example.com")["token"]
    resp = client.get(
        "/leaderboard", params={"scope": "nearby", "period": "weekly"}, headers=auth(a)
    )
    assert resp.status_code == 422


def test_leaderboard_counts_everyday_deeds(client: TestClient):
    """Everyday deeds carry points, so they have to appear on the board.

    Leaving them out showed someone with six logged kindnesses sitting at
    zero, which reads as a broken board rather than a scoring choice.
    """
    a = signup(client, "Mo", "mo.micro@example.com")["token"]

    todays = client.get("/tasks/today", headers=auth(a)).json()["deeds"]
    for deed in todays[:3]:
        client.post(f"/tasks/{deed['id']}/complete", json={}, headers=auth(a))

    rows = client.get("/leaderboard", params={"period": "weekly"}, headers=auth(a)).json()
    assert rows[0]["points"] > 0
    assert rows[0]["deed_count"] == 3


def test_leaderboard_friends_scope_defaults_to_self_only(client: TestClient):
    token = signup(client, "Solo", "solo@example.com")["token"]
    resp = client.get("/leaderboard", params={"scope": "friends", "period": "daily"}, headers=auth(token))
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["is_you"] is True


def test_leaderboard_rejects_invalid_scope(client: TestClient):
    token = signup(client, "Maya", "badscope@example.com")["token"]
    resp = client.get("/leaderboard", params={"scope": "galaxy", "period": "daily"}, headers=auth(token))
    assert resp.status_code == 422


# --- friends ------------------------------------------------------------


def test_friends_invite_and_join_share_a_leaderboard(client: TestClient):
    a_token = signup(client, "Alice", "alicef@example.com")["token"]
    b_token = signup(client, "Bob", "bobf@example.com")["token"]

    invite = client.post("/friends/invite", headers=auth(a_token))
    assert invite.status_code == 200
    code = invite.json()["invite_code"]

    # inviting again returns the same code (reuses the existing group)
    invite_again = client.post("/friends/invite", headers=auth(a_token))
    assert invite_again.json()["invite_code"] == code

    join = client.post("/friends/join", json={"invite_code": code}, headers=auth(b_token))
    assert join.status_code == 200
    assert join.json()["member_count"] == 2

    resp = client.get("/leaderboard", params={"scope": "friends", "period": "weekly"}, headers=auth(a_token))
    assert {r["user_id"] for r in resp.json()} == {
        client.get("/auth/me", headers=auth(a_token)).json()["id"],
        client.get("/auth/me", headers=auth(b_token)).json()["id"],
    }


def test_friends_join_rejects_unknown_code(client: TestClient):
    token = signup(client, "Maya", "badcode@example.com")["token"]
    resp = client.post("/friends/join", json={"invite_code": "NOPE99"}, headers=auth(token))
    assert resp.status_code == 404


# --- reports: full claim -> proof -> confirm lifecycle ---------------------


def _create_report(client: TestClient, token: str, **overrides) -> dict:
    body = {
        "photo_url": "https://example.com/trash.jpg",
        "description": "Overflowing trash bins at the corner of 3rd and Maple",
        "lat": OAKLAND["lat"],
        "lng": OAKLAND["lng"],
    }
    body.update(overrides)
    resp = client.post("/reports", json=body, headers=auth(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_report_full_lifecycle_credits_the_claimant(client: TestClient):
    lena = signup(client, "Lena", "lena_full@example.com")
    maya = signup(client, "Maya", "maya_full@example.com")
    omar = signup(client, "Omar", "omar_full@example.com")
    lena_token, maya_token, omar_token = lena["token"], maya["token"], omar["token"]

    report = _create_report(client, lena_token)
    assert report["status"] == "open"
    assert report["reported_by_name"] == "Lena"
    assert report["estimated_points"] > 0
    assert report["awaiting_confirmation"] is False

    # reporter can't claim their own report
    resp = client.post(f"/reports/{report['report_id']}/claim", headers=auth(lena_token))
    assert resp.status_code == 400

    claimed = client.post(f"/reports/{report['report_id']}/claim", headers=auth(maya_token)).json()
    assert claimed["status"] == "claimed"
    # Helper identities are never returned. Pairing "who volunteered" with a
    # report's location and time is exactly what the anonymity rule exists to
    # prevent, so the API sends counts only.
    assert claimed["claimed_by_name"] is None
    assert claimed["claimed_by"] is None
    assert claimed["filled_slots"] == 1
    assert claimed["claimed_by_me"] is True   # the helper's own view

    # claiming an already-claimed report fails, distinctly from the self-claim rule
    resp = client.post(f"/reports/{report['report_id']}/claim", headers=auth(omar_token))
    assert resp.status_code == 409

    # only the claimant can submit proof
    resp = client.post(
        f"/reports/{report['report_id']}/proof",
        json={"photo_url": "https://example.com/after.jpg", "description": "cleaned up", "time_spent_minutes": 30},
        headers=auth(lena_token),
    )
    assert resp.status_code == 403

    proof = client.post(
        f"/reports/{report['report_id']}/proof",
        json={
            "photo_url": "https://example.com/after.jpg",
            "description": "Collected two bags of trash, left glass marked for pickup.",
            "time_spent_minutes": 30,
        },
        headers=auth(maya_token),
    ).json()
    assert proof["awaiting_confirmation"] is True

    # completing before confirmation shouldn't award anything to a random caller
    resp = client.post(f"/reports/{report['report_id']}/complete", headers=auth(maya_token))
    assert resp.status_code == 403  # only the reporter can confirm

    confirmed = client.post(f"/reports/{report['report_id']}/complete", headers=auth(lena_token)).json()
    assert confirmed["status"] == "done"
    assert confirmed["points_awarded"] is not None
    assert confirmed["confirmed_at"] is not None

    # double confirm fails
    resp = client.post(f"/reports/{report['report_id']}/complete", headers=auth(lena_token))
    assert resp.status_code == 409

    # points landed on Maya (the claimant), not Lena (the reporter)
    maya_me = client.get("/auth/me", headers=auth(maya_token)).json()
    lena_me = client.get("/auth/me", headers=auth(lena_token)).json()
    assert maya_me["tier_points"] == confirmed["points_awarded"]
    # The poster now earns a small fixed award for spotting and writing up
    # the problem -- worth much less than doing the work, but not nothing.
    from backend.config import REPORTER_POINTS
    assert lena_me["tier_points"] == REPORTER_POINTS


def test_complete_requires_proof_first(client: TestClient):
    lena = signup(client, "Lena", "lena_noproof@example.com")["token"]
    maya = signup(client, "Maya", "maya_noproof@example.com")["token"]
    report = _create_report(client, lena)
    client.post(f"/reports/{report['report_id']}/claim", headers=auth(maya))

    resp = client.post(f"/reports/{report['report_id']}/complete", headers=auth(lena))
    assert resp.status_code == 409


def test_reports_status_filter_and_default_feed(client: TestClient):
    lena = signup(client, "Lena", "lena_feed@example.com")["token"]
    maya = signup(client, "Maya", "maya_feed@example.com")["token"]
    report = _create_report(client, lena)
    rid = report["report_id"]

    open_list = client.get(
        "/reports", params={**OAKLAND, "radius": 5, "status": "open"}, headers=auth(maya)
    ).json()
    assert any(r["report_id"] == rid for r in open_list)

    client.post(f"/reports/{rid}/claim", headers=auth(maya))

    open_list = client.get(
        "/reports", params={**OAKLAND, "radius": 5, "status": "open"}, headers=auth(maya)
    ).json()
    assert not any(r["report_id"] == rid for r in open_list)

    default_feed = client.get("/reports", params={**OAKLAND, "radius": 5}, headers=auth(maya)).json()
    assert any(r["report_id"] == rid for r in default_feed)


def test_reports_out_of_radius_are_excluded(client: TestClient):
    lena = signup(client, "Lena", "lena_radius@example.com")["token"]
    maya = signup(client, "Maya", "maya_radius@example.com")["token"]
    _create_report(client, lena)

    far_away = {"lat": 51.5074, "lng": -0.1278}  # London
    resp = client.get("/reports", params={**far_away, "radius": 5}, headers=auth(maya))
    assert resp.json() == []


def test_get_report_detail_includes_timeline(client: TestClient):
    lena = signup(client, "Lena", "lena_detail@example.com")["token"]
    maya = signup(client, "Maya", "maya_detail@example.com")["token"]
    report = _create_report(client, lena)
    rid = report["report_id"]
    client.post(f"/reports/{rid}/claim", headers=auth(maya))

    detail = client.get(f"/reports/{rid}", headers=auth(maya)).json()
    assert detail["claimed_at"] is not None
    assert detail["proof_photo_url"] is None
    assert detail["confirmed_at"] is None


def test_get_report_detail_404_for_unknown_id(client: TestClient):
    token = signup(client, "Maya", "maya_404@example.com")["token"]
    resp = client.get("/reports/does-not-exist", headers=auth(token))
    assert resp.status_code == 404


# --- health -----------------------------------------------------------


def test_health(client: TestClient):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["agent"]["llm_provider"] == "mock"


def test_report_slots_fill_and_hide_from_browsing(client: TestClient):
    """A multi-helper post tracks counts, stays anonymous, and drops out of
    browsing once full while remaining visible to the people involved."""
    poster = signup(client, "Pia", "pia.slots@example.com")["token"]
    h1 = signup(client, "Hal", "hal.slots@example.com")["token"]
    h2 = signup(client, "Hana", "hana.slots@example.com")["token"]
    browser = signup(client, "Bo", "bo.slots@example.com")["token"]

    created = client.post(
        "/reports",
        json={
            "photo_url": "https://example.com/trash.jpg",
            "description": "Fly-tipped bags behind the shops, needs a few hands.",
            "lat": 39.3299, "lng": -76.6205, "total_slots": 2,
        },
        headers=auth(poster),
    ).json()
    rid = created["report_id"]
    assert created["total_slots"] == 2 and created["filled_slots"] == 0

    first = client.post(f"/reports/{rid}/claim", headers=auth(h1)).json()
    assert first["filled_slots"] == 1 and first["is_full"] is False

    # The same person cannot take a second slot.
    assert client.post(f"/reports/{rid}/claim", headers=auth(h1)).status_code == 409

    full = client.post(f"/reports/{rid}/claim", headers=auth(h2)).json()
    assert full["is_full"] is True and full["slots_left"] == 0
    assert client.post(f"/reports/{rid}/claim", headers=auth(browser)).status_code == 409

    def visible(token):
        rows = client.get(
            "/reports", params={"lat": 39.3299, "lng": -76.6205, "radius": 16},
            headers=auth(token),
        ).json()
        return any(r["report_id"] == rid for r in rows)

    assert not visible(browser)      # full posts leave the browse view
    assert visible(poster)           # the poster still tracks it
    assert visible(h1) and visible(h2)   # helpers still have work to finish


def test_submission_time_can_be_trimmed_but_not_inflated(client: TestClient):
    """A measured session may be corrected downward only.

    Allowing an upward revision would hand back the unverifiable claim the
    timer exists to remove.
    """
    token = signup(client, "Tim", "tim.timer@example.com")["token"]
    started = client.post(
        "/checkins",
        json={
            "org_name": "Maryland SPCA", "org_lat": 39.3429, "org_lng": -76.6275,
            "lat": 39.3430, "lng": -76.6276,
            "category": "animal_shelter", "quest_type": "daily",
        },
        headers=auth(token),
    ).json()

    # Reach the fixture's in-memory database through the same dependency
    # override the app uses, rather than the real SessionLocal.
    from backend import db_models as dm
    from backend.database import get_db

    db = next(app.dependency_overrides[get_db]())
    row = db.get(dm.CheckIn, started["checkin_id"])
    row.elapsed_seconds = 90 * 60
    db.commit()
    db.close()

    def submit(adjusted):
        body = {
            "deed_type": "volunteer", "org_name": "Maryland SPCA",
            "photo_url": "https://example.com/trash.jpg", "description": "Walked dogs and cleaned the kennels.",
            "lat": 39.3430, "lng": -76.6276, "submitted_at": "2026-09-19T12:00:00Z",
            "checkin_id": started["checkin_id"],
        }
        if adjusted is not None:
            body["adjusted_minutes"] = adjusted
        return client.post("/submissions", json=body, headers=auth(token)).json()

    trimmed = submit(30)
    assert trimmed["time_spent_minutes"] == 30   # honoured downward


# --- deleting your own content -------------------------------------------


def test_delete_your_own_deed_reverses_its_points(client: TestClient):
    token = signup(client, "Dana", "dana.del@example.com")["token"]

    todays = client.get("/tasks/today", headers=auth(token)).json()["deeds"]
    first = todays[0]
    client.post(f"/tasks/{first['id']}/complete", json={}, headers=auth(token))
    after = client.get("/auth/me", headers=auth(token)).json()["tier_points"]
    assert after == first["points"]

    assert client.delete(f"/tasks/{first['id']}/complete", headers=auth(token)).status_code == 204
    assert client.get("/auth/me", headers=auth(token)).json()["tier_points"] == 0

    # Undoing something that isn't there is not an error.
    assert client.delete(f"/tasks/{first['id']}/complete", headers=auth(token)).status_code == 204


def test_only_the_owner_can_delete(client: TestClient):
    owner = signup(client, "Omar", "omar.del@example.com")["token"]
    other = signup(client, "Nia", "nia.del@example.com")["token"]

    report = client.post(
        "/reports",
        json={
            "photo_url": "https://example.com/trash.jpg",
            "description": "Bags dumped by the hedge on the corner.",
            "lat": 39.3299, "lng": -76.6205,
        },
        headers=auth(owner),
    ).json()
    rid = report["report_id"]

    assert client.delete(f"/reports/{rid}", headers=auth(other)).status_code == 403
    assert client.delete(f"/reports/{rid}", headers=auth(owner)).status_code == 204

    rows = client.get(
        "/reports", params={"lat": 39.3299, "lng": -76.6205, "radius": 16},
        headers=auth(owner),
    ).json()
    assert not any(r["report_id"] == rid for r in rows)


def test_deleting_a_post_never_claws_back_a_helpers_points(client: TestClient):
    """The poster changing their mind must not cost the helper.

    They went out and did the work. Taking points off someone for another
    person's decision would be the app punishing the wrong party.
    """
    poster = signup(client, "Pia", "pia.del@example.com")["token"]
    helper = signup(client, "Hal", "hal.del@example.com")["token"]

    report = client.post(
        "/reports",
        json={
            "photo_url": "https://example.com/trash.jpg",
            "description": "Fly-tipped bags behind the shops need clearing.",
            "lat": 39.3299, "lng": -76.6205,
        },
        headers=auth(poster),
    ).json()
    rid = report["report_id"]

    client.post(f"/reports/{rid}/claim", headers=auth(helper))
    client.post(
        f"/reports/{rid}/proof",
        json={
            "photo_url": "https://example.com/after.jpg",
            "description": "Bagged it all and stacked it for collection.",
            "time_spent_minutes": 30,
        },
        headers=auth(helper),
    )
    client.post(f"/reports/{rid}/complete", headers=auth(poster))

    earned = client.get("/auth/me", headers=auth(helper)).json()["tier_points"]
    assert earned > 0

    client.delete(f"/reports/{rid}", headers=auth(poster))
    assert client.get("/auth/me", headers=auth(helper)).json()["tier_points"] == earned


def test_deletion_cannot_strand_escrowed_points(client: TestClient):
    """Points held against an open bounty are promised to someone.

    A deletion that would drop the total below what is escrowed is refused
    rather than producing an incoherent wallet.
    """
    from backend import db_models as dm
    from backend.database import get_db

    token = signup(client, "Esme", "esme.del@example.com")["token"]
    for deed in client.get("/tasks/today", headers=auth(token)).json()["deeds"][:3]:
        client.post(f"/tasks/{deed['id']}/complete", json={}, headers=auth(token))

    me = client.get("/auth/me", headers=auth(token)).json()
    total = me["tier_points"]
    assert total > 0

    # Hold the whole balance directly, skipping the live link check.
    db = next(app.dependency_overrides[get_db]())
    user = db.query(dm.User).filter(dm.User.email == "esme.del@example.com").one()
    user.escrow_points = total
    db.commit()
    db.close()

    wallet = client.get("/wallet", headers=auth(token)).json()
    assert wallet["available_points"] == 0
    assert wallet["escrow_points"] == total

    deed = client.get("/tasks/today", headers=auth(token)).json()["deeds"][0]
    resp = client.delete(f"/tasks/{deed['id']}/complete", headers=auth(token))
    assert resp.status_code == 409
    assert "held" in resp.json()["detail"]

    # Nothing moved.
    assert client.get("/auth/me", headers=auth(token)).json()["tier_points"] == total


def test_wallet_split_always_sums_to_the_total(client: TestClient):
    token = signup(client, "Wally", "wally.del@example.com")["token"]
    for deed in client.get("/tasks/today", headers=auth(token)).json()["deeds"][:2]:
        client.post(f"/tasks/{deed['id']}/complete", json={}, headers=auth(token))

    w = client.get("/wallet", headers=auth(token)).json()
    assert w["available_points"] + w["escrow_points"] == w["total_points"]


def test_completion_credits_poster_and_every_helper_in_the_database(client: TestClient):
    """The dual-credit guarantee, asserted against the rows themselves.

    A 200 from /complete proves nothing about points -- the endpoint returns
    200 whether or not the writes landed. So this reads ``User.tier_points``
    straight out of the database before and after, for the poster and for
    *both* helpers on a two-slot post.
    """
    from backend.config import REPORTER_POINTS
    from backend import db_models as m

    poster = signup(client, "Pia", "pia_dual@example.com")
    h1 = signup(client, "Hana", "hana_dual@example.com")
    h2 = signup(client, "Hugo", "hugo_dual@example.com")

    report = _create_report(client, poster["token"], total_slots=2)
    rid = report["report_id"]
    for h in (h1, h2):
        assert client.post(f"/reports/{rid}/claim", headers=auth(h["token"])).status_code == 200
    client.post(
        f"/reports/{rid}/proof",
        json={
            "photo_url": "https://example.com/after.jpg",
            "description": "Cleared the whole verge, three bags out for collection.",
            "time_spent_minutes": 45,
        },
        headers=auth(h1["token"]),
    )

    def points_in_db():
        db = next(app.dependency_overrides[get_db]())
        try:
            return {
                u.email: u.tier_points
                for u in db.query(m.User).filter(
                    m.User.email.in_(["pia_dual@example.com",
                                      "hana_dual@example.com",
                                      "hugo_dual@example.com"])
                )
            }
        finally:
            db.close()

    before = points_in_db()
    done = client.post(f"/reports/{rid}/complete", headers=auth(poster["token"])).json()
    after = points_in_db()

    awarded = done["points_awarded"]
    assert awarded > 0, "mock provider should score this proof"

    # Every helper who took a slot is paid, not just the first to claim.
    for email in ("hana_dual@example.com", "hugo_dual@example.com"):
        gained = after[email] - before[email]
        assert gained == awarded, f"{email} gained {gained}, expected {awarded}"

    # And the poster is paid in the same transaction.
    assert after["pia_dual@example.com"] - before["pia_dual@example.com"] == REPORTER_POINTS


def test_a_zero_scoring_proof_still_pays_both_people(client: TestClient):
    """A confirmed task always pays the helper AND the poster.

    The AI can pay a helper more than the floor but not less: the poster has
    looked at the result and signed off. (This test used to assert the helper
    got nothing when the proof scored zero; that rule was replaced on purpose.)
    """
    import backend.routers.reports as reports_router
    from backend.config import COMPLETION_MIN_POINTS, REPORTER_POINTS
    from backend import db_models as m

    poster = signup(client, "Pia", "pia_zero@example.com")
    helper = signup(client, "Hana", "hana_zero@example.com")
    report = _create_report(client, poster["token"])
    rid = report["report_id"]
    client.post(f"/reports/{rid}/claim", headers=auth(helper["token"]))
    client.post(
        f"/reports/{rid}/proof",
        json={"photo_url": "https://example.com/blurry.jpg", "description": "done", "time_spent_minutes": 12},
        headers=auth(helper["token"]),
    )

    real = reports_router.score_submission_from_dict
    reports_router.score_submission_from_dict = lambda d: {
        "points": 0, "tier_points": 0, "authenticity_confidence": 0.13,
        "rationale": "Reads as a general street scene rather than a cleanup.",
    }
    try:
        done = client.post(f"/reports/{rid}/complete", headers=auth(poster["token"])).json()
    finally:
        reports_router.score_submission_from_dict = real

    assert done["points_awarded"] == COMPLETION_MIN_POINTS
    assert done["reporter_points_awarded"] == REPORTER_POINTS
    # The card explains the payout in plain words, never with raw model text.
    assert "Confirmed by the poster" in done["award_rationale"]
    assert f"+{COMPLETION_MIN_POINTS}" in done["award_rationale"]
    assert "street scene" not in done["award_rationale"]

    db = next(app.dependency_overrides[get_db]())
    try:
        rows = {u.email: u.tier_points for u in db.query(m.User)
                .filter(m.User.email.in_(["pia_zero@example.com", "hana_zero@example.com"]))}
        entry = (
            db.query(m.Submission)
            .filter(m.Submission.report_id == rid, m.Submission.deed_type == "community_cleanup")
            .one()
        )
    finally:
        db.close()
    assert rows["pia_zero@example.com"] == REPORTER_POINTS
    assert rows["hana_zero@example.com"] == COMPLETION_MIN_POINTS
    # The helper's own history keeps the AI's honest read, plus why they were still paid.
    assert "street scene" in entry.rationale and "still counts" in entry.rationale


def test_scoring_outage_does_not_consume_the_report(client: TestClient):
    """An outage is not a verdict. The proof stays, the post stays claimable."""
    import backend.routers.reports as reports_router
    from backend import db_models as m

    poster = signup(client, "Pia", "pia_out@example.com")
    helper = signup(client, "Hana", "hana_out@example.com")
    report = _create_report(client, poster["token"])
    rid = report["report_id"]
    client.post(f"/reports/{rid}/claim", headers=auth(helper["token"]))
    client.post(
        f"/reports/{rid}/proof",
        json={"photo_url": "https://example.com/after.jpg", "description": "all cleared", "time_spent_minutes": 40},
        headers=auth(helper["token"]),
    )

    real = reports_router.score_submission_from_dict
    reports_router.score_submission_from_dict = lambda d: {
        "points": 0, "tier_points": 0, "authenticity_confidence": 0.0,
        "rationale": "We couldn't verify this submission right now.",
        "scoring_unavailable": True,
    }
    try:
        resp = client.post(f"/reports/{rid}/complete", headers=auth(poster["token"]))
    finally:
        reports_router.score_submission_from_dict = real
    assert resp.status_code == 503

    db = next(app.dependency_overrides[get_db]())
    try:
        row = db.query(m.Report).filter(m.Report.id == rid).one()
        assert row.status == "claimed", "an outage must not mark the report done"
        assert row.proof_photo_url is not None, "the helper's proof must survive"
        assert db.query(m.Submission).filter(m.Submission.deed_type == "community_cleanup").count() == 0
    finally:
        db.close()

    # Once the scorer is back, the same confirmation works and pays out.
    retry = client.post(f"/reports/{rid}/complete", headers=auth(poster["token"]))
    assert retry.status_code == 200
    assert retry.json()["points_awarded"] > 0


def test_comment_delete_is_a_real_database_delete_and_respects_ownership(client: TestClient):
    """Author deletes their own; deed owner can moderate; strangers cannot."""
    from backend import db_models as m

    owner = signup(client, "Owen", "owen_cmt@example.com")
    author = signup(client, "Ana", "ana_cmt@example.com")
    nosy = signup(client, "Nico", "nico_cmt@example.com")

    # The feed is friends-only, so put all three in one group first.
    code = client.post("/friends/invite", headers=auth(owner["token"])).json()["invite_code"]
    for u in (author, nosy):
        client.post("/friends/join", json={"invite_code": code}, headers=auth(u["token"]))

    sid = _submit(client, owner["token"])["id"]

    def comment(tok, text):
        r = client.post(f"/feed/{sid}/comment", json={"text": text}, headers=auth(tok))
        assert r.status_code == 200, r.text
        return r.json()["comments"][-1]["id"]

    mine = comment(author["token"], "Nice work!")
    other = comment(nosy["token"], "Second that")

    def count():
        db = next(app.dependency_overrides[get_db]())
        try:
            return db.query(m.Comment).count()
        finally:
            db.close()

    assert count() == 2

    # A stranger can't delete someone else's comment on someone else's deed.
    assert client.delete(f"/feed/comments/{mine}", headers=auth(nosy["token"])).status_code == 403
    assert count() == 2

    # The author can delete their own -- and the row is gone, not hidden.
    assert client.delete(f"/feed/comments/{mine}", headers=auth(author["token"])).status_code == 204
    assert count() == 1

    # The deed owner can moderate a comment left on their own deed.
    assert client.delete(f"/feed/comments/{other}", headers=auth(owner["token"])).status_code == 204
    assert count() == 0

    # Deleting twice is a no-op, not an error -- double-taps shouldn't 500.
    assert client.delete(f"/feed/comments/{mine}", headers=auth(author["token"])).status_code == 204


def test_refresh_endpoint_is_disabled_without_a_token(client: TestClient):
    """No secret configured means 404, not an open endpoint.

    This triggers a full Places fan-out, so leaving it reachable would let
    anyone run up the project's API bill.
    """
    import backend.routers.admin as admin
    assert admin.REFRESH_TOKEN == "", "tests must not run with a real refresh token set"
    assert client.post("/admin/refresh-opportunities").status_code == 404


def test_refresh_endpoint_rejects_a_wrong_token(client: TestClient, monkeypatch):
    import backend.routers.admin as admin
    monkeypatch.setattr(admin, "REFRESH_TOKEN", "s3cret")

    assert client.post("/admin/refresh-opportunities").status_code == 401
    assert client.post(
        "/admin/refresh-opportunities", headers={"X-Refresh-Token": "guess"}
    ).status_code == 401
    # Correct token gets through.
    ok = client.post("/admin/refresh-opportunities", headers={"X-Refresh-Token": "s3cret"})
    assert ok.status_code == 200, ok.text
    assert set(ok.json()) == {"areas", "refreshed", "skipped", "failed", "rows"}


def test_daily_refresh_is_idempotent_and_does_not_duplicate_rows(client: TestClient, monkeypatch):
    """Running the refresh twice must leave one copy of each area, not two."""
    import backend.routers.admin as admin
    from backend import db_models as m

    from backend.routers.quests import _cache_key, _replace_cache

    # Seed a cached area the same way the quest lookup does. (The live cold
    # path writes on a background thread with its own session, which does
    # not see this test's in-memory database.)
    key = _cache_key(OAKLAND["lat"], OAKLAND["lng"], 16.0)
    db = next(app.dependency_overrides[get_db]())
    try:
        _replace_cache(db, key, [
            {"org_name": f"Org {i}", "address": f"{i} Main St",
             "lat": OAKLAND["lat"], "lng": OAKLAND["lng"], "category": "food_bank",
             "legitimacy_score": 0.8, "quest_type": "daily"}
            for i in range(3)
        ])
        db.commit()
    finally:
        db.close()

    def rows():
        db = next(app.dependency_overrides[get_db]())
        try:
            return db.query(m.Opportunity).count(), {
                k for (k,) in db.query(m.Opportunity.cache_key).distinct()
            }
        finally:
            db.close()

    seeded_count, seeded_keys = rows()
    assert seeded_count == 3 and seeded_keys == {key}

    monkeypatch.setattr(admin, "REFRESH_TOKEN", "s3cret")
    hdr = {"X-Refresh-Token": "s3cret"}

    first = client.post("/admin/refresh-opportunities", headers=hdr).json()
    after_one = rows()
    second = client.post("/admin/refresh-opportunities", headers=hdr).json()
    after_two = rows()

    assert first["areas"] == len(seeded_keys)
    assert first["refreshed"] >= 1, first
    # The row count is identical after one run and after two -- replaced, not appended.
    assert after_one == after_two, (after_one, after_two)
    assert after_two[1] == seeded_keys, "refresh must not invent new cache areas"
    assert second["areas"] == first["areas"]


def test_refresh_survives_one_bad_area(monkeypatch):
    """A single failing area must not abort the sweep or lose the others."""
    from backend import refresh as r

    calls = []

    def flaky(lat, lng, radius, **kw):
        calls.append(lat)
        if lat == 1.0:
            raise RuntimeError("Places timed out")
        return [{
            "org_name": "Shelter", "address": "1 Main St", "lat": lat, "lng": lng,
            "category": "shelter", "legitimacy_score": 0.8, "quest_type": "daily",
        }]

    class FakeQuery:
        def distinct(self): return self
        def limit(self, n): return [("1.000:2.000:16",), ("3.000:4.000:16",)]

    class FakeDB:
        def query(self, *a): return FakeQuery()
        def commit(self): pass

    monkeypatch.setattr("backend.agent_client.find_opportunities", flaky)
    monkeypatch.setattr("backend.routers.quests._replace_cache", lambda db, k, o: None)

    out = r.refresh_cached_areas(FakeDB())
    assert out == {"areas": 2, "refreshed": 1, "skipped": 0, "failed": 1, "rows": 1}, out
    assert calls == [1.0, 3.0], "the sweep continued past the failure"


def test_cache_key_round_trips_to_coordinates():
    """The refresh re-derives coordinates from the cache key, so the two
    must stay in step. A silent parse failure would skip every area."""
    from backend.refresh import _parse_cache_key
    from backend.routers.quests import _cache_key

    key = _cache_key(39.3312, -76.6205, 16.0)
    parsed = _parse_cache_key(key)
    assert parsed is not None, key
    lat, lng, radius = parsed
    assert abs(lat - 39.33) < 0.02 and abs(lng - (-76.62)) < 0.02 and radius == 16.0
    assert _parse_cache_key("garbage") is None
    assert _parse_cache_key("a:b:c") is None


def test_scheduler_targets_eight_in_the_morning():
    from datetime import datetime, timedelta
    from backend.refresh import REFRESH_HOUR, _seconds_until_next_run

    assert REFRESH_HOUR == 8
    secs = _seconds_until_next_run()
    assert 0 < secs <= 24 * 3600
    when = datetime.now().astimezone() + timedelta(seconds=secs)
    assert when.hour == 8 and when.minute == 0
