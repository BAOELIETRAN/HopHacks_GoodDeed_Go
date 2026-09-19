"""Wipe and reseed a complete, realistic demo dataset -- the one command before going on stage.

    python scripts/seed_demo.py              # wipe the demo accounts, rebuild everything, verify
    python scripts/seed_demo.py --no-warm    # ...without pre-loading the map's quest cache

It writes to whatever DATABASE_URL points at (Supabase/Postgres), or to the local SQLite
file when that is empty. Only accounts ending in ``@demo.dev`` are ever deleted or
recreated, so real signups survive, and running it twice gives the same result, not two
copies of everyone.

What you get, all dated relative to *now* (so re-run it shortly before presenting):

* 14 people across all three tiers, every password ``demo1234``, in two teams plus one
  fresh account with no team (the one for a judge to try).
* ~10 days of verified deeds with AI-style rationales, real streaks, a few rejected photos,
  everyday deeds, reactions and comments on the team feed.
* Community reports in every state: open, claimed (3-hour timer ticking), waiting for the
  poster to confirm, and done. The done ones are completed through the app's own
  ``complete_report`` code, so the poster-and-helper double credit is the real thing.
* Boost campaigns (open, claimed, paid out) with the points ledger behind them, and a few
  store purchases.

Deeds are written straight to the database rather than through /submissions, so seeding
never spends an OpenAI call and gives the same data every time. The rationales are written
in the model's voice and do not contain placeholder text.
"""
from __future__ import annotations

import argparse
import base64
import math
import random
import struct
import sys
import uuid
import zlib
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, ".")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend import db_models as m  # noqa: E402
from backend import store  # noqa: E402
from backend.agent_client import tier_for_points  # noqa: E402
from backend.config import CLAIM_EXPIRY_HOURS, COMPLETION_MIN_POINTS, REPORTER_POINTS  # noqa: E402
from backend.micro_deeds import BY_ID, DAILY_POINT_CAP, deeds_for_day  # noqa: E402
from backend.security import hash_password  # noqa: E402
from backend.wallet import hold, pay_out  # noqa: E402
from wipe_demo import demo_users, wipe_accounts  # noqa: E402

PASSWORD = "demo1234"
UTC = timezone.utc
BALT = (39.3299, -76.6205)  # Johns Hopkins, where HopHacks is: also the app's fallback location


# --------------------------------------------------------------------------- people

@dataclass
class Person:
    email: str
    name: str
    username: str
    target: int                 # tier points from deeds and everyday deeds (reports/campaigns add on top)
    days: list[int]             # days ago with activity; 0 = today
    team: str | None            # "A", "B" or None
    note: str = ""
    extra: dict = field(default_factory=dict)


PEOPLE = [
    # --- Gold ---
    Person("lena@demo.dev", "Lena Rivera", "lenabuilds", 590, list(range(0, 12)), "A",
           "Has a cleanup waiting on HER confirmation (Maya did the work): confirm it live and both accounts get credit.",
           extra={"recent": 2.0}),
    Person("theo@demo.dev", "Theo Marsh", "theohelps", 548, list(range(0, 9)), "A",
           "Just paid a Boost bounty out to Maya.",
           extra={"recent": 0.7}),
    # --- Silver ---
    Person("ana@demo.dev", "Ana Powell", "anap", 395, [0, 1, 2, 3, 4, 5, 7, 9], "A",
           "Has a cleanup waiting on her confirmation (Chloe did the work)."),
    Person("jordan@demo.dev", "Jordan Kim", "jordank", 312, [0, 1, 2, 3, 6, 8], "A",
           "Posted the storm-drain job that Omar has claimed, timer running."),
    Person("priya@demo.dev", "Priya Shah", "priyas", 262, [0, 1, 2, 4, 7], "A",
           "Has a hatched pet in the store, and a Boost campaign someone has claimed."),
    Person("omar@demo.dev", "Omar Diallo", "omard", 168, [0, 2, 3, 5, 8], "A",
           "Working the storm-drain job right now (3-hour timer), and has claimed a Boost bounty."),
    Person("maya@demo.dev", "Maya Chen", "mayadoesgood", 112, [0, 1, 4, 6], "A",
           "Sent proof for the Stony Run cleanup and is waiting on Lena to confirm."),
    # --- Bronze ---
    Person("sam@demo.dev", "Sam Okafor", "samokafor", 92, [1, 2, 5, 8], "A",
           "Eight points from Silver: the best account for a live tier-up."),
    Person("chloe@demo.dev", "Chloe Bennett", "chloeb", 44, [2, 3, 7], "A", "Sent proof on Ana's cleanup and is waiting on her."),
    Person("diego@demo.dev", "Diego Alvarez", "diegoa", 30, [0, 3, 6], "B", "Runs the second, smaller team (CLEANUP)."),
    Person("hannah@demo.dev", "Hannah Lee", "hannahl", 22, [1, 4], "B", "On the second team, getting going."),
    Person("marcus@demo.dev", "Marcus Johnson", "marcusj", 12, [2, 5], "B", "On the second team, just started."),
    Person("nia@demo.dev", "Nia Thompson", "niat", 6, [3], "B", "On the second team, one small deed so far."),
    Person("newbie@demo.dev", "Riley Park", "rileypark", 0, [], None,
           "Fresh account with no team: sign in as this, or make your own, and join HOPHACKS live."),
]

TEAMS = {"A": ("HOPHACKS", "lena@demo.dev"), "B": ("CLEANUP", "diego@demo.dev")}


# --------------------------------------------------------------------------- content

# name, category, lat, lng, what the photo shows, things a volunteer did there
ORGS = [
    ("Maryland Food Bank", "food_bank", 39.2437, -76.6795,
     "volunteers in aprons sorting canned goods into labelled crates on a warehouse floor",
     ["sorted and boxed donated canned goods", "packed produce boxes for the mobile pantry",
      "checked dates and restocked the pantry shelves"]),
    ("Paul's Place", "food_bank", 39.2810, -76.6415,
     "a serving line with trays of hot meals and volunteers in hairnets",
     ["served lunch to the community", "prepped vegetables in the kitchen", "washed up after dinner service"]),
    ("The Baltimore Station", "homeless_shelter", 39.2696, -76.6161,
     "a supply table with folded clothing sorted into labelled bins",
     ["sorted donated clothing by size", "helped set up the evening meal", "restocked the hygiene kit shelves"]),
    ("BARCS Animal Shelter", "animal_shelter", 39.2655, -76.6540,
     "a volunteer walking a dog in a fenced yard beside a row of kennels",
     ["walked dogs and cleaned kennels", "socialised kittens and refilled water bowls"]),
    ("Blue Water Baltimore", "environmental", 39.2833, -76.6086,
     "tied bags of litter piled beside a stream bank",
     ["cleared litter from the stream bank", "planted native shrubs along the bank"]),
    ("Lennox Street Community Garden", "environmental", 39.3102, -76.6335,
     "raised beds with volunteers holding wheelbarrows and hand tools",
     ["weeded and mulched the raised beds", "turned compost and watered seedlings"]),
    ("Village Learning Place", "education", 39.3200, -76.6156,
     "a reading corner with shelves of children's books and an adult at a small table with two kids",
     ["ran the after-school reading hour", "helped elementary students with homework"]),
    ("Health Care for the Homeless", "healthcare", 39.2905, -76.6020,
     "a check-in desk and boxes of care-kit supplies being assembled",
     ["assembled care kits", "helped at the front desk with intake paperwork"]),
    ("Govans Senior Center", "senior_care", 39.3540, -76.6082,
     "a bright common room with residents at tables and volunteers pouring tea",
     ["ran a bingo afternoon with residents", "delivered lunches to homebound seniors"]),
]

DONATION_ITEMS = [
    ("Goodwill Industries of the Chesapeake", "two bags of winter coats and boots"),
    ("Maryland Food Bank", "a box of canned goods and pasta"),
    ("The Baltimore Station", "towels, blankets and unopened toiletries"),
    ("BARCS Animal Shelter", "old towels and a bag of unopened dog treats"),
    ("Village Learning Place", "a box of children's paperbacks"),
]
DONATION_MONEY = [
    ("American Red Cross", 20), ("Maryland SPCA", 15), ("Habitat for Humanity", 25),
    ("Maryland Food Bank", 30), ("Doctors Without Borders", 40),
]
FUNDRAISERS = [
    ("a dorm-floor bake sale for the Maryland Food Bank", 185),
    ("a 5K pledge page for Blue Water Baltimore", 240),
    ("a lemonade stand for BARCS Animal Shelter", 95),
]
REMOTE_TASKS = [
    ("Baltimore Reads", "tutored a middle schooler in fractions over video for an hour"),
    ("a community clinic", "translated the clinic's intake flyer into Spanish"),
    ("a local archive", "transcribed a batch of handwritten letters for a digitisation project"),
]
ADVOCACY = [
    "emailed my city councilmember asking for funding for the 33rd Street bus shelters",
    "phoned my representative about school-meal funding and shared the script with friends",
    "spoke for two minutes at the neighbourhood association meeting about the crosswalk on Greenmount",
]
KINDNESS = [
    "Carried my elderly neighbour's groceries up three flights of stairs and stayed to help put them away",
    "Paid the bus fare for a stranger whose card kept declining, then waited to make sure they got on",
    "Shovelled and salted the sidewalk for the whole block before work",
    "Sat with a lost child at the farmers' market until their mum found them",
    "Left a thank-you basket and a note for our building's cleaner",
    "Drove a friend without a car to a hospital appointment and waited two hours",
    "Fixed a neighbour's wobbly gate and painted it over the weekend",
]
BLOOD = ["American Red Cross drive at Hopkins Homewood", "Red Cross Baltimore donation centre"]

PLACES = {
    "food_bank": "a warehouse",
    "homeless_shelter": "a shelter",
    "animal_shelter": "an animal shelter",
    "environmental": "an outdoor site",
    "education": "a classroom",
    "healthcare": "a clinic",
    "senior_care": "a community centre",
}

RATIONALES = {
    "volunteer": [
        "The photo shows {scene}, which fits the described {minutes}-minute shift at {org}. The setting and activity match the write-up, and nothing in the image contradicts it.",
        "Consistent with the description: the image shows {scene}. The write-up is specific about what was done at {org}, and the {minutes} minutes is a plausible length for it.",
        "The photo clearly shows {scene}, matching a shift at {org}. Lighting and background look like a working {place}, and the description gives enough detail to check against the image.",
    ],
    "donation_item": [
        "The photo shows {item} packed for donation, and the drop-off at {org} matches the description. The quantity is modest and believable, so this is credited in full.",
        "The image shows {item} ready to hand over at {org}. It lines up with the write-up, and the scale of the donation is plausible.",
    ],
    "donation_money": [
        "The screenshot is a ${amount} donation confirmation to {org}, dated within the last two days. The organisation and amount match the description.",
        "A donation receipt for ${amount} to {org} is visible, with a recent date. It matches what was described, so it counts.",
    ],
    "fundraising": [
        "The fundraising page shown reports ${amount} raised for {cause}, and the description matches it. The page is public and the total is believable for the effort described.",
    ],
    "remote": [
        "The write-up describes {task}, and the screenshot of the session confirms a recent, time-stamped call. Remote help is credited at a slightly lower rate than in-person shifts.",
    ],
    "advocacy": [
        "The description names who was contacted and what was asked, which is what makes a civic action checkable. Small in scale, so it earns a small verified award.",
    ],
    "blood_donation": [
        "The appointment card and wristband are consistent with a blood donation at {org} today. Donations are fixed-value, so no time bonus applies.",
    ],
    "kindness": [
        "No photo is needed for a kindness. The description is specific (who, where, what happened), plausible and modest in scale, so it earns a small verified award.",
        "The description is concrete and believable, and it names a real, small act for another person. It earns the standard kindness award.",
    ],
}

REJECTED = [
    "The image looks like a stock photo (a watermark is visible) rather than a picture taken at {org}, so we couldn't verify the deed. Nothing was deducted. Retake the photo on site and submit again.",
    "The photo shows a different setting from the one described, and there's nothing in it that ties it to {org}. We couldn't verify this one. Nothing was deducted.",
    "The description is very general and the photo is too dark to make out what was done, so we couldn't confirm it. Nothing was deducted. A clearer photo and a sentence about what you did would help.",
]

COMMENTS = [
    "Love this.", "This is the kind of thing I needed to see today.", "How long was the line?",
    "Count me in next time!", "Legend.", "Saving my Saturday for this one.", "So proud of this team.",
    "Tell me they gave you a free tote bag.", "Same place as last week? I'll come along.",
    "That's a solid morning's work.", "Nice one, that counts for a lot.", "You make the rest of us look bad.",
]
EMOJI = ["👏", "❤️", "🔥", "🙌", "💪"]

REPORT_SCORING = [
    "The after photo shows the area clear and the collected material bagged nearby, which matches the write-up of a cleanup here.",
    "The before-and-after difference is clear: the spot described is now tidy and the waste is tied up for pickup. The write-up matches the image.",
    "The photo shows the finished work and the write-up gives a believable account of the time it took. Consistent with the original report.",
]

# --- community reports -------------------------------------------------------------
# key, description, lat, lng, category, poster
OPEN_REPORTS = [
    ("Trash piled along the Jones Falls Trail underpass", 39.3340, -76.6180, "litter", "ana@demo.dev", 1),
    ("Broken bench slats at the Wyman Park Dell entrance", 39.3290, -76.6300, "broken_infrastructure", "theo@demo.dev", 1),
    ("Peeling flyers and tape covering the bus shelter at 33rd & Greenmount", 39.3270, -76.6090, "graffiti", "lena@demo.dev", 1),
    ("Dumped mattress in the alley behind Calvert Street", 39.3232, -76.6142, "abandoned_item", "omar@demo.dev", 2),
    ("Weeds and litter choking the tree pits outside the Waverly library", 39.3355, -76.6255, "overgrowth", "priya@demo.dev", 3),
]
# description, lat, lng, category, poster, [helpers], slots, minutes since claimed
CLAIMED_REPORTS = [
    ("Storm drain on Charles Street blocked with leaves, water pooling at the crosswalk",
     39.3300, -76.6172, "hazard", "jordan@demo.dev", ["omar@demo.dev"], 2, 8),
    ("Overgrown tree bed on Greenmount Ave is swallowing the sidewalk",
     39.3212, -76.6087, "overgrowth", "priya@demo.dev", ["sam@demo.dev"], 3, 20),
]
# description, lat, lng, category, poster, helper, proof text, minutes
PROOF_REPORTS = [
    ("Litter along the Stony Run trail behind the school",
     39.3405, -76.6265, "litter", "lena@demo.dev", "maya@demo.dev",
     "Filled three bags with bottles and wrappers along about 200 metres of trail, and dragged a broken chair out to the road for pickup.", 50, 35),
    ("Graffiti tag and litter at the underpass near Wyman Park",
     39.3318, -76.6318, "graffiti", "ana@demo.dev", "chloe@demo.dev",
     "Scrubbed off the lower tags with the city's approved cleaner and bagged all the loose trash at the base.", 40, 55),
]
# days ago confirmed, description, lat, lng, category, poster, [helpers], proof text, minutes
DONE_REPORTS = [
    (7, "Illegal dumping behind the Waverly rec center", 39.3290, -76.6055, "illegal_dumping", "theo@demo.dev",
     ["priya@demo.dev", "jordan@demo.dev"], "Bagged the loose rubbish and stacked cardboard for pickup with two other volunteers.", 75),
    (6, "Faded flyers layered over the 33rd Street bus shelter", 39.3262, -76.6120, "graffiti", "ana@demo.dev",
     ["maya@demo.dev"], "Peeled off the old flyers and scraped the residue clean.", 45),
    (5, "Graffiti on the underpass wall near Wyman Park", 39.3309, -76.6311, "graffiti", "jordan@demo.dev",
     ["lena@demo.dev"], "Covered the tags with the approved paint and cleaned the base of the wall.", 90),
    (4, "Overflowing litter bin at the Charles Village farmers' market lot", 39.3252, -76.6154, "litter", "priya@demo.dev",
     ["theo@demo.dev"], "Emptied and re-bagged the bin, then picked up what had blown across the lot.", 35),
    (3, "Broken bench slats at the Stony Run playground", 39.3410, -76.6285, "broken_infrastructure", "omar@demo.dev",
     ["ana@demo.dev", "chloe@demo.dev"], "Replaced two slats and tightened the bolts; the bench is safe to sit on again.", 70),
    (2, "Weeds choking the tree pits on Greenmount Ave", 39.3210, -76.6086, "overgrowth", "lena@demo.dev",
     ["omar@demo.dev"], "Cleared all six tree pits and mulched them.", 60),
    (1, "Fallen branches blocking the path at Sherwood Gardens", 39.3560, -76.6068, "hazard", "maya@demo.dev",
     ["diego@demo.dev", "hannah@demo.dev"], "Dragged the branches to the side and swept the path clear.", 40),
]

# --- Boost campaigns --------------------------------------------------------------
# poster, title, url, org, platforms, bounty, note
OPEN_CAMPAIGNS = [
    ("lena@demo.dev", "American Red Cross disaster relief: share our story", "https://www.redcross.org",
     "American Red Cross", "instagram,snapchat", 25, "A story or a reel is fine. Just show the link."),
    ("ana@demo.dev", "Habitat for Humanity build-day fundraiser", "https://www.habitat.org",
     "Habitat for Humanity", "tiktok", 15, "My cousin's crew is building on the 12th."),
    ("jordan@demo.dev", "Humane Society adoption weekend", "https://www.humanesociety.org",
     "Humane Society of the United States", "instagram,snapchat", 12, "Show a pet, tag the shelter."),
]
CLAIMED_CAMPAIGN = ("priya@demo.dev", "Arbor Day Foundation tree-planting drive", "https://www.arborday.org",
                    "Arbor Day Foundation", "instagram", 10, "One story with the link sticker is plenty.", "omar@demo.dev")
DONE_CAMPAIGN = ("theo@demo.dev", "Feeding America pantry appeal", "https://www.feedingamerica.org",
                 "Feeding America", "instagram", 20, "Every share helps.", "maya@demo.dev")

# --- store --------------------------------------------------------------------------
# email, code, kind, equip, hatched animal code
PURCHASES = [
    ("lena@demo.dev", "av_lantern", True), ("theo@demo.dev", "av_bloom", True),
    ("jordan@demo.dev", "av_sprout", True), ("priya@demo.dev", "av_sun", True),
    ("ana@demo.dev", "egg_mossy", False),
]


# --------------------------------------------------------------------------- helpers

def _png(size: int, rgb: tuple[int, int, int]) -> str:
    """A flat colour PNG as a data: URL. Placeholder proof photos only."""
    raw = b"".join(b"\x00" + bytes(rgb) * size for _ in range(size))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return "data:image/png;base64," + base64.b64encode(png).decode()


PROOF_PHOTO = _png(64, (150, 170, 140))


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def moment(now: datetime, days_ago: int, rng: random.Random) -> datetime:
    """A believable time on a given calendar day (UTC). Today's are always in the past."""
    if days_ago == 0:
        since_midnight = (now - now.replace(hour=0, minute=0, second=0, microsecond=0)).total_seconds() / 3600
        if since_midnight < 1.0:
            return now - timedelta(minutes=rng.randint(8, 40))
        hi = min(9.0, since_midnight - 0.1)
        return now - timedelta(hours=rng.uniform(min(0.6, hi), hi))
    day = (now - timedelta(days=days_ago)).date()
    return datetime(day.year, day.month, day.day, tzinfo=UTC) + timedelta(hours=rng.uniform(8.5, 21.0))


# Tier-point range each deed type can plausibly pay (inside the agent's own caps).
TYPE_RANGE = {
    "volunteer": (24, 100), "donation_item": (20, 70), "donation_money": (20, 80), "fundraising": (25, 90),
    "remote": (22, 85), "blood_donation": (35, 90), "kindness": (6, 20), "advocacy": (4, 15),
}
TYPE_WEIGHT = {
    "volunteer": 6.0, "donation_item": 1.3, "donation_money": 1.3, "fundraising": 0.6,
    "remote": 0.8, "blood_donation": 0.5, "kindness": 3.0, "advocacy": 1.5,
}


def pick_type(size: int, rng: random.Random) -> str:
    options = [(t, TYPE_WEIGHT[t]) for t, (lo, hi) in TYPE_RANGE.items() if lo <= size <= hi]
    if not options:  # a rounding leftover outside every range: fall back to the nearest sensible kind
        return "advocacy" if size < 6 else "volunteer"
    types, weights = zip(*options)
    return rng.choices(types, weights=weights)[0]


@dataclass
class SubPlan:
    day: int
    size: int
    kind: str


def plan_person(p: Person, now: datetime, rng: random.Random) -> tuple[list[SubPlan], list[tuple[int, str, int]]]:
    """Split a person's target into submissions and (day, deed_id, points) everyday deeds."""
    if p.target <= 0 or not p.days:
        return [], []
    micro: list[tuple[int, str, int]] = []
    if p.target >= 40:
        for d in p.days:
            take = 2 if (d == 0 and p.email == "lena@demo.dev") else (1 if (d == 0 or rng.random() < 0.5) else 0)
            day_date = (now - timedelta(days=d)).date()
            pool = list(deeds_for_day(day_date))
            rng.shuffle(pool)
            spent = 0
            for spec in pool[:take]:
                if spent + spec.points <= DAILY_POINT_CAP:
                    micro.append((d, spec.id, spec.points))
                    spent += spec.points
        while micro and sum(x[2] for x in micro) > 0.12 * p.target:
            micro.pop(rng.randrange(len(micro)))
    remaining = p.target - sum(x[2] for x in micro)

    # Most active days get one submission; a heavy earner gets a second on some days.
    sub_days = list(p.days)
    micro_only = [d for d in sub_days if d != 0 and remaining > 0 and any(x[0] == d for x in micro) and rng.random() < 0.3]
    sub_days = [d for d in sub_days if d not in micro_only] or list(p.days)
    while math.ceil(remaining / 60) > len(sub_days):
        sub_days.append(rng.choice(p.days))
    recent = p.extra.get("recent", 1.0)  # >1 makes the last week heavier than the days before it
    weights = [rng.uniform(0.6, 1.4) * (recent if d <= 6 else 1.0) for d in sub_days]
    sizes = [max(4, round(remaining * w / sum(weights))) for w in weights]
    sizes[sizes.index(max(sizes))] += remaining - sum(sizes)
    return [SubPlan(d, s, pick_type(s, rng)) for d, s in zip(sub_days, sizes)], micro


def describe(kind: str, size: int, rng: random.Random) -> dict:
    """org, category, description, rationale, minutes and location for one deed."""
    out: dict = {"org": "", "cat": None, "lat": BALT[0], "lng": BALT[1], "minutes": 0}
    if kind == "volunteer":
        name, cat, lat, lng, scene, jobs = rng.choice(ORGS)
        minutes = max(30, min(240, round(((size - 30) * 10 + 60) / 5) * 5))
        out.update(org=name, cat=cat, lat=lat, lng=lng, minutes=minutes)
        out["description"] = f"{rng.choice(jobs).capitalize()} at {name} for about {minutes} minutes."
        out["rationale"] = rng.choice(RATIONALES["volunteer"]).format(
            scene=scene, minutes=minutes, org=name, place=PLACES.get(cat, "a community site"))
    elif kind == "donation_item":
        org, item = rng.choice(DONATION_ITEMS)
        out.update(org=org)
        out["description"] = f"Dropped off {item} at {org}."
        out["rationale"] = rng.choice(RATIONALES[kind]).format(item=item, org=org)
    elif kind == "donation_money":
        org, amount = rng.choice(DONATION_MONEY)
        out.update(org=org)
        out["description"] = f"Donated ${amount} to {org}."
        out["rationale"] = rng.choice(RATIONALES[kind]).format(org=org, amount=amount)
    elif kind == "fundraising":
        cause, amount = rng.choice(FUNDRAISERS)
        out.update(org=cause.split(" for ")[-1])
        out["description"] = f"Ran {cause} and raised ${amount}."
        out["rationale"] = rng.choice(RATIONALES[kind]).format(amount=amount, cause=cause.split(" for ")[-1])
    elif kind == "remote":
        org, task = rng.choice(REMOTE_TASKS)
        out.update(org=org, minutes=60)
        out["description"] = f"Remotely {task}."
        out["rationale"] = rng.choice(RATIONALES[kind]).format(task=task)
    elif kind == "advocacy":
        out["description"] = rng.choice(ADVOCACY).capitalize() + "."
        out["rationale"] = rng.choice(RATIONALES[kind])
    elif kind == "blood_donation":
        org = rng.choice(BLOOD)
        out.update(org=org)
        out["description"] = f"Gave blood at the {org}."
        out["rationale"] = rng.choice(RATIONALES[kind]).format(org=org)
    else:  # kindness
        out["description"] = rng.choice(KINDNESS) + "."
        out["rationale"] = rng.choice(RATIONALES["kindness"])
    return out


def _credit(user: m.User, pts: int) -> None:
    """Mirror what the app does for any earned points: the lifetime record and the coins."""
    user.tier_points += pts
    user.coins += pts


def _placeholder_scorer(rng: random.Random):
    """Stands in for the AI when the seed completes reports through the real endpoint code.

    Seeding must be deterministic and free, so the scorer is swapped for the duration of
    the reports step only. Everything else in complete_report (the crediting, the ledger
    entries, coins, the payout note) runs unchanged.
    """
    def score(_submission: dict, **_kwargs) -> dict:
        pts = rng.randint(14, 32)
        return {
            "points": pts, "tier_points": pts,
            "authenticity_confidence": round(rng.uniform(0.82, 0.95), 2),
            "rationale": rng.choice(REPORT_SCORING),
        }
    return score


# --------------------------------------------------------------------------- the seed

def seed(db, *, now: datetime | None = None, rng_seed: int = 2026, log=print) -> dict:
    """Wipe the demo accounts and rebuild everything. Returns a summary for printing/tests."""
    now = now or datetime.now(UTC)
    rng = random.Random(rng_seed)

    # ---- 1. wipe (only @demo.dev accounts) -------------------------------------------------
    counts, detached = wipe_accounts(db, demo_users(db))
    db.commit()
    log(f"  wiped previous demo data: {', '.join(f'{n} {k}' for k, n in counts.items()) or 'nothing to remove'}")

    try:
        return _build(db, now, rng, detached, counts, log)
    except Exception:
        # Half a demo is worse than none: leave a clean slate and say why.
        db.rollback()
        wipe_accounts(db, demo_users(db))
        db.commit()
        log("  seeding failed; the partial demo data was removed again")
        raise


def _build(db, now: datetime, rng: random.Random, detached, wiped, log) -> dict:
    users: dict[str, m.User] = {}

    # ---- 2. users and teams ----------------------------------------------------------------
    for p in PEOPLE:
        pw_hash, salt = hash_password(PASSWORD)
        u = m.User(
            name=p.name, email=p.email, password_hash=pw_hash, password_salt=salt,
            username=p.username, city="Baltimore",
            lat=BALT[0] + rng.uniform(-0.012, 0.012), lng=BALT[1] + rng.uniform(-0.012, 0.012),
            created_at=now - timedelta(days=(rng.randint(14, 40) if p.target else 0), hours=rng.randint(0, 20)),
            tier_points=0, coins=0, escrow_points=0, tier="Bronze",
        )
        db.add(u)
        users[p.email] = u
    db.flush()

    teams: dict[str, m.FriendGroup] = {}
    for key, (code, owner) in TEAMS.items():
        clash = db.query(m.FriendGroup).filter(m.FriendGroup.invite_code == code).first()
        if clash is not None:  # a real team already owns the code: pick a free variant
            code = f"{code}{rng.randint(2, 9)}"
        g = m.FriendGroup(invite_code=code, created_by=users[owner].id, created_at=now - timedelta(days=12))
        db.add(g)
        teams[key] = g
    db.flush()
    for p in PEOPLE:
        if p.team:
            users[p.email].friend_group_id = teams[p.team].id
    # People who joined a demo team before the wipe (a teammate testing, say) go back in.
    by_code = {g.invite_code: g for g in teams.values()}
    for uid, code in detached:
        if code in by_code:
            db.query(m.User).filter(m.User.id == uid).update({"friend_group_id": by_code[code].id})

    # ---- 3. deeds: submissions, check-ins and everyday deeds ------------------------------------
    subs: list[m.Submission] = []
    for p in PEOPLE:
        u = users[p.email]
        sub_plans, micro = plan_person(p, now, rng)
        for sp in sub_plans:
            info = describe(sp.kind, sp.size, rng)
            when = moment(now, sp.day, rng)
            verified = sp.kind == "volunteer" and rng.random() < 0.3 and info["minutes"] > 0
            points = round(sp.size * 1.5) if verified else sp.size
            sid, cid = uuid.uuid4().hex, uuid.uuid4().hex
            sub = m.Submission(
                id=sid, user_id=u.id, org_name=info["org"], photo_url="", description=info["description"],
                time_spent_minutes=info["minutes"], lat=info["lat"], lng=info["lng"],
                submitted_at=_iso(when - timedelta(seconds=rng.randint(20, 90))),
                points=points, tier_points=sp.size,
                authenticity_confidence=round(rng.uniform(0.9, 0.97) if verified else rng.uniform(0.78, 0.95), 2),
                rationale=info["rationale"] + (" Presence at the site was confirmed by a timed check-in." if verified else ""),
                scored_at=when, deed_type=sp.kind, verified_presence=verified,
                checkin_id=cid if verified else None,
            )
            db.add(sub)
            subs.append(sub)
            if verified:
                start = when - timedelta(minutes=info["minutes"] + 2)
                db.add(m.CheckIn(
                    id=cid, user_id=u.id, org_name=info["org"], org_lat=info["lat"], org_lng=info["lng"],
                    category=info["cat"], quest_type="daily", status="done", started_at=start, ended_at=when,
                    last_seen_at=when, last_lat=info["lat"], last_lng=info["lng"],
                    elapsed_seconds=info["minutes"] * 60, end_reason="completed", submission_id=sid,
                ))
            _credit(u, sp.size)
        for d, deed_id, pts in micro:
            when = moment(now, d, rng)
            db.add(m.MicroDeedDone(user_id=u.id, deed_id=deed_id, day=when.date().isoformat(),
                                   points=pts, created_at=when))
            _credit(u, pts)

    # A few photos the AI couldn't verify: they earn nothing and stay out of the feed and the boards.
    for email, day in (("maya@demo.dev", 1), ("sam@demo.dev", 2), ("marcus@demo.dev", 2)):
        org = rng.choice(ORGS)
        when = moment(now, day, rng) + timedelta(hours=1)
        subs.append(m.Submission(
            user_id=users[email].id, org_name=org[0], photo_url="",
            description=f"Helped out at {org[0]} this afternoon.", time_spent_minutes=60,
            lat=org[2], lng=org[3], submitted_at=_iso(when), points=0, tier_points=0,
            authenticity_confidence=0.3, rationale=rng.choice(REJECTED).format(org=org[0]),
            scored_at=when, deed_type="volunteer",
        ))
        db.add(subs[-1])
    db.commit()
    log(f"  {len(PEOPLE)} accounts in 2 teams, {len(subs)} submissions")

    # ---- 4. community reports ---------------------------------------------------------------
    def new_report(desc, lat, lng, category, poster, created, *, slots=1) -> m.Report:
        r = m.Report(
            reported_by=users[poster].id, photo_url="", description=desc, lat=lat, lng=lng,
            status="open", total_slots=slots, filled_slots=0, created_at=_iso(created),
            category=category, classification_confidence=round(rng.uniform(0.88, 0.96), 2),
        )
        db.add(r)
        db.flush()
        return r

    def add_helper(r: m.Report, email: str, when: datetime) -> None:
        db.add(m.ReportHelper(report_id=r.id, user_id=users[email].id, joined_at=when))
        r.filled_slots = (r.filled_slots or 0) + 1
        if r.claimed_by is None:
            r.claimed_by, r.claimed_at = users[email].id, _iso(when)
        r.status = "claimed"

    for desc, lat, lng, cat, poster, slots in OPEN_REPORTS:
        new_report(desc, lat, lng, cat, poster, now - timedelta(minutes=rng.randint(20, 900)), slots=slots)

    for desc, lat, lng, cat, poster, helpers, slots, mins in CLAIMED_REPORTS:
        r = new_report(desc, lat, lng, cat, poster, now - timedelta(minutes=mins + rng.randint(30, 120)), slots=slots)
        for h in helpers:
            add_helper(r, h, now - timedelta(minutes=mins))

    for desc, lat, lng, cat, poster, helper, text, minutes, ago in PROOF_REPORTS:
        r = new_report(desc, lat, lng, cat, poster, now - timedelta(hours=6))
        add_helper(r, helper, now - timedelta(hours=5))
        r.proof_photo_url, r.proof_description = PROOF_PHOTO, text
        r.proof_time_spent_minutes, r.proof_submitted_at = minutes, _iso(now - timedelta(minutes=ago))
    db.commit()

    # Done reports go through the real completion code, so the double credit is not simulated.
    from backend.routers import reports as reports_router

    checks: list[dict] = []
    real_scorer = reports_router.score_submission_from_dict
    reports_router.score_submission_from_dict = _placeholder_scorer(rng)
    try:
        for days_ago, desc, lat, lng, cat, poster, helpers, text, minutes in DONE_REPORTS:
            confirmed = moment(now, days_ago, rng)
            created = confirmed - timedelta(hours=rng.randint(9, 20))
            # One spot is left unfilled: the app hides full jobs from anyone not involved, and a
            # finished job should show in everybody's Completed tab.
            r = new_report(desc, lat, lng, cat, poster, created, slots=len(helpers) + 1)
            for i, h in enumerate(helpers):
                add_helper(r, h, created + timedelta(hours=1 + i))
            proof_at = confirmed - timedelta(hours=rng.randint(2, 5))
            r.proof_photo_url, r.proof_description = PROOF_PHOTO, text
            r.proof_time_spent_minutes, r.proof_submitted_at = minutes, _iso(proof_at)
            db.commit()

            people = [poster, *helpers]
            before = {e: (users[e].tier_points, users[e].coins) for e in people}
            done = reports_router.complete_report(r.id, db=db, user=users[poster])

            # Backdate what the endpoint stamped "now", so the record reads as history.
            db.query(m.Report).filter(m.Report.id == r.id).update({"confirmed_at": _iso(confirmed)})
            db.query(m.Submission).filter(m.Submission.report_id == r.id).update(
                {"scored_at": confirmed}, synchronize_session=False)
            db.commit()

            for e in people:
                db.refresh(users[e])
            want = {poster: done.reporter_points_awarded, **{h: done.points_awarded for h in helpers}}
            for e in people:
                got = users[e].tier_points - before[e][0]
                got_coins = users[e].coins - before[e][1]
                assert got == want[e] == got_coins, (
                    f"dual credit failed on '{desc}': {e} gained {got} pts / {got_coins} coins, expected {want[e]}")
            checks.append({"report": desc, "poster": poster, "helpers": helpers,
                           "poster_gain": want[poster], "helper_gain": done.points_awarded})
    finally:
        reports_router.score_submission_from_dict = real_scorer
    log(f"  reports: {len(OPEN_REPORTS)} open, {len(CLAIMED_REPORTS)} claimed, "
        f"{len(PROOF_REPORTS)} waiting on the poster, {len(DONE_REPORTS)} done (each checked: poster and helper both paid)")

    # ---- 5. Boost campaigns and the points ledger -----------------------------------------------
    def campaign(spec, created: datetime, status="open") -> m.Campaign:
        poster, title, url, org, plats, bounty, note = spec[:7]
        c = m.Campaign(
            poster_id=users[poster].id, title=title, donation_url=url, note=note, platforms=plats,
            bounty=bounty, status=status, link_ok=True, link_org=org,
            link_note=f"The link goes to {org}'s own site.", created_at=created,
            expires_at=created + timedelta(days=7),
        )
        db.add(c)
        db.flush()
        hold(db, users[poster], bounty, c.id, f"Bounty for “{title}”")
        return c

    for spec in OPEN_CAMPAIGNS:
        campaign(spec, now - timedelta(hours=rng.randint(2, 30)))
    c = campaign(CLAIMED_CAMPAIGN, now - timedelta(hours=9))
    c.status, c.claimed_by, c.claimed_at = "claimed", users[CLAIMED_CAMPAIGN[7]].id, now - timedelta(hours=2)
    c = campaign(DONE_CAMPAIGN, now - timedelta(days=4))
    claimer = users[DONE_CAMPAIGN[7]]
    c.status, c.claimed_by, c.claimed_at = "done", claimer.id, now - timedelta(days=3, hours=4)
    c.proof_photo_url, c.proof_note = PROOF_PHOTO, "Posted to my story Sunday evening with the link sticker on the last slide."
    c.completed_at = now - timedelta(days=2, hours=20)
    pay_out(db, users[DONE_CAMPAIGN[0]], claimer, DONE_CAMPAIGN[5], c.id, f"Promoted “{c.title}”")
    db.flush()
    for tx in db.query(m.PointsTransaction).filter(m.PointsTransaction.campaign_id == c.id):
        tx.created_at = now - timedelta(days=4) if tx.kind == "escrow" else c.completed_at
    db.commit()
    log(f"  Boost: {len(OPEN_CAMPAIGNS)} open, 1 claimed, 1 paid out")

    # ---- 6. store purchases (coins spent, never tier points) -------------------------------------
    db.flush()
    for email, code, equip in PURCHASES:
        u, entry = users[email], store.catalog_item(code)
        price = int(entry["price"])
        assert u.coins >= price, f"{email} can't afford {code} ({u.coins} coins)"
        u.coins -= price
        deeds = store.deeds_done(db, u.id)
        egg = entry["kind"] == "egg"
        db.add(m.OwnedItem(
            user_id=u.id, kind=entry["kind"], code=code, price_paid=price,
            state="incubating" if egg else "owned", acquired_at=now - timedelta(days=rng.randint(1, 5)),
            deeds_at_purchase=max(0, deeds - 1) if egg else 0, hatches_after=int(entry.get("hatches_after") or 0),
        ))
        if equip:
            u.equipped_avatar = code
    # Priya's first egg already hatched.
    egg = store.catalog_item("egg_mossy")
    priya = users["priya@demo.dev"]
    assert priya.coins >= int(egg["price"]), f"priya can't afford her first egg ({priya.coins} coins)"
    priya.coins -= int(egg["price"])
    db.add(m.OwnedItem(
        user_id=priya.id, kind="egg", code="egg_mossy", price_paid=int(egg["price"]), state="hatched",
        acquired_at=now - timedelta(days=8), deeds_at_purchase=0, hatches_after=2,
        hatched_code="an_frog", rarity="common", hatched_at=now - timedelta(days=5),
    ))
    db.commit()

    # ---- 7. reactions and comments on the team feed ---------------------------------------------
    members = {k: [users[p.email] for p in PEOPLE if p.team == k] for k in ("A", "B")}
    team_of = {users[p.email].id: p.team for p in PEOPLE if p.team}
    email_of = {u.id: e for e, u in users.items()}
    feed_subs = (
        db.query(m.Submission)
        .filter(m.Submission.points > 0, m.Submission.user_id.in_(list(team_of)))
        .all()
    )
    # A fully deterministic order: several entries share one timestamp (everyone paid for the
    # same finished job), and breaking those ties by random ids made reseeds differ.
    feed_subs.sort(key=lambda s: (-_aware(s.scored_at).timestamp(), s.description, email_of[s.user_id]))
    feed_subs = feed_subs[:60]
    n_react = n_comment = 0
    for sub in feed_subs:
        peers = [u for u in members[team_of[sub.user_id]] if u.id != sub.user_id]
        if not peers:
            continue
        for u in rng.sample(peers, min(len(peers), rng.choice([0, 1, 1, 2, 3, 4]))):
            db.add(m.Reaction(submission_id=sub.id, user_id=u.id, emoji=rng.choice(EMOJI),
                              created_at=min(now, _aware(sub.scored_at) + timedelta(minutes=rng.randint(5, 240)))))
            n_react += 1
        if rng.random() < 0.3:
            for u in rng.sample(peers, min(len(peers), rng.choice([1, 1, 2]))):
                db.add(m.Comment(submission_id=sub.id, user_id=u.id, text=rng.choice(COMMENTS),
                                 created_at=min(now, _aware(sub.scored_at) + timedelta(minutes=rng.randint(10, 400)))))
                n_comment += 1
    db.commit()
    log(f"  team feed: {n_react} reactions, {n_comment} comments")

    # ---- 8. streaks and tiers, derived from what is really in the database -------------------------
    for p in PEOPLE:
        u = users[p.email]
        cur, longest, last = derive_streaks(activity_dates(db, u.id))
        u.current_streak, u.longest_streak, u.last_active_date = cur, longest, last
        u.tier = tier_for_points(u.tier_points)
    db.commit()

    from backend.routers.leaderboard import get_leaderboard

    week = {e.user_id: e.rank for e in get_leaderboard(scope="friends", period="weekly", db=db, user=users["lena@demo.dev"])}
    accounts = []
    for p in PEOPLE:
        u = users[p.email]
        facts = [u.tier] + ([f"#{week[u.id]} on this week's team board"] if u.id in week and week[u.id] <= 3 else [])             + ([f"{u.current_streak}-day streak"] if u.current_streak >= 3 else [])
        accounts.append({
            "email": p.email, "name": p.name, "tier": u.tier, "points": u.tier_points, "streak": u.current_streak,
            "team": teams[p.team].invite_code if p.team else None, "note": f"{', '.join(facts)}. {p.note}",
        })
    return {
        "accounts": accounts,
        "teams": {g.invite_code: [p.email for p in PEOPLE if p.team == k] for k, g in teams.items()},
        "credit_checks": checks,
        "wiped": wiped,
    }


# --------------------------------------------------------------------------- streaks

def activity_dates(db, user_id: str) -> set[date]:
    """Every UTC day this person did something that counts toward a streak."""
    days: set[date] = set()
    for (when,) in db.query(m.Submission.scored_at).filter(
            m.Submission.user_id == user_id, m.Submission.points > 0):
        days.add(_aware(when).astimezone(UTC).date())
    for (day,) in db.query(m.MicroDeedDone.day).filter(
            m.MicroDeedDone.user_id == user_id, m.MicroDeedDone.points > 0):
        days.add(date.fromisoformat(day))
    return days


def derive_streaks(days: set[date]) -> tuple[int, int, str | None]:
    """(current run ending at the last active day, longest run, last active day)."""
    if not days:
        return 0, 0, None
    ordered = sorted(days)
    longest = run = 1
    for a, b in zip(ordered, ordered[1:]):
        run = run + 1 if (b - a).days == 1 else 1
        longest = max(longest, run)
    current = 1
    for i in range(len(ordered) - 1, 0, -1):
        if (ordered[i] - ordered[i - 1]).days != 1:
            break
        current += 1
    return current, longest, ordered[-1].isoformat()


# --------------------------------------------------------------------------- CLI

def _warm_quest_cache(log=print) -> None:
    """Make sure the map's quest cache for the default location is loaded, so the first
    'discover a quest' on stage is instant. Uses the same code path as GET /quests and only
    calls Google Places when the cache for this spot is missing or stale."""
    from backend.agent_client import find_opportunities
    from backend.config import QUEST_CACHE_TTL_SECONDS
    from backend.database import SessionLocal
    from backend.routers.quests import _cache_key, _cap_for, _replace_cache

    radius = min(50, 10 * 1.609344)  # the frontend's fixed 10-mile search
    key = _cache_key(BALT[0], BALT[1], radius)
    db = SessionLocal()
    try:
        rows = db.query(m.Opportunity).filter(m.Opportunity.cache_key == key).all()
        newest = max((_aware(r.cached_at) for r in rows if r.cached_at), default=None)
        fresh = newest is not None and newest > datetime.now(UTC) - timedelta(seconds=QUEST_CACHE_TTL_SECONDS)
        if fresh:
            log(f"  quest cache for the default location is warm ({len(rows)} places)")
            return
        found = find_opportunities(BALT[0], BALT[1], radius, max_results=_cap_for(radius), include_website=True)
        if found:
            _replace_cache(db, key, found)
            db.commit()
            log(f"  quest cache loaded: {len(found)} places near the default location")
        else:
            log("  quest cache not loaded (no results); the first map open will fetch live")
    except Exception as exc:  # never fail a seed over a cache
        db.rollback()
        log(f"  quest cache not loaded ({exc.__class__.__name__}); the first map open will fetch live")
    finally:
        db.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--no-warm", action="store_true", help="skip pre-loading the quest cache")
    ap.add_argument("--no-verify", action="store_true", help="skip the read-back verification report")
    args = ap.parse_args()

    from backend.database import Base, SessionLocal, engine
    from backend.migrate import backfill_coins, ensure_schema

    print(f"Seeding {engine.url.render_as_string(hide_password=True)}")
    # The same additive setup the app runs at startup, so a database the app has not
    # started against yet (or one behind on columns) is ready before we write to it.
    Base.metadata.create_all(bind=engine)
    ensure_schema(engine)
    backfill_coins(engine)
    db = SessionLocal()
    try:
        summary = seed(db)
    finally:
        db.close()
    if not args.no_warm:
        _warm_quest_cache()

    if not args.no_verify:
        import verify_demo

        print()
        ok = verify_demo.report(summary)
        if not ok:
            sys.exit(1)


if __name__ == "__main__":
    main()
