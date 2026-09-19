"""Pydantic request/response shapes.

Contract fields (Submission, Opportunity, Score result, Community report) are
named and typed exactly per the team-wide spec. Everything else (auth,
leaderboard rows, friend groups) is backend-internal and free to shape as
needed.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


# --- auth --------------------------------------------------------------

class SignupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=6, max_length=255)
    username: Optional[str] = Field(default=None, max_length=40)
    city: Optional[str] = Field(default=None, max_length=120)


class LoginRequest(BaseModel):
    email: str
    password: str


class GoogleAuthRequest(BaseModel):
    """The ID token the Google Identity Services button hands the frontend."""

    credential: str = Field(min_length=20)


class AuthConfigOut(BaseModel):
    """Lets the frontend show the Google button only when it will work."""

    google_enabled: bool
    google_client_id: str


class BadgeOut(BaseModel):
    code: str
    label: str


class UserOut(BaseModel):
    id: str
    name: str
    email: str
    username: Optional[str]
    city: Optional[str]
    avatar_url: Optional[str] = None
    tier: str
    tier_points: int
    points_to_next_tier: Optional[int]
    current_streak: int
    longest_streak: int
    badges: list[BadgeOut]


class AuthResponse(BaseModel):
    token: str
    user: UserOut


# --- quests / opportunities ---------------------------------------------

class OpportunityOut(BaseModel):
    org_name: str
    address: str
    lat: float
    lng: float
    category: str
    legitimacy_score: float
    quest_type: Literal["daily", "monthly"]
    # extras the Figma quest cards/detail screen show, not in the contract
    verified: bool
    estimated_points: int
    distance_km: float


# --- submissions ----------------------------------------------------------

class SubmissionCreate(BaseModel):
    """Everything in the Submission contract except user_id, which comes
    from the bearer token so a user can't submit on someone else's behalf."""

    org_name: str
    photo_url: str
    description: str = ""
    time_spent_minutes: int = Field(ge=0)
    lat: float
    lng: float
    submitted_at: str


class SubmissionOut(BaseModel):
    id: str
    user_id: str
    org_name: str
    photo_url: str
    description: str
    time_spent_minutes: int
    lat: float
    lng: float
    submitted_at: str
    points: int
    tier_points: int
    authenticity_confidence: float
    rationale: str
    user_tier: str
    user_tier_points: int
    current_streak: int
    is_personal_best: bool


# --- leaderboard ------------------------------------------------------

class LeaderboardEntry(BaseModel):
    rank: int
    user_id: str
    name: str
    points: int
    deed_count: int
    is_you: bool


# --- friends ------------------------------------------------------------

class InviteOut(BaseModel):
    invite_code: str


class JoinRequest(BaseModel):
    invite_code: str


class FriendGroupOut(BaseModel):
    invite_code: str
    member_count: int


# --- community reports --------------------------------------------------

class ReportCreate(BaseModel):
    photo_url: str
    description: str = ""
    lat: float
    lng: float


class ReportOut(BaseModel):
    report_id: str
    photo_url: str
    description: str
    lat: float
    lng: float
    status: Literal["open", "claimed", "done"]
    claimed_by: Optional[str]
    created_at: str
    # extras the Figma community feed / detail screens show, not in the contract
    reported_by: str
    reported_by_name: str
    claimed_by_name: Optional[str]
    estimated_points: int
    awaiting_confirmation: bool  # claimed + proof submitted, waiting on the poster
    points_awarded: Optional[int]


class ReportDetailOut(ReportOut):
    """Full activity timeline, for the claimed-report detail screen."""

    claimed_at: Optional[str]
    proof_photo_url: Optional[str]
    proof_description: Optional[str]
    proof_submitted_at: Optional[str]
    confirmed_at: Optional[str]


class ReportProofSubmit(BaseModel):
    photo_url: str
    description: str = ""
    time_spent_minutes: int = Field(ge=0)


class ReportRejected(BaseModel):
    detail: str
    category: str
