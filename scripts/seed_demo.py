"""Seed demo data so the leaderboard and community feed aren't empty.

Writes straight to the DB (bypassing the AI checks) because seeding is a
demo convenience, not a code path users exercise. Idempotent: re-running
resets the demo users and reports rather than duplicating them.

    python3 scripts/seed_demo.py
"""
from __future__ import annotations

import random
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, ".")

from backend import db_models as m
from backend.database import Base, SessionLocal, engine
from backend.security import hash_password
from gooddeed_agent import tier_for_points

Base.metadata.create_all(bind=engine)

NOW = datetime.now(timezone.utc)
BALT = (39.3299, -76.6205)

PEOPLE = [
    ("Lena Rivera",  "lena@demo.dev",   "lenabuilds",   288),
    ("Theo Marsh",   "theo@demo.dev",   "theohelps",    246),
    ("Ana Powell",   "ana@demo.dev",    "anap",         211),
    ("Jordan Kim",   "jordan@demo.dev", "jordank",      172),
    ("Priya Shah",   "priya@demo.dev",  "priyas",       161),
    ("Omar Diallo",  "omar@demo.dev",   "omard",        154),
]

ORGS = [
    ("Maryland Food Bank", "food_bank"),
    ("Maryland SPCA", "animal_shelter"),
    ("The Baltimore Station", "homeless_shelter"),
    ("Lennox Street Community Garden", "environmental"),
    ("Village Learning Place", "education"),
]

REPORTS = [
    ("Trash piled along the Jones Falls trail underpass", 39.3340, -76.6180, "open", None),
    ("Flyers completely covering the bus shelter at 33rd & Greenmount", 39.3270, -76.6090, "claimed", 3),
    ("Tree bed outside the library needs weeding", 39.3355, -76.6255, "open", None),
    ("Broken bench at the Wyman Park entrance", 39.3290, -76.6300, "open", None),
]


def main() -> None:
    db = SessionLocal()
    rng = random.Random(7)
    try:
        emails = [p[1] for p in PEOPLE]
        # Clear prior demo rows so re-running doesn't stack duplicates.
        old = db.query(m.User).filter(m.User.email.in_(emails)).all()
        old_ids = [u.id for u in old]
        if old_ids:
            db.query(m.Submission).filter(m.Submission.user_id.in_(old_ids)).delete(synchronize_session=False)
            db.query(m.Report).filter(m.Report.reported_by.in_(old_ids)).delete(synchronize_session=False)
            db.query(m.Session).filter(m.Session.user_id.in_(old_ids)).delete(synchronize_session=False)
            db.query(m.User).filter(m.User.id.in_(old_ids)).delete(synchronize_session=False)
            db.commit()

        users: list[m.User] = []
        for name, email, username, target in PEOPLE:
            pw_hash, salt = hash_password("demo1234")
            user = m.User(
                name=name, email=email, password_hash=pw_hash, password_salt=salt,
                username=username, city="Baltimore",
                lat=BALT[0] + rng.uniform(-0.01, 0.01),
                lng=BALT[1] + rng.uniform(-0.01, 0.01),
                tier_points=target, tier=tier_for_points(target),
                current_streak=rng.randint(2, 14), longest_streak=rng.randint(5, 16),
                last_active_date=NOW.date().isoformat(),
            )
            db.add(user)
            users.append(user)
        db.flush()

        # Spread each user's points over a few submissions inside the last
        # week, so both the daily and weekly leaderboards have something.
        for user, (_n, _e, _u, target) in zip(users, PEOPLE):
            remaining = target
            count = rng.randint(4, 7)
            for i in range(count):
                pts = remaining if i == count - 1 else max(10, min(remaining - (count - i - 1) * 10, rng.randint(18, 48)))
                remaining -= pts
                if pts <= 0:
                    continue
                org, _cat = ORGS[rng.randrange(len(ORGS))]
                when = NOW - timedelta(hours=rng.randint(1, 160))
                db.add(m.Submission(
                    user_id=user.id, org_name=org, photo_url="", 
                    description=f"Helped out at {org}.",
                    time_spent_minutes=rng.choice([30, 45, 60, 90, 120]),
                    lat=BALT[0], lng=BALT[1], submitted_at=when.isoformat(),
                    points=pts, tier_points=pts,
                    authenticity_confidence=round(rng.uniform(0.78, 0.96), 2),
                    rationale="Photo matches the described shift.",
                    scored_at=when,
                ))

        for desc, lat, lng, status, claimer in REPORTS:
            created = NOW - timedelta(minutes=rng.randint(15, 300))
            db.add(m.Report(
                reported_by=users[rng.randrange(3)].id,
                photo_url="", description=desc, lat=lat, lng=lng,
                status=status,
                claimed_by=users[claimer].id if claimer is not None else None,
                claimed_at=(created + timedelta(minutes=20)).isoformat() if claimer is not None else None,
                created_at=created.isoformat(),
                category="litter", classification_confidence=0.9,
            ))

        db.commit()
        print(f"Seeded {len(users)} users, "
              f"{db.query(m.Submission).count()} submissions, "
              f"{db.query(m.Report).count()} reports.")
        print("Demo logins: lena@demo.dev … omar@demo.dev / password: demo1234")
    finally:
        db.close()


if __name__ == "__main__":
    main()
