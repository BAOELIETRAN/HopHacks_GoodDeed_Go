"""Remove the demo accounts, and everything attached to them, from the database.

A demo account is one whose email ends in ``@demo.dev`` (see scripts/seed_demo.py),
plus a short list of old test emails. Real signups are never touched, and nor is the
quest cache: the cache is real Places data, and clearing it only makes the first map
load slow.

Every table that points at a user is cleaned in foreign-key order, because Postgres
enforces the constraints SQLite quietly ignores. That covers the newer tables too
(comments, reactions, helpers, campaigns, the points ledger, the store).

    python scripts/wipe_demo.py            # delete the demo accounts only
    python scripts/wipe_demo.py --all --yes  # delete EVERY account, report and campaign

``--all`` is for a throwaway database. It refuses to run without ``--yes``.
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from sqlalchemy import func, or_

from backend import db_models as m

DEMO_DOMAIN = "@demo.dev"

# Accounts made by earlier test scripts, which the seed used to clean up as well.
LEGACY_EMAILS = [
    "maya@test.dev", "persist@test.dev", "team_a@test.dev", "team_b@test.dev", "helper@test.dev",
]

_CHUNK = 400  # keeps IN (...) lists under SQLite's 999-variable limit


def demo_users(db) -> list[m.User]:
    return (
        db.query(m.User)
        .filter(or_(func.lower(m.User.email).like(f"%{DEMO_DOMAIN}"),
                    func.lower(m.User.email).in_(LEGACY_EMAILS)))
        .all()
    )


def _chunks(items: list[str]):
    for i in range(0, len(items), _CHUNK):
        yield items[i:i + _CHUNK]


def _delete_in(db, column, ids: list[str]) -> int:
    total = 0
    for part in _chunks(ids):
        total += db.query(column.class_).filter(column.in_(part)).delete(synchronize_session=False)
    return total


def wipe_accounts(db, users: list[m.User]) -> tuple[dict[str, int], list[tuple[str, str]]]:
    """Delete these users and everything that references them.

    Returns ``(counts, detached)``. ``detached`` lists ``(user_id, invite_code)`` for
    real (non-demo) people who had joined a demo team, so a reseed can put them back.
    """
    ids = [u.id for u in users]
    counts: dict[str, int] = {}
    detached: list[tuple[str, str]] = []
    if not ids:
        return counts, detached

    def note(name: str, n: int) -> None:
        if n:
            counts[name] = counts.get(name, 0) + n

    demo_ids = set(ids)
    sub_ids = [r[0] for r in db.query(m.Submission.id).filter(m.Submission.user_id.in_(ids))]

    # 1. Reactions and comments: the ones these users wrote, and anyone's on their deeds.
    note("reactions", _delete_in(db, m.Reaction.user_id, ids))
    note("comments", _delete_in(db, m.Comment.user_id, ids))
    note("reactions", _delete_in(db, m.Reaction.submission_id, sub_ids))
    note("comments", _delete_in(db, m.Comment.submission_id, sub_ids))

    # 2. Their own records.
    note("submissions", _delete_in(db, m.Submission.user_id, ids))
    note("checkins", _delete_in(db, m.CheckIn.user_id, ids))
    note("everyday deeds", _delete_in(db, m.MicroDeedDone.user_id, ids))
    note("store items", _delete_in(db, m.OwnedItem.user_id, ids))
    note("sessions", _delete_in(db, m.Session.user_id, ids))

    # 3. Community reports. Ones they posted go, with their helper rows...
    posted = [r[0] for r in db.query(m.Report.id).filter(m.Report.reported_by.in_(ids))]
    note("report helpers", _delete_in(db, m.ReportHelper.report_id, posted))
    note("reports", _delete_in(db, m.Report.id, posted))

    # ...and where they helped on somebody else's report, they just step out of it.
    helped = {
        rid for (rid,) in db.query(m.ReportHelper.report_id).filter(m.ReportHelper.user_id.in_(ids))
    }
    note("report helpers", _delete_in(db, m.ReportHelper.user_id, ids))
    db.flush()
    for rid in helped:
        report = db.get(m.Report, rid)
        if report is None:
            continue
        remaining = [
            h.user_id for h in db.query(m.ReportHelper).filter(m.ReportHelper.report_id == rid)
        ]
        report.filled_slots = len(remaining)
        if report.claimed_by in demo_ids:
            report.claimed_by = remaining[0] if remaining else None
        if not remaining and report.status == "claimed":
            report.status = "open"
            report.claimed_at = None
            report.proof_photo_url = report.proof_description = None
            report.proof_time_spent_minutes = report.proof_submitted_at = None
    # A claim with no helper row (older data) still has to let go of the user id.
    for report in db.query(m.Report).filter(m.Report.claimed_by.in_(ids)).all():
        report.claimed_by = None
        report.claimed_at = None
        if report.status == "claimed":
            report.status = "open"

    # 4. Campaigns and the points ledger. The ledger rows go too: they describe points
    #    moving to or from an account that no longer exists.
    posted_campaigns = [r[0] for r in db.query(m.Campaign.id).filter(m.Campaign.poster_id.in_(ids))]
    for part in _chunks(posted_campaigns):
        note("ledger rows", db.query(m.PointsTransaction)
             .filter(m.PointsTransaction.campaign_id.in_(part)).delete(synchronize_session=False))
    for part in _chunks(ids):
        note("ledger rows", db.query(m.PointsTransaction).filter(or_(
            m.PointsTransaction.from_user_id.in_(part),
            m.PointsTransaction.to_user_id.in_(part))).delete(synchronize_session=False))
    note("campaigns", _delete_in(db, m.Campaign.id, posted_campaigns))
    for campaign in db.query(m.Campaign).filter(m.Campaign.claimed_by.in_(ids)).all():
        campaign.claimed_by = None
        campaign.claimed_at = None
        campaign.proof_photo_url = campaign.proof_note = None
        if campaign.status in ("claimed", "done"):
            campaign.status = "open"

    # 5. Teams. Everyone leaves a team we are about to delete; real members are
    #    remembered so a reseed can put them back.
    groups = db.query(m.FriendGroup).filter(m.FriendGroup.created_by.in_(ids)).all()
    group_ids = [g.id for g in groups]
    code_of = {g.id: g.invite_code for g in groups}
    if group_ids:
        for u in db.query(m.User).filter(m.User.friend_group_id.in_(group_ids)).all():
            if u.id not in demo_ids:
                detached.append((u.id, code_of[u.friend_group_id]))
            u.friend_group_id = None
    for u in users:
        u.friend_group_id = None
    db.flush()
    note("teams", _delete_in(db, m.FriendGroup.id, group_ids))
    db.flush()

    # 6. The users themselves.
    note("users", _delete_in(db, m.User.id, ids))
    db.flush()
    return counts, detached


def wipe_everything(db) -> dict[str, int]:
    """Every account, report, campaign and team. Throwaway databases only."""
    counts, _ = wipe_accounts(db, db.query(m.User).all())
    for label, model in (("reports", m.Report), ("campaigns", m.Campaign),
                         ("ledger rows", m.PointsTransaction), ("teams", m.FriendGroup)):
        n = db.query(model).delete(synchronize_session=False)
        if n:
            counts[label] = counts.get(label, 0) + n
    return counts


def _describe(counts: dict[str, int]) -> str:
    return ", ".join(f"{n} {name}" for name, n in counts.items()) or "nothing"


def main() -> None:
    from backend.database import SessionLocal, engine

    wipe_all = "--all" in sys.argv
    if wipe_all and "--yes" not in sys.argv:
        sys.exit("--all deletes EVERY account, report and campaign in "
                 f"{engine.url.render_as_string(hide_password=True)}.\nRe-run with --yes if you mean it.")

    db = SessionLocal()
    try:
        if wipe_all:
            counts = wipe_everything(db)
            print("Deleted every account:", _describe(counts))
        else:
            users = demo_users(db)
            print(f"Found {len(users)} demo account(s).")
            counts, _ = wipe_accounts(db, users)
            print("Deleted:", _describe(counts))
        db.commit()
        print(f"  users left:       {db.query(m.User).count()}")
        print(f"  submissions left: {db.query(m.Submission).count()}")
        print(f"  reports left:     {db.query(m.Report).count()}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
