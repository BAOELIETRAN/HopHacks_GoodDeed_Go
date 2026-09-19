"""Read the demo data back out of the database and check it is really there and consistent.

    python scripts/verify_demo.py

Read-only. Everything below is queried fresh from the database that DATABASE_URL points at,
not taken from the seed script's own output, so it is a check on what a judge will actually see:

* /health (which database, and whether the AI and Places providers are real or stubs)
* accounts per tier, deeds per day, reports and campaigns per status, teams
* both sides of every finished community job, with their current totals
* the daily and weekly team leaderboards, as the API computes them
* a ledger audit: every account's points, coins and escrow explained line by line

Exits non-zero if any check fails.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, ".")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sqlalchemy import func  # noqa: E402

from backend import db_models as m  # noqa: E402
from backend.agent_client import tier_for_points  # noqa: E402
from backend.config import CLAIM_EXPIRY_HOURS  # noqa: E402
from seed_demo import PASSWORD, _aware, activity_dates, derive_streaks  # noqa: E402
from wipe_demo import demo_users  # noqa: E402

UTC = timezone.utc
EXPECTED_TIERS = {"Gold": 2, "Silver": 5, "Bronze": 7}


def _heading(title: str) -> None:
    print(f"\n== {title} " + "=" * max(0, 74 - len(title)))


# --------------------------------------------------------------------------- checks

def invariant_failures(db, now: datetime | None = None) -> list[str]:
    """Every way the demo data could be wrong. An empty list means it is sound."""
    now = now or datetime.now(UTC)
    fails: list[str] = []
    users = demo_users(db)
    by_id = {u.id: u for u in users}
    ids = list(by_id)

    if len(users) != 14:
        fails.append(f"expected 14 demo accounts, found {len(users)}")
    tiers = defaultdict(int)
    for u in users:
        tiers[u.tier] += 1
    if dict(tiers) != EXPECTED_TIERS:
        fails.append(f"tier spread is {dict(tiers)}, expected {EXPECTED_TIERS}")

    # Ledger: every point and coin explained by a row.
    sub_sum = dict(db.query(m.Submission.user_id, func.sum(m.Submission.tier_points))
                   .filter(m.Submission.user_id.in_(ids)).group_by(m.Submission.user_id).all())
    micro_sum = dict(db.query(m.MicroDeedDone.user_id, func.sum(m.MicroDeedDone.points))
                     .filter(m.MicroDeedDone.user_id.in_(ids)).group_by(m.MicroDeedDone.user_id).all())
    spent = dict(db.query(m.OwnedItem.user_id, func.sum(m.OwnedItem.price_paid))
                 .filter(m.OwnedItem.user_id.in_(ids)).group_by(m.OwnedItem.user_id).all())
    tx_in: dict[str, int] = defaultdict(int)
    tx_out: dict[str, int] = defaultdict(int)
    for tx in db.query(m.PointsTransaction).filter(m.PointsTransaction.kind == "payout"):
        tx_in[tx.to_user_id] += tx.amount
        tx_out[tx.from_user_id] += tx.amount
    held: dict[str, int] = defaultdict(int)
    for c in db.query(m.Campaign).filter(m.Campaign.poster_id.in_(ids), m.Campaign.status.in_(("open", "claimed"))):
        held[c.poster_id] += c.bounty

    for u in users:
        earned = int(sub_sum.get(u.id) or 0) + int(micro_sum.get(u.id) or 0)
        want_points = earned + tx_in[u.id] - tx_out[u.id]
        want_coins = earned - int(spent.get(u.id) or 0)
        if u.tier_points != want_points:
            fails.append(f"{u.email}: tier_points {u.tier_points} but the ledger adds up to {want_points}")
        if u.coins != want_coins:
            fails.append(f"{u.email}: coins {u.coins} but earned - spent = {want_coins}")
        if (u.escrow_points or 0) != held[u.id]:
            fails.append(f"{u.email}: escrow {u.escrow_points} but open campaigns hold {held[u.id]}")
        if u.tier != tier_for_points(u.tier_points):
            fails.append(f"{u.email}: tier {u.tier} does not match {u.tier_points} points")
        cur, longest, last = derive_streaks(activity_dates(db, u.id))
        if (u.current_streak, u.longest_streak, u.last_active_date) != (cur, longest, last):
            fails.append(f"{u.email}: streak fields {(u.current_streak, u.longest_streak, u.last_active_date)} "
                         f"differ from the activity record {(cur, longest, last)}")

    # Finished community jobs: both sides really were paid, in scored entries.
    done = db.query(m.Report).filter(m.Report.status == "done", m.Report.reported_by.in_(ids)).all()
    if len(done) < 5:
        fails.append(f"only {len(done)} finished community jobs (want at least 5)")
    for r in done:
        poster_rows = db.query(m.Submission).filter(
            m.Submission.report_id == r.id, m.Submission.user_id == r.reported_by,
            m.Submission.deed_type == "community_report").all()
        if len(poster_rows) != 1 or poster_rows[0].points != r.reporter_points:
            fails.append(f"job '{r.description[:40]}': the poster has no matching +{r.reporter_points} entry")
        helpers = [h.user_id for h in db.query(m.ReportHelper).filter(m.ReportHelper.report_id == r.id)]
        if len(helpers) != (r.filled_slots or 0) or not helpers:
            fails.append(f"job '{r.description[:40]}': {len(helpers)} helpers recorded, {r.filled_slots} slots filled")
        for hid in helpers:
            rows = db.query(m.Submission).filter(
                m.Submission.report_id == r.id, m.Submission.user_id == hid,
                m.Submission.deed_type == "community_cleanup").all()
            if len(rows) != 1 or rows[0].points != r.points_awarded:
                fails.append(f"job '{r.description[:40]}': a helper has no matching +{r.points_awarded} entry")

    # Live states for the demo.
    open_n = db.query(m.Report).filter(m.Report.status == "open", m.Report.reported_by.in_(ids)).count()
    if open_n < 3:
        fails.append(f"only {open_n} open jobs to claim live (want at least 3)")
    ticking = 0
    for r in db.query(m.Report).filter(m.Report.status == "claimed", m.Report.reported_by.in_(ids)):
        if r.proof_submitted_at or not r.claimed_at:
            continue
        left = _aware(datetime.fromisoformat(r.claimed_at)) + timedelta(hours=CLAIM_EXPIRY_HOURS) - now
        if left > timedelta(minutes=20):
            ticking += 1
    if ticking < 1:
        fails.append("no claimed job with a running timer (it expired, or was never made): re-run the seed")
    if db.query(m.Report).filter(m.Report.status == "claimed", m.Report.proof_photo_url.isnot(None),
                                 m.Report.reported_by.in_(ids)).count() < 1:
        fails.append("no job waiting on its poster to confirm")

    # Teams.
    for code, want in (("HOPHACKS", 9), ("CLEANUP", 4)):
        g = db.query(m.FriendGroup).filter(m.FriendGroup.invite_code == code).first()
        n = db.query(m.User).filter(m.User.friend_group_id == g.id).count() if g else 0
        if n < want:
            fails.append(f"team {code} has {n} members (want at least {want})")

    # Rationales: present, and never placeholder text.
    for (text,) in db.query(m.Submission.rationale).filter(m.Submission.user_id.in_(ids)):
        if not (text or "").strip() or "[mock]" in text.lower():
            fails.append("a submission has an empty or placeholder rationale")
            break

    # Leaderboard movement, computed by the real endpoint code.
    lena = next((u for u in users if u.email == "lena@demo.dev"), None)
    if lena is not None:
        from backend.routers.leaderboard import get_leaderboard

        weekly = get_leaderboard(scope="friends", period="weekly", db=db, user=lena)
        daily = get_leaderboard(scope="friends", period="daily", db=db, user=lena)
        if sum(1 for e in weekly if e.points > 0) < 8:
            fails.append("the weekly board has fewer than 8 people with points")
        if sum(1 for e in daily if e.points > 0) < 5:
            fails.append("the daily board has fewer than 5 people with points")
        if [e.user_id for e in daily] == [e.user_id for e in weekly]:
            fails.append("the daily and weekly boards rank people identically (no movement)")
    return fails


# --------------------------------------------------------------------------- report

def _health() -> dict:
    from fastapi.testclient import TestClient

    from backend.main import app

    body = TestClient(app).get("/health")
    return body.json() if body.status_code == 200 else {"status": f"HTTP {body.status_code}"}


def report(summary: dict | None = None) -> bool:
    from backend.database import SessionLocal, engine

    db = SessionLocal()
    now = datetime.now(UTC)
    try:
        _heading("Where this is writing, and what the AI/Places providers are")
        print(f"  database   : {engine.url.render_as_string(hide_password=True)}")
        health = _health()
        agent = health.get("agent", {})
        print(f"  /health    : {health}")
        if health.get("database") == "sqlite":
            print("  NOTE       : this is a LOCAL SQLite file, not the shared/hosted database.")
        if agent.get("llm_provider") == "mock":
            print("  WARNING    : llm_provider is 'mock'. Any deed a judge submits live is scored by a stub, so the\n"
                  "               points and explanation are placeholders (the app shows a yellow 'Demo scoring'\n"
                  "               banner). The seeded history is unaffected. Set OPENAI_API_KEY to fix.")
        if agent.get("places_provider") == "mock":
            print("  WARNING    : places_provider is 'mock'. The map shows sample organisations, not real ones.")
        if agent.get("llm_provider") == "openai" and agent.get("places_provider") == "google":
            print("  OK         : real database, real AI scoring (openai) and real nearby places (google).")

        users = demo_users(db)
        _heading("Demo accounts per tier")
        tiers = defaultdict(list)
        for u in users:
            tiers[u.tier].append(u)
        for tier in ("Gold", "Silver", "Bronze"):
            names = ", ".join(f"{u.name.split()[0]} {u.tier_points}" for u in sorted(tiers[tier], key=lambda x: -x.tier_points))
            print(f"  {tier:6} {len(tiers[tier]):2}   {names}")
        total = db.query(m.User).count()
        print(f"  ({len(users)} demo accounts of {total} in the database; the rest are untouched)")

        _heading("Verified deeds per day, last 8 days (demo accounts)")
        ids = [u.id for u in users]
        per_day: dict = defaultdict(lambda: [0, 0, 0, 0])
        for when, pts in db.query(m.Submission.scored_at, m.Submission.points).filter(m.Submission.user_id.in_(ids)):
            d = _aware(when).astimezone(UTC).date()
            if pts > 0:
                per_day[d][0] += 1
                per_day[d][1] += pts
            else:
                per_day[d][2] += 1
        for day, pts in db.query(m.MicroDeedDone.day, m.MicroDeedDone.points).filter(m.MicroDeedDone.user_id.in_(ids)):
            per_day[datetime.fromisoformat(day).date()][3] += 1
        print("  date         deeds  points  rejected  everyday")
        for i in range(8):
            d = (now - timedelta(days=i)).date()
            c = per_day.get(d, [0, 0, 0, 0])
            print(f"  {d}{' (today)' if i == 0 else '        '}  {c[0]:5}  {c[1]:6}  {c[2]:8}  {c[3]:8}")

        _heading("Community jobs and Boost campaigns per status")
        for status, n in db.query(m.Report.status, func.count(m.Report.id)).group_by(m.Report.status).all():
            print(f"  reports    {status:8} {n}")
        for r in db.query(m.Report).filter(m.Report.status == "claimed", m.Report.reported_by.in_(ids)):
            if r.proof_submitted_at:
                print(f"             waiting on the poster to confirm: {r.description[:56]}")
            elif r.claimed_at:
                left = _aware(datetime.fromisoformat(r.claimed_at)) + timedelta(hours=CLAIM_EXPIRY_HOURS) - now
                mins = int(left.total_seconds() // 60)
                print(f"             timer running, {mins // 60}h {mins % 60:02d}m left: {r.description[:50]}")
        for status, n in db.query(m.Campaign.status, func.count(m.Campaign.id)).group_by(m.Campaign.status).all():
            print(f"  campaigns  {status:8} {n}")

        _heading("Both sides of every finished job (queried back, not assumed)")
        print("  poster (total now)              helper(s) (total now)                 pays")
        for r in (db.query(m.Report).filter(m.Report.status == "done", m.Report.reported_by.in_(ids))
                  .order_by(m.Report.confirmed_at)):
            poster = db.get(m.User, r.reported_by)
            helpers = [db.get(m.User, h.user_id) for h in db.query(m.ReportHelper).filter(m.ReportHelper.report_id == r.id)]
            hs = ", ".join(f"{h.name.split()[0]} ({h.tier_points})" for h in helpers)
            print(f"  {poster.name.split()[0] + ' (' + str(poster.tier_points) + ')':30}  {hs:36}  "
                  f"+{r.reporter_points} / +{r.points_awarded}")

        _heading("Teams")
        for g in db.query(m.FriendGroup).filter(m.FriendGroup.created_by.in_(ids)):
            members = db.query(m.User).filter(m.User.friend_group_id == g.id).all()
            print(f"  {g.invite_code:9} {len(members):2} members: " + ", ".join(sorted(u.name.split()[0] for u in members)))
        print("  (a judge joins a team by entering its code under Profile > Join a team)")

        lena = next((u for u in users if u.email == "lena@demo.dev"), None)
        if lena:
            from backend.routers.leaderboard import get_leaderboard

            for period in ("daily", "weekly"):
                _heading(f"Team HOPHACKS leaderboard, {period} (as the API returns it)")
                for e in get_leaderboard(scope="friends", period=period, db=db, user=lena)[:10]:
                    print(f"  {e.rank:2}. {e.name:16} {e.points:4} pts  {e.deed_count} deeds")

        _heading("Streaks")
        for u in sorted(users, key=lambda x: -x.current_streak)[:6]:
            print(f"  {u.name:16} {u.current_streak:2}-day streak (best {u.longest_streak})")

        _heading("Consistency checks")
        fails = invariant_failures(db, now)
        if fails:
            for f in fails:
                print("  FAIL:", f)
        else:
            print("  all checks passed: every account's points, coins and escrow are explained by rows in the database,")
            print("  streaks match the deed history, and every finished job paid both the poster and its helpers.")

        if summary:
            _heading("Demo logins (password for every account: " + PASSWORD + ")")
            print(f"  {'email':20} {'tier':7} {'pts':>4} {'streak':>6}  team       what to show")
            for a in summary["accounts"]:
                print(f"  {a['email']:20} {a['tier']:7} {a['points']:4} {a['streak']:6}  {(a['team'] or '-'):9}  {a['note']}")
        return not fails
    finally:
        db.close()


def main() -> None:
    sys.exit(0 if report() else 1)


if __name__ == "__main__":
    main()
