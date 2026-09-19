"""Shared data shapes for GoodDeed Go.

These mirror the team-wide data contract exactly. The field names are load
bearing -- the backend persists them and the UI reads them -- so do not rename
them. Every dataclass exposes ``to_dict()`` which produces plain JSON-safe
values, which is what crosses the boundary to the backend.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Optional

QuestType = Literal["daily", "monthly"]
ReportStatus = Literal["open", "claimed", "done"]
Tier = Literal["Bronze", "Silver", "Gold"]


@dataclass
class Opportunity:
    """A real-world place a quest can be attached to."""

    org_name: str
    address: str
    lat: float
    lng: float
    category: str
    legitimacy_score: float  # 0-1
    quest_type: QuestType

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScoreResult:
    """The result of grading one submission.

    ``points`` is what lands on the daily/weekly leaderboards (it includes the
    quest-type multiplier). ``tier_points`` is the slice that counts toward the
    cumulative Bronze/Silver/Gold total and deliberately excludes multipliers,
    so a bonus event can't fast-track someone to Gold. With the default
    multiplier of 1.0 the two are equal.
    """

    points: int
    tier_points: int
    authenticity_confidence: float  # 0-1
    rationale: str
    debug: Optional[dict[str, Any]] = field(default=None, repr=False)

    def to_dict(self, include_debug: bool = False) -> dict[str, Any]:
        out: dict[str, Any] = {
            "points": self.points,
            "tier_points": self.tier_points,
            "authenticity_confidence": self.authenticity_confidence,
            "rationale": self.rationale,
        }
        if include_debug and self.debug is not None:
            out["debug"] = self.debug
        return out


@dataclass
class TrustResult:
    """Whether an organization looks real enough to hand out quests for."""

    legit: bool
    confidence: float  # 0-1
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReportClassification:
    """Triage for a user-submitted "this needs fixing" photo."""

    category: str
    is_valid: bool
    confidence: float = 0.0
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        # `category` and `is_valid` are the contract; the other two are extra
        # context that consumers may ignore.
        return asdict(self)
