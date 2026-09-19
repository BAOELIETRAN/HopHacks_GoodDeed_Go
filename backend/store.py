"""The points store: cosmetic avatars, and eggs that hatch into animals.

Three ideas hold this together.

**Coins are not tier points.** ``User.tier_points`` is a lifetime record --
it drives the tier ladder, the leaderboard, and how far Sprout has grown in
companion.js. Spending it would mean buying a hat demotes you from Gold and
shrinks your companion, which is nonsense. So every point-earning path now
credits ``User.coins`` by the same amount, and only coins are ever spent.
The two numbers start equal and drift apart exactly as much as someone
shops.

**An egg is earned twice.** Coins buy it, but deeds hatch it: an egg needs
``hatches_after`` more good deeds before it opens. That keeps the collection
loop pointed back at the thing the app is actually for, rather than at
grinding a balance.

**The reveal is a moment.** Hatching is a request the user makes, not a
background job -- the egg sits at "ready" until they tap it. The species is
rolled at hatch time, not at purchase, so nothing is knowable in advance.

Catalogs live here as plain data next to the frame list in gamification.py,
for the same reason: a cosmetic is content, not schema, and adding one
should never mean a migration.
"""

from __future__ import annotations

import random
from typing import Any

from sqlalchemy.orm import Session as DbSession

from . import db_models as m

# --- rarity ---------------------------------------------------------------

#: Display metadata per rarity. ``tint`` is used by the UI for the card edge
#: and the reveal flash.
RARITIES: dict[str, dict[str, Any]] = {
    "common":    {"label": "Common",    "tint": "#8aa0b4"},
    "uncommon":  {"label": "Uncommon",  "tint": "#5cba86"},
    "rare":      {"label": "Rare",      "tint": "#5b9ddb"},
    "legendary": {"label": "Legendary", "tint": "#e0a92a"},
}

RARITY_ORDER = ["common", "uncommon", "rare", "legendary"]


# --- catalogs -------------------------------------------------------------

#: Cosmetic avatars. Emoji rather than image assets, matching the everyday
#: deeds list -- nothing to host, nothing to load, legible at any size.
AVATARS: list[dict[str, Any]] = [
    {"code": "av_sprout",   "label": "Sprout Cap",    "price": 60,   "emoji": "🌱", "tint": "#5cba86",
     "blurb": "Where everyone starts."},
    {"code": "av_sun",      "label": "Sun Hat",       "price": 120,  "emoji": "🌞", "tint": "#e8bd5c",
     "blurb": "For long shifts outdoors."},
    {"code": "av_wave",     "label": "Tidewalker",    "price": 200,  "emoji": "🌊", "tint": "#5b9ddb",
     "blurb": "Earned on beach cleanups."},
    {"code": "av_bloom",    "label": "Bloom",         "price": 320,  "emoji": "🌸", "tint": "#e88fb4",
     "blurb": "Something you planted came up."},
    {"code": "av_lantern",  "label": "Lantern",       "price": 480,  "emoji": "🏮", "tint": "#e07a5f",
     "blurb": "You show up when it's dark out."},
    {"code": "av_comet",    "label": "Comet",         "price": 750,  "emoji": "☄️", "tint": "#9b7ede",
     "blurb": "Rare air. People notice."},
    {"code": "av_crown",    "label": "Quiet Crown",   "price": 1200, "emoji": "👑", "tint": "#edc45e",
     "blurb": "For the ones who never mention it."},
]

#: Egg tiers. A pricier egg does not hatch sooner -- it hatches *better*.
#: ``odds`` are relative weights over RARITY_ORDER.
EGGS: list[dict[str, Any]] = [
    {
        "code": "egg_mossy", "label": "Mossy Egg", "price": 150, "emoji": "🥚",
        "tint": "#8fd0a1", "hatches_after": 2,
        "blurb": "Warm to the touch. Two more deeds and it opens.",
        "odds": {"common": 70, "uncommon": 25, "rare": 5, "legendary": 0},
    },
    {
        "code": "egg_speckled", "label": "Speckled Egg", "price": 400, "emoji": "🥚",
        "tint": "#5b9ddb", "hatches_after": 4,
        "blurb": "Heavier than it looks. Better odds inside.",
        "odds": {"common": 40, "uncommon": 35, "rare": 22, "legendary": 3},
    },
    {
        "code": "egg_gilded", "label": "Gilded Egg", "price": 900, "emoji": "🥚",
        "tint": "#e0a92a", "hatches_after": 6,
        "blurb": "Something unusual is in here. Six deeds to find out.",
        "odds": {"common": 15, "uncommon": 30, "rare": 40, "legendary": 15},
    },
]

#: The animal pool, grouped by rarity. Rolled at hatch time.
ANIMALS: dict[str, list[dict[str, str]]] = {
    "common": [
        {"code": "an_sparrow",  "label": "Sparrow",       "emoji": "🐦"},
        {"code": "an_frog",     "label": "Pond Frog",     "emoji": "🐸"},
        {"code": "an_mouse",    "label": "Field Mouse",   "emoji": "🐭"},
        {"code": "an_bee",      "label": "Honeybee",      "emoji": "🐝"},
        {"code": "an_snail",    "label": "Garden Snail",  "emoji": "🐌"},
    ],
    "uncommon": [
        {"code": "an_hedgehog", "label": "Hedgehog",      "emoji": "🦔"},
        {"code": "an_turtle",   "label": "River Turtle",  "emoji": "🐢"},
        {"code": "an_otter",    "label": "Otter",         "emoji": "🦦"},
        {"code": "an_owl",      "label": "Barn Owl",      "emoji": "🦉"},
    ],
    "rare": [
        {"code": "an_fox",      "label": "Red Fox",       "emoji": "🦊"},
        {"code": "an_deer",     "label": "Fallow Deer",   "emoji": "🦌"},
        {"code": "an_wolf",     "label": "Grey Wolf",     "emoji": "🐺"},
        {"code": "an_peacock",  "label": "Peacock",       "emoji": "🦚"},
    ],
    "legendary": [
        {"code": "an_dragon",   "label": "Moss Dragon",   "emoji": "🐉"},
        {"code": "an_phoenix",  "label": "Ember Phoenix", "emoji": "🔥"},
        {"code": "an_unicorn",  "label": "White Hart",    "emoji": "🦄"},
    ],
}

#: code -> catalog entry, for both kinds. Built once; the catalogs are static.
_BY_CODE: dict[str, dict[str, Any]] = {
    **{a["code"]: {**a, "kind": "avatar"} for a in AVATARS},
    **{e["code"]: {**e, "kind": "egg"} for e in EGGS},
}

_ANIMAL_BY_CODE: dict[str, dict[str, str]] = {
    a["code"]: {**a, "rarity": rarity}
    for rarity, pool in ANIMALS.items()
    for a in pool
}


def catalog_item(code: str) -> dict[str, Any] | None:
    """The store entry for a code, or None if it is not for sale."""
    return _BY_CODE.get(code)


def animal(code: str) -> dict[str, str] | None:
    """The animal a hatched egg turned into."""
    return _ANIMAL_BY_CODE.get(code)


# --- rolling --------------------------------------------------------------

def roll_rarity(odds: dict[str, int], rng: random.Random | None = None) -> str:
    """Pick a rarity from relative weights.

    ``rng`` is injectable so tests can pin the outcome; production uses the
    module-level generator, which is seeded by the OS.
    """
    r = rng or random
    pool = [k for k in RARITY_ORDER if odds.get(k, 0) > 0]
    weights = [odds[k] for k in pool]
    if not pool:
        return "common"
    return r.choices(pool, weights=weights, k=1)[0]


def roll_animal(egg_code: str, rng: random.Random | None = None) -> dict[str, str]:
    """Roll one animal for an egg, weighted by that egg's odds."""
    r = rng or random
    entry = _BY_CODE.get(egg_code) or {}
    odds = entry.get("odds") or {"common": 1}
    rarity = roll_rarity(odds, rng=r)
    pool = ANIMALS.get(rarity) or ANIMALS["common"]
    picked = r.choice(pool)
    return {**picked, "rarity": rarity}


# --- deed counting --------------------------------------------------------

def deeds_done(db: DbSession, user_id: str) -> int:
    """How many good deeds this user has to their name.

    Verified submissions plus completed everyday deeds. Both are things the
    user actually *did*; coins spent and points held are deliberately not in
    here, so an egg can never be hatched by shopping.

    This is a snapshot, not a ledger: deleting a submission lowers it, which
    is why egg progress is clamped at zero rather than trusted to only grow.
    """
    verified = (
        db.query(m.Submission)
        .filter(m.Submission.user_id == user_id, m.Submission.points > 0)
        .count()
    )
    micro = db.query(m.MicroDeedDone).filter(m.MicroDeedDone.user_id == user_id).count()
    return verified + micro


def egg_progress(item: m.OwnedItem, deeds: int) -> tuple[int, int]:
    """``(done, needed)`` deeds for this egg, clamped to a sane range."""
    needed = max(1, item.hatches_after or 1)
    done = max(0, deeds - (item.deeds_at_purchase or 0))
    return min(done, needed), needed


def is_ready(item: m.OwnedItem, deeds: int) -> bool:
    """True when an unhatched egg has met its deed requirement."""
    if item.kind != "egg" or item.state != "incubating":
        return False
    done, needed = egg_progress(item, deeds)
    return done >= needed


# --- serialization --------------------------------------------------------

def item_out(item: m.OwnedItem, deeds: int) -> dict[str, Any]:
    """One owned item, shaped for the portfolio.

    A hatched egg is presented as the animal it became -- the egg is the
    wrapper, the animal is the thing you own -- while an unhatched one keeps
    the egg's own art and carries its progress.
    """
    entry = catalog_item(item.code) or {}
    base = {
        "id": item.id,
        "kind": item.kind,
        "code": item.code,
        "acquired_at": item.acquired_at.isoformat() if item.acquired_at else None,
    }

    if item.kind == "avatar":
        return {
            **base,
            "label": entry.get("label", item.code),
            "emoji": entry.get("emoji", "❔"),
            "tint": entry.get("tint", "#8aa0b4"),
            "rarity": None,
            "state": "owned",
        }

    if item.state == "hatched":
        beast = animal(item.hatched_code or "") or {}
        rarity = item.rarity or beast.get("rarity") or "common"
        return {
            **base,
            "label": beast.get("label", "Something"),
            "emoji": beast.get("emoji", "❔"),
            "tint": RARITIES.get(rarity, {}).get("tint", "#8aa0b4"),
            "rarity": rarity,
            "rarity_label": RARITIES.get(rarity, {}).get("label", rarity.title()),
            "state": "hatched",
            "from_egg": entry.get("label", "Egg"),
            # ``code`` stays the egg's, so the purchase is still identifiable.
            # The species needs its own field or a client cannot tell two of
            # the same animal from two different ones.
            "species_code": item.hatched_code,
        }

    done, needed = egg_progress(item, deeds)
    return {
        **base,
        "label": entry.get("label", "Egg"),
        "emoji": entry.get("emoji", "🥚"),
        "tint": entry.get("tint", "#8fd0a1"),
        "rarity": None,
        "state": "incubating",
        "progress": done,
        "needed": needed,
        "ready": done >= needed,
    }


def catalog_out(owned_codes: set[str], coins: int) -> dict[str, Any]:
    """The full shop front.

    Avatars are one-per-account, so an owned one is flagged rather than
    hidden -- a collection you can see the shape of is the point. Eggs are
    always buyable; owning six is fine.
    """
    return {
        "coins": coins,
        "avatars": [
            {
                **a,
                "kind": "avatar",
                "owned": a["code"] in owned_codes,
                "affordable": coins >= a["price"],
            }
            for a in AVATARS
        ],
        "eggs": [
            {
                **e,
                "kind": "egg",
                "owned": False,          # eggs are consumable, never "owned out"
                "affordable": coins >= e["price"],
                "odds_pct": _odds_pct(e["odds"]),
            }
            for e in EGGS
        ],
        "rarities": [
            {"key": k, **RARITIES[k]} for k in RARITY_ORDER
        ],
    }


def _odds_pct(odds: dict[str, int]) -> list[dict[str, Any]]:
    """Relative weights as display percentages, so the drop table is honest."""
    total = sum(odds.values()) or 1
    return [
        {
            "key": k,
            "label": RARITIES[k]["label"],
            "tint": RARITIES[k]["tint"],
            "pct": round(odds.get(k, 0) * 100 / total, 1),
        }
        for k in RARITY_ORDER
        if odds.get(k, 0) > 0
    ]
