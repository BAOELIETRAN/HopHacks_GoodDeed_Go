"""The demo seed: complete, consistent, idempotent, and safe for real accounts.

These run against a throwaway SQLite database with foreign keys switched ON, because
Postgres (Supabase) enforces them and SQLite does not by default. Passing here means the
wipe order and the inserts hold up against the real database's constraints.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, func
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from backend import db_models as m  # noqa: E402
from backend.database import Base  # noqa: E402
from backend.security import verify_password  # noqa: E402

import seed_demo  # noqa: E402
import verify_demo  # noqa: E402
import wipe_demo  # noqa: E402

quiet = lambda *_a, **_k: None  # noqa: E731


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'seed.db'}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _fk_on(conn, _rec):
        conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    yield session
    session.close()
    engine.dispose()


def _counts(db) -> dict[str, int]:
    return {
        model.__tablename__: db.query(model).count()
        for model in (m.User, m.Submission, m.Report, m.ReportHelper, m.Campaign, m.PointsTransaction,
                      m.MicroDeedDone, m.Reaction, m.Comment, m.OwnedItem, m.CheckIn, m.FriendGroup)
    }


def test_seed_builds_a_consistent_demo(db):
    seed_demo.seed(db, log=quiet)

    users = wipe_demo.demo_users(db)
    assert len(users) == 14
    tiers = sorted(u.tier for u in users)
    assert tiers.count("Gold") == 2 and tiers.count("Silver") == 5 and tiers.count("Bronze") == 7
    # Every check that matters for the demo, in one place.
    assert verify_demo.invariant_failures(db) == []


def test_every_seeded_account_can_log_in(db):
    seed_demo.seed(db, log=quiet)
    for user in wipe_demo.demo_users(db):
        assert verify_password(seed_demo.PASSWORD, user.password_hash, user.password_salt), user.email


def test_reseeding_is_idempotent(db):
    seed_demo.seed(db, log=quiet)
    first = _counts(db)
    seed_demo.seed(db, log=quiet)
    second = _counts(db)

    assert first == second
    emails = [e for (e,) in db.query(m.User.email)]
    assert len(emails) == len(set(emails)) == 14
    assert verify_demo.invariant_failures(db) == []


def test_dates_are_spread_and_streaks_are_real(db):
    seed_demo.seed(db, log=quiet)
    by_email = {u.email: u for u in wipe_demo.demo_users(db)}

    assert by_email["lena@demo.dev"].current_streak == 12
    assert by_email["lena@demo.dev"].longest_streak >= 10  # earns the 10-day badge
    assert by_email["newbie@demo.dev"].tier_points == 0

    days = {seed_demo._aware(when).date() for (when,) in db.query(m.Submission.scored_at)}
    assert len(days) >= 8  # not all today


def test_every_report_state_is_present(db):
    seed_demo.seed(db, log=quiet)
    statuses = dict(db.query(m.Report.status, func.count(m.Report.id)).group_by(m.Report.status).all())
    assert statuses["open"] >= 3 and statuses["claimed"] >= 2 and statuses["done"] >= 5
    waiting = db.query(m.Report).filter(m.Report.status == "claimed", m.Report.proof_photo_url.isnot(None)).count()
    assert waiting >= 1


def test_finished_jobs_pay_both_sides_in_scored_entries(db):
    seed_demo.seed(db, log=quiet)
    for report in db.query(m.Report).filter(m.Report.status == "done"):
        poster = db.query(m.Submission).filter(
            m.Submission.report_id == report.id, m.Submission.deed_type == "community_report").one()
        assert poster.user_id == report.reported_by and poster.points == report.reporter_points > 0
        helpers = db.query(m.Submission).filter(
            m.Submission.report_id == report.id, m.Submission.deed_type == "community_cleanup").all()
        assert helpers and all(h.points == report.points_awarded >= 10 for h in helpers)


def test_no_placeholder_text_anywhere(db):
    seed_demo.seed(db, log=quiet)
    rationales = [t for (t,) in db.query(m.Submission.rationale)]
    payout_notes = [t for (t,) in db.query(m.Report.award_rationale).filter(m.Report.status == "done")]
    assert rationales and payout_notes
    assert all(t and "[mock]" not in t.lower() for t in rationales + payout_notes)


def test_real_accounts_survive_and_rejoin_their_team(db):
    seed_demo.seed(db, log=quiet)

    # A real person joins the demo team; someone else has a real deed and a real report.
    team = db.query(m.FriendGroup).filter(m.FriendGroup.invite_code == "HOPHACKS").one()
    real = m.User(name="Real Judge", email="judge@example.com", password_hash="x", password_salt="y",
                  friend_group_id=team.id, tier_points=30, coins=30)
    bystander = m.User(name="Bystander", email="by@example.com", password_hash="x", password_salt="y")
    db.add_all([real, bystander])
    db.flush()
    db.add(m.Submission(user_id=bystander.id, org_name="Somewhere", photo_url="", description="Real deed",
                        time_spent_minutes=30, lat=1, lng=1, submitted_at="2026-01-01T00:00:00+00:00",
                        points=20, tier_points=20, authenticity_confidence=0.9, rationale="ok"))
    # A real person's job that a demo user is helping on.
    lena = db.query(m.User).filter(m.User.email == "lena@demo.dev").one()
    job = m.Report(reported_by=bystander.id, photo_url="", description="A real job", lat=1, lng=1,
                   status="claimed", total_slots=1, filled_slots=1, claimed_by=lena.id,
                   created_at="2026-01-01T00:00:00+00:00", claimed_at="2026-01-01T01:00:00+00:00")
    db.add(job)
    db.flush()
    db.add(m.ReportHelper(report_id=job.id, user_id=lena.id))
    db.commit()

    seed_demo.seed(db, log=quiet)

    assert db.query(m.User).filter(m.User.email == "judge@example.com").count() == 1
    judge = db.query(m.User).filter(m.User.email == "judge@example.com").one()
    new_team = db.query(m.FriendGroup).filter(m.FriendGroup.invite_code == "HOPHACKS").one()
    assert judge.friend_group_id == new_team.id                      # put back on the team
    assert judge.tier_points == 30                                    # untouched
    assert db.query(m.Submission).filter(m.Submission.description == "Real deed").count() == 1
    released = db.get(m.Report, job.id)                               # the demo helper stepped out
    assert released.status == "open" and released.filled_slots == 0 and released.claimed_by is None


def test_wiping_leaves_nothing_pointing_at_a_demo_user(db):
    seed_demo.seed(db, log=quiet)
    wipe_demo.wipe_accounts(db, wipe_demo.demo_users(db))
    db.commit()

    assert _counts(db) == {name: 0 for name in _counts(db)}


def test_wipe_everything_requires_no_survivors(db):
    seed_demo.seed(db, log=quiet)
    wipe_demo.wipe_everything(db)
    db.commit()
    assert _counts(db) == {name: 0 for name in _counts(db)}
