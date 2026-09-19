"""The points store: coins, purchases, eggs and the portfolio.

The rules worth protecting here are the ones that would be embarrassing to
get wrong in front of a user: being charged twice, a tier dropping because
someone bought a hat, an egg that opens early, or an egg that can be opened
again for a second animal.
"""

from __future__ import annotations

import os

os.environ["GOODDEED_USE_MOCKS"] = "1"

import itertools
import random

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend import store
from backend.database import Base, get_db
from backend.main import app


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
        c.db = TestingSession          # type: ignore[attr-defined]
        yield c
    app.dependency_overrides.clear()


def signup(client: TestClient, name="Maya", email="maya@example.com") -> dict:
    resp = client.post(
        "/auth/signup", json={"name": name, "email": email, "password": "hunter22"}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


_seed = itertools.count()


def grant(client: TestClient, email: str, coins: int, deeds: int = 0) -> None:
    """Put coins (and optionally completed deeds) on an account directly.

    Faster and steadier than driving the scoring pipeline for every test,
    and this suite is about the store, not about how points are earned.
    Deed ids come from a global counter because micro-deeds are unique per
    (user, deed, day) and several tests grant deeds more than once.
    """
    from backend import db_models as m

    db = client.db()  # type: ignore[attr-defined]
    try:
        user = db.query(m.User).filter(m.User.email == email).first()
        user.coins = coins
        user.tier_points = max(user.tier_points or 0, coins)
        for _ in range(deeds):
            n = next(_seed)
            db.add(
                m.MicroDeedDone(
                    user_id=user.id, deed_id=f"seed_{n}", day="2026-01-01", points=1
                )
            )
        db.commit()
    finally:
        db.close()


# --- catalog ---------------------------------------------------------------


def test_catalog_lists_avatars_and_eggs_with_affordability(client: TestClient):
    token = signup(client)["token"]
    grant(client, "maya@example.com", 200)

    body = client.get("/store", headers=auth(token)).json()
    assert body["coins"] == 200
    assert len(body["avatars"]) == len(store.AVATARS)
    assert len(body["eggs"]) == len(store.EGGS)

    cheap = next(a for a in body["avatars"] if a["code"] == "av_sprout")   # 60
    dear = next(a for a in body["avatars"] if a["code"] == "av_crown")     # 1200
    assert cheap["affordable"] is True
    assert dear["affordable"] is False
    assert cheap["owned"] is False


def test_egg_odds_are_published_as_percentages(client: TestClient):
    token = signup(client)["token"]
    body = client.get("/store", headers=auth(token)).json()

    gilded = next(e for e in body["eggs"] if e["code"] == "egg_gilded")
    assert sum(o["pct"] for o in gilded["odds_pct"]) == pytest.approx(100.0, abs=0.2)
    # A drop table nobody can read is not a drop table.
    assert {o["key"] for o in gilded["odds_pct"]} == {"common", "uncommon", "rare", "legendary"}


# --- buying ----------------------------------------------------------------


def test_buying_an_avatar_spends_coins_but_never_tier_points(client: TestClient):
    signed = signup(client)
    token = signed["token"]
    grant(client, "maya@example.com", 500)

    before = client.get("/auth/me", headers=auth(token)).json()
    assert before["coins"] == 500
    tier_points_before = before["tier_points"]
    tier_before = before["tier"]

    resp = client.post("/store/buy", json={"code": "av_sun"}, headers=auth(token))  # 120
    assert resp.status_code == 200, resp.text
    assert resp.json()["label"] == "Sun Hat"

    after = client.get("/auth/me", headers=auth(token)).json()
    assert after["coins"] == 380
    # The whole reason coins exist: shopping must not rewrite the record.
    assert after["tier_points"] == tier_points_before
    assert after["tier"] == tier_before


def test_cannot_afford_is_refused_with_the_balance_in_the_message(client: TestClient):
    token = signup(client)["token"]
    grant(client, "maya@example.com", 10)

    resp = client.post("/store/buy", json={"code": "av_crown"}, headers=auth(token))
    assert resp.status_code == 400
    assert "1200" in resp.json()["detail"] and "10" in resp.json()["detail"]

    assert client.get("/auth/me", headers=auth(token)).json()["coins"] == 10


def test_avatar_cannot_be_bought_twice(client: TestClient):
    token = signup(client)["token"]
    grant(client, "maya@example.com", 500)

    assert client.post("/store/buy", json={"code": "av_sun"}, headers=auth(token)).status_code == 200
    resp = client.post("/store/buy", json={"code": "av_sun"}, headers=auth(token))
    assert resp.status_code == 409

    # Charged once, not twice.
    assert client.get("/auth/me", headers=auth(token)).json()["coins"] == 380


def test_unknown_item_is_a_404_and_costs_nothing(client: TestClient):
    token = signup(client)["token"]
    grant(client, "maya@example.com", 500)

    assert client.post("/store/buy", json={"code": "av_nope"}, headers=auth(token)).status_code == 404
    assert client.get("/auth/me", headers=auth(token)).json()["coins"] == 500


def test_eggs_are_consumable_so_several_can_be_owned(client: TestClient):
    token = signup(client)["token"]
    grant(client, "maya@example.com", 500)

    for _ in range(3):
        assert client.post("/store/buy", json={"code": "egg_mossy"}, headers=auth(token)).status_code == 200

    portfolio = client.get("/store/portfolio", headers=auth(token)).json()
    assert len([i for i in portfolio["items"] if i["kind"] == "egg"]) == 3
    assert portfolio["coins"] == 500 - 3 * 150


# --- hatching --------------------------------------------------------------


def test_egg_will_not_hatch_before_its_deeds_are_done(client: TestClient):
    token = signup(client)["token"]
    grant(client, "maya@example.com", 500)

    egg = client.post("/store/buy", json={"code": "egg_mossy"}, headers=auth(token)).json()
    assert egg["state"] == "incubating"
    assert egg["needed"] == 2 and egg["progress"] == 0 and egg["ready"] is False

    resp = client.post(f"/store/eggs/{egg['id']}/hatch", headers=auth(token))
    assert resp.status_code == 400
    assert "2 more deed" in resp.json()["detail"]


def test_deeds_after_purchase_hatch_the_egg(client: TestClient):
    token = signup(client)["token"]
    grant(client, "maya@example.com", 500, deeds=5)   # deeds BEFORE the egg

    egg = client.post("/store/buy", json={"code": "egg_mossy"}, headers=auth(token)).json()
    # Pre-existing deeds must not count -- the requirement is "two more".
    assert egg["progress"] == 0

    resp = client.post(f"/store/eggs/{egg['id']}/hatch", headers=auth(token))
    assert resp.status_code == 400

    grant(client, "maya@example.com", 350, deeds=2)   # two more deeds
    portfolio = client.get("/store/portfolio", headers=auth(token)).json()
    pending = next(i for i in portfolio["items"] if i["id"] == egg["id"])
    assert pending["progress"] == 2 and pending["ready"] is True

    resp = client.post(f"/store/eggs/{egg['id']}/hatch", headers=auth(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["item"]["state"] == "hatched"
    assert body["rarity"] in store.RARITY_ORDER
    assert body["is_new_species"] is True
    assert body["item"]["code"] == "egg_mossy"          # the purchase is still identifiable
    assert store.animal(body["item"]["species_code"])   # and the species is its own field
    assert body["item"]["emoji"]                        # shows the animal, not the egg


def test_an_egg_cannot_be_hatched_twice(client: TestClient):
    token = signup(client)["token"]
    grant(client, "maya@example.com", 500, deeds=0)

    egg = client.post("/store/buy", json={"code": "egg_mossy"}, headers=auth(token)).json()
    grant(client, "maya@example.com", 350, deeds=2)

    first = client.post(f"/store/eggs/{egg['id']}/hatch", headers=auth(token))
    assert first.status_code == 200
    species = first.json()["item"]["label"]

    again = client.post(f"/store/eggs/{egg['id']}/hatch", headers=auth(token))
    assert again.status_code == 409

    # And it still shows the same animal it first became.
    portfolio = client.get("/store/portfolio", headers=auth(token)).json()
    hatched = next(i for i in portfolio["items"] if i["id"] == egg["id"])
    assert hatched["label"] == species


def test_cannot_hatch_someone_elses_egg(client: TestClient):
    mine = signup(client, "Maya", "maya@example.com")["token"]
    theirs = signup(client, "Sam", "sam@example.com")["token"]
    grant(client, "maya@example.com", 500, deeds=5)

    egg = client.post("/store/buy", json={"code": "egg_mossy"}, headers=auth(mine)).json()
    resp = client.post(f"/store/eggs/{egg['id']}/hatch", headers=auth(theirs))
    assert resp.status_code == 404


# --- equipping -------------------------------------------------------------


def test_equip_requires_ownership(client: TestClient):
    token = signup(client)["token"]
    grant(client, "maya@example.com", 500)

    denied = client.post("/store/equip", json={"code": "av_crown"}, headers=auth(token))
    assert denied.status_code == 403

    client.post("/store/buy", json={"code": "av_sun"}, headers=auth(token))
    ok = client.post("/store/equip", json={"code": "av_sun"}, headers=auth(token))
    assert ok.status_code == 200
    assert ok.json()["equipped_avatar"] == "av_sun"
    assert client.get("/auth/me", headers=auth(token)).json()["equipped_avatar"] == "av_sun"

    cleared = client.post("/store/equip", json={"code": None}, headers=auth(token))
    assert cleared.json()["equipped_avatar"] is None


# --- portfolio -------------------------------------------------------------


def test_portfolio_counts_distinct_species_not_eggs(client: TestClient):
    token = signup(client)["token"]
    grant(client, "maya@example.com", 2000, deeds=0)

    empty = client.get("/store/portfolio", headers=auth(token)).json()
    assert empty["animals_collected"] == 0
    assert empty["animals_total"] == sum(len(p) for p in store.ANIMALS.values())

    eggs = [
        client.post("/store/buy", json={"code": "egg_mossy"}, headers=auth(token)).json()
        for _ in range(2)
    ]
    grant(client, "maya@example.com", 1700, deeds=2)
    for egg in eggs:
        client.post(f"/store/eggs/{egg['id']}/hatch", headers=auth(token))

    full = client.get("/store/portfolio", headers=auth(token)).json()
    hatched = [i for i in full["items"] if i["state"] == "hatched"]
    assert len(hatched) == 2
    # Two eggs can roll the same species; the collection counts uniques.
    assert full["animals_collected"] == len({i["species_code"] for i in hatched})


# --- earning ---------------------------------------------------------------


def test_everyday_deeds_credit_coins_and_points_together(client: TestClient):
    token = signup(client)["token"]

    tasks = client.get("/tasks/today", headers=auth(token)).json()
    deed = tasks["deeds"][0]
    resp = client.post(f"/tasks/{deed['id']}/complete", json={}, headers=auth(token))
    assert resp.status_code == 200, resp.text

    me = client.get("/auth/me", headers=auth(token)).json()
    assert me["coins"] == me["tier_points"] > 0


def test_deleting_a_deed_takes_its_coins_back(client: TestClient):
    token = signup(client)["token"]

    tasks = client.get("/tasks/today", headers=auth(token)).json()
    deed = tasks["deeds"][0]
    client.post(f"/tasks/{deed['id']}/complete", json={}, headers=auth(token))
    earned = client.get("/auth/me", headers=auth(token)).json()["coins"]
    assert earned > 0

    client.delete(f"/tasks/{deed['id']}/complete", headers=auth(token))
    assert client.get("/auth/me", headers=auth(token)).json()["coins"] == 0


# --- rolling (pure) --------------------------------------------------------


def test_roll_respects_zero_weight_rarities():
    # A mossy egg can never produce a legendary.
    rng = random.Random(0)
    rolls = {store.roll_animal("egg_mossy", rng=rng)["rarity"] for _ in range(400)}
    assert "legendary" not in rolls


def test_roll_returns_an_animal_from_the_rolled_rarity():
    rng = random.Random(7)
    for _ in range(200):
        got = store.roll_animal("egg_gilded", rng=rng)
        pool = {a["code"] for a in store.ANIMALS[got["rarity"]]}
        assert got["code"] in pool


def test_every_catalog_code_is_unique():
    codes = [a["code"] for a in store.AVATARS] + [e["code"] for e in store.EGGS]
    assert len(codes) == len(set(codes))
    animals = [a["code"] for pool in store.ANIMALS.values() for a in pool]
    assert len(animals) == len(set(animals))
