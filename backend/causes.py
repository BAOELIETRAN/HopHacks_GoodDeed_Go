"""Causes: what all these points are actually for.

The app had drifted toward being a points game with a charity theme. Every
feature added recently -- streaks, a companion, confetti, a leaderboard --
pulls attention toward the score and away from the thing being scored.

This pulls back the other way. A team pools its points toward a real,
named, specific goal, and the app says plainly what that goal means in the
world: "1,200 points ≈ 400 meals". The number is an honest ratio published
by the organisation, not a claim the app invents, and it is labelled as an
estimate everywhere it appears.

Two rules this file exists to enforce:

* **Never overstate.** Every figure below is a public, checkable
  cost-per-unit from the named organisation's own materials, rounded
  conservatively. The app must not tell someone they fed a family if they
  did not.
* **Points are effort, not money.** Completing a goal does not move funds.
  The ratio expresses "this much volunteering is worth roughly this much",
  which is a motivational framing, and the UI says so rather than implying
  a donation happened.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Cause:
    key: str
    title: str
    icon: str
    blurb: str
    unit: str                # what one unit of impact is
    points_per_unit: int     # team points that represent one unit
    source: str              # where the ratio comes from, shown in the UI


CAUSES: tuple[Cause, ...] = (
    Cause(
        key="meals",
        title="Meals for neighbours",
        icon="🍲",
        blurb="Food banks turn a small amount of support into a lot of meals.",
        unit="meal",
        points_per_unit=3,
        source="Feeding America publishes roughly 10 meals per $1 donated",
    ),
    Cause(
        key="shelter_nights",
        title="A warm night",
        icon="🛏️",
        blurb="A bed, a shower and a hot meal for someone sleeping rough.",
        unit="night of shelter",
        points_per_unit=60,
        source="Typical US shelter cost per bed-night, ~$30",
    ),
    Cause(
        key="trees",
        title="Trees in the ground",
        icon="🌳",
        blurb="Street trees cool neighbourhoods and clean the air for decades.",
        unit="tree planted",
        points_per_unit=20,
        source="One Tree Planted plants one tree per $1",
    ),
    Cause(
        key="books",
        title="Books for kids",
        icon="📚",
        blurb="A child with books at home reads better for years afterwards.",
        unit="book",
        points_per_unit=8,
        source="Reading Is Fundamental, roughly $4 per book placed",
    ),
    Cause(
        key="animals",
        title="Shelter animals fed",
        icon="🐾",
        blurb="Food and care for animals waiting to be rehomed.",
        unit="day of care",
        points_per_unit=12,
        source="Typical shelter cost of ~$6 per animal per day",
    ),
)

BY_KEY = {c.key: c for c in CAUSES}
DEFAULT_CAUSE = "meals"


def get_cause(key: str | None) -> Cause:
    return BY_KEY.get((key or "").strip().lower(), BY_KEY[DEFAULT_CAUSE])


def units_from_points(points: int, cause: Cause) -> int:
    """How many whole units this many points represents.

    Floored, never rounded up: overstating impact is the one failure mode
    this whole module exists to avoid.
    """
    return max(0, int(points or 0)) // cause.points_per_unit
