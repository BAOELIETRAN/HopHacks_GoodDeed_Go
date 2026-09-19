"""Pydantic request/response shapes.

Contract fields (Submission, Opportunity, Score result, Community report) are
named and typed exactly per the team-wide spec. Everything else (auth,
leaderboard rows, friend groups) is backend-internal and free to shape as
needed.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from .textclean import public_text


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


class FrameOut(BaseModel):
    code: str
    label: str
    at: int
    ring: str
    unlocked: bool


class UserOut(BaseModel):
    id: str
    name: str
    email: str
    username: Optional[str]
    city: Optional[str]
    avatar_url: Optional[str] = None
    tier: str
    tier_points: int          # the total; the one source of truth
    available_points: int = 0  # tier_points minus anything held in escrow
    escrow_points: int = 0
    points_to_next_tier: Optional[int]
    current_streak: int
    longest_streak: int
    badges: list[BadgeOut]
    frames: list[FrameOut] = []
    frame: Optional[str] = None
    coins: int = 0                       # spendable store balance
    equipped_avatar: Optional[str] = None  # store item code, if any


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
    website: Optional[str] = None


# --- everyday deeds (tap to complete) -------------------------------------

class MicroDeedOut(BaseModel):
    id: str
    text: str
    icon: str
    points: int
    theme: str
    done: bool = False


class MicroDeedTodayOut(BaseModel):
    day: str
    points_today: int
    daily_cap: int
    deeds: list[MicroDeedOut]


class TaskCompleteIn(BaseModel):
    note: Optional[str] = Field(default=None, max_length=280)


class MicroDeedDoneOut(BaseModel):
    deed_id: str
    points: int
    capped: bool          # true when the daily ceiling trimmed the award
    points_today: int
    daily_cap: int
    user_tier: str
    user_tier_points: int
    current_streak: int
    is_personal_best: bool


# --- check-ins (presence-verified sessions) -------------------------------

class CheckInStart(BaseModel):
    """Where the user is, and which org they say they're at. The server
    checks the two against each other before starting a clock."""

    org_name: str = Field(min_length=1, max_length=255)
    org_lat: float
    org_lng: float
    lat: float          # the user's current position
    lng: float
    category: Optional[str] = None
    quest_type: Optional[Literal["daily", "monthly"]] = "daily"


class HeartbeatIn(BaseModel):
    lat: float
    lng: float


class CheckInOut(BaseModel):
    checkin_id: str
    org_name: str
    org_lat: float
    org_lng: float
    category: Optional[str]
    quest_type: Literal["daily", "monthly"]
    status: Literal["active", "done", "abandoned"]
    started_at: str
    elapsed_seconds: int
    elapsed_minutes: int
    end_reason: Optional[str]      # completed | left_area | timed_out | too_long
    estimated_points: int
    checkin_radius_m: int
    leave_radius_m: int
    already_submitted: bool


# --- submissions ----------------------------------------------------------

class DeedTypeOut(BaseModel):
    """One selectable kind of good deed, and what it asks of the user."""

    key: str
    label: str
    icon: str
    blurb: str
    evidence: str
    photo_required: bool
    time_required: bool
    location_required: bool
    base_points: int
    max_points: int


class SubmissionCreate(BaseModel):
    """Everything in the Submission contract except user_id, which comes
    from the bearer token so a user can't submit on someone else's behalf."""

    # Which kind of deed. Drives what evidence is expected, which rubric
    # the AI uses, and the point scale.
    deed_type: str = "volunteer"
    org_name: str = ""
    # Optional: kindness and advocacy accept a description alone.
    photo_url: str = ""
    description: str = ""
    # Ignored when checkin_id is supplied -- the measured time wins.
    time_spent_minutes: int = Field(default=0, ge=0)
    lat: float
    lng: float
    submitted_at: str
    # A finished presence-verified session. When present, minutes come from
    # the server's clock and the submission is marked verified.
    checkin_id: Optional[str] = None
    # Optional correction to the measured time, e.g. "I left the timer
    # running through lunch". Only ever downward -- letting someone revise
    # upward would hand back exactly the unverifiable claim the timer
    # exists to remove.
    adjusted_minutes: Optional[int] = Field(default=None, ge=0)


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
    verified_presence: bool = False
    deed_type: str = "volunteer"

    @field_validator("rationale")
    @classmethod
    def _no_placeholder_text(cls, value: str) -> str:
        return public_text(value, "Reviewed automatically.") or ""


# --- activity feed, reactions, comments -----------------------------------

class CommentOut(BaseModel):
    id: str
    user_id: str
    user_name: str
    text: str
    created_at: str
    is_mine: bool


class ReactionSummary(BaseModel):
    emoji: str
    count: int
    mine: bool          # did the requester leave this one


class FeedItem(BaseModel):
    """One scored deed in the friends feed.

    Deliberately omits photo_url: proof photos can show faces and locations,
    and the person logging a deed did not consent to broadcasting the image
    to their whole group. The deed type, org and rationale carry the story.
    """

    submission_id: str
    user_id: str
    user_name: str
    user_avatar: Optional[str]
    user_tier: str
    deed_type: str
    org_name: str
    description: str
    points: int
    verified_presence: bool
    created_at: str
    is_mine: bool
    reactions: list[ReactionSummary]
    comments: list[CommentOut]
    comment_count: int


class ReactIn(BaseModel):
    emoji: str = Field(min_length=1, max_length=8)


class CommentIn(BaseModel):
    text: str = Field(min_length=1, max_length=280)


# --- campaign marketplace -------------------------------------------------

class CampaignCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    donation_url: str = Field(min_length=8, max_length=1024)
    platforms: list[str] = Field(min_length=1, max_length=3)
    bounty: int = Field(ge=1, le=1000)
    note: str = Field(default="", max_length=500)
    expires_in_days: Optional[int] = Field(default=7, ge=1, le=30)


class CampaignProofIn(BaseModel):
    photo_url: str = Field(min_length=8)
    note: str = Field(default="", max_length=280)


class CampaignOut(BaseModel):
    campaign_id: str
    title: str
    donation_url: str
    note: str
    platforms: list[str]
    bounty: int
    status: Literal["open", "claimed", "done", "cancelled", "expired"]
    created_at: str
    expires_at: Optional[str]
    # What the link check found, so a poster can see why theirs was refused.
    link_ok: bool
    link_org: Optional[str]
    link_note: Optional[str]

    @field_validator("link_note")
    @classmethod
    def _no_placeholder_text(cls, value: Optional[str]) -> Optional[str]:
        return public_text(value)
    # Relationship to the requester. Claimer identity is never broadcast.
    is_mine: bool
    claimed_by_me: bool
    awaiting_review: bool


class TransactionOut(BaseModel):
    id: str
    kind: Literal["escrow", "payout", "refund"]
    amount: int
    campaign_id: Optional[str]
    direction: Literal["in", "out", "hold"]
    counterparty: Optional[str]     # display name, or None
    note: str
    created_at: str


class WalletOut(BaseModel):
    total_points: int
    available_points: int
    escrow_points: int
    transactions: list[TransactionOut]


# --- weekly recap ---------------------------------------------------------

class WeeklyRecapOut(BaseModel):
    """Last seven days, summarised.

    A zero week is a normal outcome, not an error: `deed_count == 0` with
    an encouraging `headline` is the expected shape, and the client must not
    treat it as an empty state to hide.
    """

    week_start: str
    week_end: str
    deed_count: int
    points: int
    micro_deed_count: int
    best_day: Optional[str]          # ISO date with the most points
    top_deed_type: Optional[str]
    tier: str
    tier_points: int          # the total; the one source of truth
    available_points: int = 0  # tier_points minus anything held in escrow
    escrow_points: int = 0
    points_to_next_tier: Optional[int]
    tier_changed: bool               # crossed a tier during the week
    current_streak: int
    friend_rank: Optional[int]       # position among friends this week
    friend_count: int
    headline: str                    # one line, written server-side
    subline: str


# --- leaderboard ------------------------------------------------------

class LeaderboardEntry(BaseModel):
    rank: int
    user_id: str
    name: str
    points: int
    deed_count: int
    is_you: bool
    # The kinds of deed behind those points, most frequent first. Shown as
    # small icons so the board says what people did, not just how much.
    deed_types: list[str] = []


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
    # How many helpers the poster wants. One is the common case; the cap
    # keeps a single post from swallowing a whole neighbourhood's effort.
    total_slots: int = Field(default=1, ge=1, le=10)


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
    # What each helper earned on confirmation, and what the poster earned for
    # reporting it. Both are set the moment the poster confirms, never one
    # without the other.
    points_awarded: Optional[int]
    reporter_points_awarded: Optional[int] = None
    award_rationale: Optional[str] = None
    # Who is looking, so the UI can pick the right action without re-deriving
    # it from ids on every card.
    is_mine: bool = False          # the requester posted it
    claimed_by_me: bool = False    # the requester claimed it
    # Slot counts only. Helper identities are never sent to any client --
    # see db_models.ReportHelper for why.
    total_slots: int = 1
    filled_slots: int = 0
    slots_left: int = 1
    is_full: bool = False
    # When an untouched claim returns to the feed, so the claimant can see a
    # countdown instead of silently losing it.
    claim_expires_at: Optional[str] = None

    @field_validator("award_rationale")
    @classmethod
    def _no_placeholder_text(cls, value: Optional[str]) -> Optional[str]:
        return public_text(value)


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


# --- store ----------------------------------------------------------------

class StoreBuy(BaseModel):
    code: str


class EquipIn(BaseModel):
    # Null un-equips and falls back to the user's photo or initials.
    code: Optional[str] = None


class OwnedItemOut(BaseModel):
    """One row of the portfolio.

    Loosely typed on purpose: an avatar, an incubating egg and a hatched
    animal are one list in the UI, and the fields that differ (progress,
    rarity) are optional rather than split across three response models the
    screen would have to branch on.
    """

    id: str
    kind: str                    # avatar | egg
    code: str
    label: str
    emoji: str
    tint: str
    state: str                   # owned | incubating | hatched
    acquired_at: Optional[str] = None
    rarity: Optional[str] = None
    rarity_label: Optional[str] = None
    from_egg: Optional[str] = None
    species_code: Optional[str] = None   # the animal, once hatched
    progress: Optional[int] = None
    needed: Optional[int] = None
    ready: Optional[bool] = None


class PortfolioOut(BaseModel):
    coins: int
    equipped_avatar: Optional[str] = None
    deeds_done: int
    items: list[OwnedItemOut]
    animals_collected: int
    animals_total: int


class StoreCatalogOut(BaseModel):
    coins: int
    avatars: list[dict]
    eggs: list[dict]
    rarities: list[dict]


class HatchOut(BaseModel):
    """The reveal. ``item`` is the row as it now reads -- a hatched animal."""

    item: OwnedItemOut
    rarity: str
    rarity_label: str
    is_new_species: bool
