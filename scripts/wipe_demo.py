"""Remove every seeded demo account and everything attached to it.

Leaves real signups untouched: it deletes only the accounts whose emails are
in scripts/seed_demo.py. Run before a demo or launch so the leaderboard shows
real people instead of Lena, Theo and Ana.

    python3 scripts/wipe_demo.py            # delete seeded accounts
    python3 scripts/wipe_demo.py --all      # delete EVERY account and report
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from backend import db_models as m
from backend.database import SessionLocal

DEMO_EMAILS = [
    "lena@demo.dev", "theo@demo.dev", "ana@demo.dev",
    "jordan@demo.dev", "priya@demo.dev", "omar@demo.dev",
    # accounts created while testing
    "maya@test.dev", "persist@test.dev",
]


def main() -> None:
    wipe_all = "--all" in sys.argv
    db = SessionLocal()
    try:
        if wipe_all:
            users = db.query(m.User).all()
            print(f"Deleting ALL {len(users)} accounts and every report.")
        else:
            users = db.query(m.User).filter(m.User.email.in_(DEMO_EMAILS)).all()
            print(f"Deleting {len(users)} seeded demo account(s).")

        ids = [u.id for u in users]
        if ids:
            # Order matters: Postgres enforces the foreign keys that SQLite
            # was quietly ignoring, so every reference to a user has to go
            # before the user does.

            # 1. Reports the user posted, and claims they hold on others'.
            db.query(m.Report).filter(m.Report.reported_by.in_(ids)).delete(synchronize_session=False)
            db.query(m.Report).filter(m.Report.claimed_by.in_(ids)).update(
                {"claimed_by": None, "status": "open", "claimed_at": None},
                synchronize_session=False,
            )
            # 2. Their submissions and login sessions.
            db.query(m.Submission).filter(m.Submission.user_id.in_(ids)).delete(synchronize_session=False)
            db.query(m.Session).filter(m.Session.user_id.in_(ids)).delete(synchronize_session=False)

            # 3. Friend groups point at users twice: members via
            #    users.friend_group_id, and the creator via created_by. Drop
            #    the membership, then any group these users created.
            group_ids = [
                g.id for g in db.query(m.FriendGroup).filter(m.FriendGroup.created_by.in_(ids)).all()
            ]
            if group_ids:
                db.query(m.User).filter(m.User.friend_group_id.in_(group_ids)).update(
                    {"friend_group_id": None}, synchronize_session=False
                )
            db.query(m.User).filter(m.User.id.in_(ids)).update(
                {"friend_group_id": None}, synchronize_session=False
            )
            db.flush()
            if group_ids:
                db.query(m.FriendGroup).filter(m.FriendGroup.id.in_(group_ids)).delete(
                    synchronize_session=False
                )
            db.flush()

            # 4. Finally the users themselves.
            db.query(m.User).filter(m.User.id.in_(ids)).delete(synchronize_session=False)

        if wipe_all:
            db.query(m.Report).delete(synchronize_session=False)
            db.query(m.User).update({"friend_group_id": None}, synchronize_session=False)
            db.flush()
            db.query(m.FriendGroup).delete(synchronize_session=False)

        # Cached opportunities are derived data, never user content -- always
        # safe to clear, and it forces a fresh Places lookup next request.
        db.query(m.Opportunity).delete(synchronize_session=False)
        db.commit()

        print(f"  users left:       {db.query(m.User).count()}")
        print(f"  submissions left: {db.query(m.Submission).count()}")
        print(f"  reports left:     {db.query(m.Report).count()}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
