"""Remove accounts created by the automated test suites.

The DOM suites sign up throwaway users with timestamped emails. They are
harmless but they clutter the leaderboard during a demo, so this removes
anything matching the test prefixes and leaves real accounts alone.

    python3 scripts/wipe_test_accounts.py
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from backend import db_models as m
from backend.database import SessionLocal

# Prefixes used by the test harnesses. Real signups never look like these.
TEST_PREFIXES = (
    "today_", "cmp_", "eng_", "soc_", "rec_", "recapui_", "team_",
    "live_", "dbg_", "helper@", "persist@",
)


def main() -> None:
    db = SessionLocal()
    try:
        users = [
            u for u in db.query(m.User).all()
            if any(u.email.startswith(p) for p in TEST_PREFIXES)
        ]
        ids = [u.id for u in users]
        if not ids:
            print("No test accounts found.")
            return
        print(f"Removing {len(ids)} test account(s):")
        for u in users:
            print(f"  {u.email}")

        # Children first: Postgres enforces these foreign keys.
        sub_ids = [s.id for s in db.query(m.Submission).filter(m.Submission.user_id.in_(ids))]
        if sub_ids:
            db.query(m.Reaction).filter(m.Reaction.submission_id.in_(sub_ids)).delete(synchronize_session=False)
            db.query(m.Comment).filter(m.Comment.submission_id.in_(sub_ids)).delete(synchronize_session=False)
        db.query(m.Reaction).filter(m.Reaction.user_id.in_(ids)).delete(synchronize_session=False)
        db.query(m.Comment).filter(m.Comment.user_id.in_(ids)).delete(synchronize_session=False)
        db.query(m.Report).filter(m.Report.reported_by.in_(ids)).delete(synchronize_session=False)
        db.query(m.Report).filter(m.Report.claimed_by.in_(ids)).update(
            {"claimed_by": None, "status": "open", "claimed_at": None}, synchronize_session=False
        )
        for table in (m.Submission, m.MicroDeedDone, m.CheckIn, m.Session):
            db.query(table).filter(table.user_id.in_(ids)).delete(synchronize_session=False)

        group_ids = [g.id for g in db.query(m.FriendGroup).filter(m.FriendGroup.created_by.in_(ids))]
        if group_ids:
            db.query(m.User).filter(m.User.friend_group_id.in_(group_ids)).update(
                {"friend_group_id": None}, synchronize_session=False
            )
        db.query(m.User).filter(m.User.id.in_(ids)).update({"friend_group_id": None}, synchronize_session=False)
        db.flush()
        if group_ids:
            db.query(m.FriendGroup).filter(m.FriendGroup.id.in_(group_ids)).delete(synchronize_session=False)
        db.flush()
        db.query(m.User).filter(m.User.id.in_(ids)).delete(synchronize_session=False)
        db.commit()

        print(f"\nAccounts left: {db.query(m.User).count()}")
        for u in db.query(m.User).all():
            print(f"  {u.email}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
