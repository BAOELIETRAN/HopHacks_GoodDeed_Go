"""Completing a community task credits both people, and no placeholder text leaks.

Reuses the backend test app and helpers (in-memory database, mock agent).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import backend.routers.reports as reports_router
from backend import db_models as m
from backend.config import COMPLETION_MIN_POINTS, REPORTER_POINTS
from backend.database import get_db
from backend.main import app

# Fixture and helpers live in test_backend; importing the fixture registers it here too.
from test_backend import OAKLAND, _create_report, _submit, auth, client, signup  # noqa: F401


def _db():
    return next(app.dependency_overrides[get_db]())


def _finish_report(client, poster, helpers, *, slots=1, scorer=None):
    """Post -> claim -> proof -> confirm. Returns (report_id, completion payload)."""
    report = _create_report(client, poster["token"], total_slots=slots)
    rid = report["report_id"]
    for h in helpers:
        assert client.post(f"/reports/{rid}/claim", headers=auth(h["token"])).status_code == 200
    client.post(
        f"/reports/{rid}/proof",
        json={
            "photo_url": "https://example.com/after.jpg",
            "description": "Cleared the whole verge, three bags out for collection.",
            "time_spent_minutes": 45,
        },
        headers=auth(helpers[0]["token"]),
    )
    real = reports_router.score_submission_from_dict
    if scorer:
        reports_router.score_submission_from_dict = scorer
    try:
        done = client.post(f"/reports/{rid}/complete", headers=auth(poster["token"]))
    finally:
        reports_router.score_submission_from_dict = real
    assert done.status_code == 200, done.text
    return rid, done.json()


def _team(client, *people):
    """One friend group, so the friends leaderboard shows everyone."""
    code = client.post("/friends/invite", headers=auth(people[0]["token"])).json()["invite_code"]
    for person in people[1:]:
        client.post("/friends/join", json={"invite_code": code}, headers=auth(person["token"]))


def _me(client, who):
    return client.get("/auth/me", headers=auth(who["token"])).json()


# --- both people are credited ------------------------------------------------


def test_credit_is_visible_to_both_people_everywhere_it_should_be(client: TestClient):
    """Not just a number in the database: the leaderboard and each person's own
    history must show it, or it looks like nothing happened."""
    poster = signup(client, "Pia", "pia_vis@example.com")
    helper = signup(client, "Hana", "hana_vis@example.com")
    _team(client, poster, helper)
    rid, done = _finish_report(client, poster, [helper])

    helper_pts, poster_pts = done["points_awarded"], done["reporter_points_awarded"]
    assert helper_pts > 0
    assert poster_pts == REPORTER_POINTS

    assert _me(client, helper)["tier_points"] == helper_pts
    assert _me(client, poster)["tier_points"] == poster_pts

    # The poster used to be missing from the leaderboard entirely: it counts scored entries.
    board = client.get(
        "/leaderboard", params={"scope": "friends", "period": "weekly"}, headers=auth(poster["token"])
    ).json()
    by_name = {r["name"]: r for r in board}
    assert by_name["Hana"]["points"] == helper_pts
    assert by_name["Pia"]["points"] == poster_pts
    assert by_name["Pia"]["deed_count"] == 1

    poster_history = client.get("/submissions/mine", headers=auth(poster["token"])).json()
    assert [(e["deed_type"], e["points"]) for e in poster_history] == [("community_report", poster_pts)]
    helper_history = client.get("/submissions/mine", headers=auth(helper["token"])).json()
    assert [(e["deed_type"], e["points"]) for e in helper_history] == [("community_cleanup", helper_pts)]

    # The finished card tells each viewer what was paid.
    for who in (poster, helper):
        card = client.get(f"/reports/{rid}", headers=auth(who["token"])).json()
        assert card["status"] == "done"
        assert card["points_awarded"] == helper_pts
        assert card["reporter_points_awarded"] == poster_pts


def test_every_helper_and_the_poster_are_each_credited_exactly_once(client: TestClient):
    poster = signup(client, "Pia", "pia_multi@example.com")
    h1 = signup(client, "Hana", "hana_multi@example.com")
    h2 = signup(client, "Hugo", "hugo_multi@example.com")
    _team(client, poster, h1, h2)
    rid, done = _finish_report(client, poster, [h1, h2], slots=2)

    for helper in (h1, h2):
        me = _me(client, helper)
        assert me["tier_points"] == done["points_awarded"]
        assert me["current_streak"] == 1
    poster_me = _me(client, poster)
    assert poster_me["tier_points"] == REPORTER_POINTS  # once, however many helpers
    assert poster_me["current_streak"] == 1
    assert "Each helper earned" in done["award_rationale"]

    # Confirming twice cannot pay twice.
    assert client.post(f"/reports/{rid}/complete", headers=auth(poster["token"])).status_code == 409
    assert _me(client, poster)["tier_points"] == REPORTER_POINTS


def test_the_ai_can_pay_a_helper_more_than_the_floor(client: TestClient):
    poster = signup(client, "Pia", "pia_more@example.com")
    helper = signup(client, "Hana", "hana_more@example.com")

    def strong(_):
        return {
            "points": 42, "tier_points": 42, "authenticity_confidence": 0.95,
            "rationale": "Clear before and after of bagged litter.",
        }

    _, done = _finish_report(client, poster, [helper], scorer=strong)
    assert done["points_awarded"] == 42 > COMPLETION_MIN_POINTS
    entry = client.get("/submissions/mine", headers=auth(helper["token"])).json()[0]
    assert entry["rationale"] == "Clear before and after of bagged litter."  # not floored, so no extra note


@pytest.mark.parametrize("ai_points", [0, 3, COMPLETION_MIN_POINTS - 1])
def test_a_low_ai_score_is_lifted_to_the_floor_not_below_it(client: TestClient, ai_points):
    poster = signup(client, "Pia", f"pia_low{ai_points}@example.com")
    helper = signup(client, "Hana", f"hana_low{ai_points}@example.com")

    def weak(_):
        return {
            "points": ai_points, "tier_points": ai_points, "authenticity_confidence": 0.2,
            "rationale": "Hard to tell from this photo.",
        }

    _, done = _finish_report(client, poster, [helper], scorer=weak)
    assert done["points_awarded"] == COMPLETION_MIN_POINTS
    assert _me(client, helper)["tier_points"] == COMPLETION_MIN_POINTS
    assert _me(client, helper)["current_streak"] == 1  # completing counts toward the streak even when scored low


def test_a_scoring_outage_credits_nobody_and_leaves_the_task_confirmable(client: TestClient):
    """An outage is not a verdict: nothing is paid and nothing is consumed."""
    poster = signup(client, "Pia", "pia_out2@example.com")
    helper = signup(client, "Hana", "hana_out2@example.com")
    report = _create_report(client, poster["token"])
    rid = report["report_id"]
    client.post(f"/reports/{rid}/claim", headers=auth(helper["token"]))
    client.post(
        f"/reports/{rid}/proof",
        json={"photo_url": "https://example.com/a.jpg", "description": "Done, bags collected.", "time_spent_minutes": 20},
        headers=auth(helper["token"]),
    )
    real = reports_router.score_submission_from_dict
    reports_router.score_submission_from_dict = lambda d: {"points": 0, "tier_points": 0, "scoring_unavailable": True}
    try:
        resp = client.post(f"/reports/{rid}/complete", headers=auth(poster["token"]))
    finally:
        reports_router.score_submission_from_dict = real

    assert resp.status_code == 503
    assert _me(client, poster)["tier_points"] == 0
    assert _me(client, helper)["tier_points"] == 0
    assert client.post(f"/reports/{rid}/complete", headers=auth(poster["token"])).status_code == 200


def test_deleting_a_confirmed_post_takes_back_only_the_posters_credit(client: TestClient):
    poster = signup(client, "Pia", "pia_del@example.com")
    helper = signup(client, "Hana", "hana_del@example.com")
    _team(client, poster, helper)
    rid, done = _finish_report(client, poster, [helper])
    assert _me(client, poster)["tier_points"] == REPORTER_POINTS

    assert client.delete(f"/reports/{rid}", headers=auth(poster["token"])).status_code == 204

    # The poster's balance and their leaderboard/history entry go together...
    assert _me(client, poster)["tier_points"] == 0
    assert client.get("/submissions/mine", headers=auth(poster["token"])).json() == []
    board = client.get(
        "/leaderboard", params={"scope": "friends", "period": "weekly"}, headers=auth(poster["token"])
    ).json()
    assert {r["name"]: r["points"] for r in board}["Pia"] == 0
    # ...while the helper keeps what they earned: they did the work.
    assert _me(client, helper)["tier_points"] == done["points_awarded"]
    assert len(client.get("/submissions/mine", headers=auth(helper["token"])).json()) == 1


def test_a_post_confirmed_before_payouts_were_recorded_still_reports_the_posters_award(client: TestClient):
    """Older rows have reporter_points = NULL, but did pay the poster REPORTER_POINTS."""
    poster = signup(client, "Pia", "pia_old@example.com")
    helper = signup(client, "Hana", "hana_old@example.com")
    rid, _ = _finish_report(client, poster, [helper])

    db = _db()
    try:
        db.get(m.Report, rid).reporter_points = None
        db.commit()
    finally:
        db.close()
    card = client.get(f"/reports/{rid}", headers=auth(poster["token"])).json()
    assert card["reporter_points_awarded"] == REPORTER_POINTS

    # ...and deleting such a post still returns exactly what was paid.
    assert client.delete(f"/reports/{rid}", headers=auth(poster["token"])).status_code == 204
    assert _me(client, poster)["tier_points"] == 0


# --- placeholder text never reaches a user -------------------------------------


def _all_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _all_strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _all_strings(v)


def test_no_response_across_a_full_lifecycle_contains_placeholder_text(client: TestClient):
    poster = signup(client, "Pia", "pia_txt@example.com")
    helper = signup(client, "Hana", "hana_txt@example.com")
    _team(client, poster, helper)
    client.get("/quests", params={**OAKLAND, "radius": 5}, headers=auth(poster["token"]))

    seen = [_submit(client, poster["token"])]
    rid, done = _finish_report(client, poster, [helper])
    seen.append(done)
    for who in (poster, helper):
        h = auth(who["token"])
        seen.append(client.get("/submissions/mine", headers=h).json())
        seen.append(client.get("/reports", params={**OAKLAND, "radius": 20}, headers=h).json())
        seen.append(client.get("/reports", params={**OAKLAND, "radius": 20, "status": "done"}, headers=h).json())

    leaked = [t for payload in seen for t in _all_strings(payload) if "[mock]" in t.lower() or "MockLLMProvider" in t]
    assert leaked == []


def test_placeholder_text_already_stored_in_the_database_is_hidden_on_the_way_out(client: TestClient):
    """Rows written while the app ran with no API key still hold the old "[mock]" label."""
    poster = signup(client, "Pia", "pia_legacy@example.com")
    helper = signup(client, "Hana", "hana_legacy@example.com")
    rid, _ = _finish_report(client, poster, [helper])
    legacy = "[mock] Plausible 'rationale' generated by MockLLMProvider (no API key set)."

    db = _db()
    try:
        db.get(m.Report, rid).award_rationale = legacy
        for sub in db.query(m.Submission).all():
            sub.rationale = legacy
        db.commit()
    finally:
        db.close()

    card = client.get(f"/reports/{rid}", headers=auth(poster["token"])).json()
    assert card["award_rationale"] is None  # the card simply shows no note
    for who in (poster, helper):
        for entry in client.get("/submissions/mine", headers=auth(who["token"])).json():
            assert entry["rationale"] == "Reviewed automatically."


# --- the new columns reach databases that already exist ---------------------------


def test_migration_adds_the_credit_columns_to_an_existing_database(tmp_path):
    """Production is Postgres with tables that predate these columns. create_all never
    alters existing tables, so without ensure_schema the first query would 500."""
    from sqlalchemy import create_engine, inspect, text

    from backend.migrate import ensure_schema

    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE reports (id VARCHAR(32) PRIMARY KEY, points_awarded INTEGER)"))
        conn.execute(text("CREATE TABLE submissions (id VARCHAR(32) PRIMARY KEY, user_id VARCHAR(32))"))
        conn.execute(text("INSERT INTO reports (id, points_awarded) VALUES ('r1', 7)"))

    ensure_schema(engine)
    ensure_schema(engine)  # idempotent: safe on every startup

    def cols(table):
        return {c["name"] for c in inspect(engine).get_columns(table)}

    assert "reporter_points" in cols("reports")
    assert "report_id" in cols("submissions")
    with engine.connect() as conn:  # existing data survives; new columns start NULL
        row = conn.execute(text("SELECT points_awarded, reporter_points FROM reports WHERE id = 'r1'")).one()
    assert tuple(row) == (7, None)
    engine.dispose()
