"""SQLAlchemy ORM models.

Field names on ``Submission``, ``Opportunity``, and ``Report`` mirror the
team-wide data contract (see the top-level README/spec) so a row can be
handed straight to the agent or serialized straight to the UI without
renaming. Columns not in the contract (ids, cache bookkeeping, server
timestamps, auth) are additions the backend needs internally.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    # Nullable: a Google-only account never sets a password. Email/password
    # signup still requires both -- that is enforced in the auth router.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_salt: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Google's stable subject id. Matched on before email, because a person
    # can change their Google email address but never their sub.
    google_sub: Mapped[str | None] = mapped_column(
        String(64), unique=True, index=True, nullable=True
    )
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    # Profile display fields (Figma profile screen: "@mayadoesgood", "Oakland").
    # Both optional -- no uniqueness/slug logic, keep signup simple.
    username: Mapped[str | None] = mapped_column(String(40), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # Last known location, set whenever the user submits a deed. Used for the
    # "nearby" leaderboard scope, which has no lat/lng of its own.
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Cumulative tier_points across all submissions -- what Bronze/Silver/Gold
    # is computed from. Deliberately excludes quest multipliers.
    tier_points: Mapped[int] = mapped_column(Integer, default=0)
    tier: Mapped[str] = mapped_column(String(16), default="Bronze")

    # Consecutive-day activity streak (Figma: "13-day streak", "🔥12").
    # Advances at most once per calendar day (UTC), on any verified
    # (points > 0) submission or confirmed report proof.
    current_streak: Mapped[int] = mapped_column(Integer, default=0)
    longest_streak: Mapped[int] = mapped_column(Integer, default=0)
    last_active_date: Mapped[str | None] = mapped_column(String(10), nullable=True)  # YYYY-MM-DD

    friend_group_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("friend_groups.id"), nullable=True
    )
    friend_group: Mapped["FriendGroup | None"] = relationship(
        back_populates="members", foreign_keys=[friend_group_id]
    )


class Session(Base):
    """Opaque bearer token -> user. No expiry; this is a hackathon build."""

    __tablename__ = "sessions"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class FriendGroup(Base):
    __tablename__ = "friend_groups"

    # The cause this team is pooling its points toward. See causes.py --
    # this is what stops the app from being a points game with a charity
    # skin: the score is always expressed as something real.
    cause_key: Mapped[str] = mapped_column(String(32), default="meals")

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    invite_code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    created_by: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    members: Mapped[list["User"]] = relationship(
        back_populates="friend_group", foreign_keys=[User.friend_group_id]
    )


class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"), index=True)

    # --- contract fields (Submission) ---
    org_name: Mapped[str] = mapped_column(String(255))
    photo_url: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    time_spent_minutes: Mapped[int] = mapped_column(Integer)
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    submitted_at: Mapped[str] = mapped_column(String(64))  # ISO-8601, as given by the client

    # --- contract fields (Score result) ---
    points: Mapped[int] = mapped_column(Integer)
    tier_points: Mapped[int] = mapped_column(Integer)
    authenticity_confidence: Mapped[float] = mapped_column(Float)
    rationale: Mapped[str] = mapped_column(Text)

    # bookkeeping: server-side receipt time, used for daily/weekly leaderboard
    # windows so a client's clock can't shift which period a score lands in.
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)

    # Set when the minutes came from a presence-verified check-in rather than
    # being typed in. Displayed as a badge and worth a scoring bonus.
    checkin_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    verified_presence: Mapped[bool] = mapped_column(Boolean, default=False)

    # Which kind of good deed this was. See gooddeed_agent/deeds.py -- each
    # type is judged by its own rubric and has its own point scale.
    deed_type: Mapped[str] = mapped_column(String(32), default="volunteer", index=True)


class CheckIn(Base):
    """A presence-verified volunteering session.

    Started only when the user is physically near the organization, and
    timed by the server from location heartbeats. ``elapsed_seconds`` is
    accumulated from heartbeats rather than computed as (end - start), so
    time spent out of range is never credited.
    """

    __tablename__ = "checkins"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"), index=True)

    org_name: Mapped[str] = mapped_column(String(255))
    org_lat: Mapped[float] = mapped_column(Float)
    org_lng: Mapped[float] = mapped_column(Float)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    quest_type: Mapped[str] = mapped_column(String(16), default="daily")

    # active | done | abandoned
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Last heartbeat we accepted as "present", and where it came from.
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_lng: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Credited time, accumulated between in-range heartbeats.
    elapsed_seconds: Mapped[int] = mapped_column(Integer, default=0)

    # Why it ended, shown to the user: completed | left_area | timed_out | too_long
    end_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Set once the session has been turned into a scored submission, so one
    # shift cannot be claimed twice.
    submission_id: Mapped[str | None] = mapped_column(String(32), nullable=True)


class MicroDeedDone(Base):
    """A tap-to-complete everyday deed.

    Kept separate from Submission: these carry no evidence and never touch
    the AI, so mixing them into the submissions table would pollute the
    verified record and the leaderboard's "only verified completions count"
    rule. The unique constraint enforces once-per-task-per-day.
    """

    __tablename__ = "micro_deeds_done"
    __table_args__ = (UniqueConstraint("user_id", "deed_id", "day", name="uq_micro_deed_per_day"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"), index=True)
    deed_id: Mapped[str] = mapped_column(String(40))
    day: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD, local to the server
    points: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Reaction(Base):
    """A friend's emoji response to a logged deed.

    One row per (submission, user, emoji), so a person can leave more than
    one kind of reaction but cannot stack the same one -- the unique
    constraint does that rather than a count column, which would need
    reconciling every time someone un-reacts.

    Allowed emoji are fixed server-side (see routers/social.py). An open
    text field here would be an unmoderated message channel with extra
    steps.
    """

    __tablename__ = "reactions"
    __table_args__ = (
        UniqueConstraint("submission_id", "user_id", "emoji", name="uq_reaction"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    submission_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("submissions.id"), index=True
    )
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"), index=True)
    emoji: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Comment(Base):
    """A short note on someone's logged deed."""

    __tablename__ = "comments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    submission_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("submissions.id"), index=True
    )
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"), index=True)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, index=True
    )


class Opportunity(Base):
    """Cached agent.find_opportunities() results for a (lat, lng, radius) bucket."""

    __tablename__ = "opportunities"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)

    # --- contract fields (Opportunity) ---
    org_name: Mapped[str] = mapped_column(String(255), index=True)
    address: Mapped[str] = mapped_column(String(255))
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    category: Mapped[str] = mapped_column(String(64))
    legitimacy_score: Mapped[float] = mapped_column(Float)
    quest_type: Mapped[str] = mapped_column(String(16))

    # cache bookkeeping
    cache_key: Mapped[str] = mapped_column(String(64), index=True)
    cached_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Report(Base):
    """A community "needs fixing" report.

    Lifecycle: open (posted) -> claimed (someone takes it on) -> claimed with
    proof attached, awaiting the original poster's confirmation -> done (the
    poster confirms, which is also when points post to whoever did the work).
    This last part -- proof + human confirmation -- isn't in the written
    contract but is a clear, consistent workflow across several UI screens
    (the claimed-report detail screen, the community feed's point badges, and
    the profile's "Recent impact" list mixing report and quest credit), so
    the extra columns below support it without touching any contract field.
    """

    __tablename__ = "reports"

    # `id` doubles as the contract's `report_id`.
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    reported_by: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"))

    # --- contract fields (Community report) ---
    photo_url: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16), default="open")
    claimed_by: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[str] = mapped_column(String(64))  # ISO-8601

    # extra context from agent.classify_report -- not in the contract, ignored
    # by consumers that don't want it.
    category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    classification_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    # activity timeline (Figma detail screen shows exactly these three events)
    claimed_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    proof_submitted_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confirmed_at: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # the claimant's "after" photo + write-up, graded the same way a quest
    # submission is (see routers/reports.py complete_report), but only once
    # the original poster confirms.
    proof_photo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    proof_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    proof_time_spent_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    points_awarded: Mapped[int | None] = mapped_column(Integer, nullable=True)
