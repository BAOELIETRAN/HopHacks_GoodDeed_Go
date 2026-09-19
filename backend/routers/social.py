"""The friends activity feed, and reacting to what's on it.

Doing good alone is a chore; seeing that three people you know did something
this week is the thing that actually brings people back. This is the social
layer over submissions that already exist -- no new scoring, no new points.

Two deliberate limits:

* **Reactions come from a fixed set.** A free-text emoji field is an
  unmoderated message channel with extra steps, and there is no moderation
  here to back one.
* **The feed carries no photos.** A proof photo can show a face, a home or a
  workplace, and someone logging a deed did not agree to broadcast that
  image to their whole group. The deed type, organization and the AI's own
  rationale tell the story without it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session as DbSession

from .. import db_models as m
from ..database import get_db
from ..deps import get_current_user
from ..schemas import CommentIn, CommentOut, FeedItem, ReactIn, ReactionSummary

router = APIRouter(tags=["social"])

#: The reactions people can leave. Warm only -- there is no thumbs-down,
#: because a volunteering app does not need a mechanism for discouraging
#: someone who just spent their Saturday at a shelter.
ALLOWED_EMOJI = ("👏", "❤️", "🔥", "🙌", "💪")

FEED_DAYS = 14
COMMENT_PREVIEW = 3


def _friend_ids(db: DbSession, user: m.User) -> list[str]:
    """Everyone whose deeds this user can see: their group, plus themselves.

    No group yet means a feed of one, which is a real state and reads fine
    -- better than an empty screen that looks broken.
    """
    if not user.friend_group_id:
        return [user.id]
    members = (
        db.query(m.User.id).filter(m.User.friend_group_id == user.friend_group_id).all()
    )
    return [row[0] for row in members] or [user.id]


def _iso(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).isoformat()


def _build_items(db: DbSession, viewer: m.User, subs: list[m.Submission]) -> list[FeedItem]:
    """Assemble feed rows, fetching reactions, comments and users in bulk.

    One query per related table rather than per submission: a 30-item feed
    was otherwise ~90 round trips to a hosted Postgres.
    """
    if not subs:
        return []
    sub_ids = [s.id for s in subs]

    users = {
        u.id: u
        for u in db.query(m.User).filter(
            m.User.id.in_({s.user_id for s in subs})
        )
    }

    reactions: dict[str, list[m.Reaction]] = {}
    for r in db.query(m.Reaction).filter(m.Reaction.submission_id.in_(sub_ids)):
        reactions.setdefault(r.submission_id, []).append(r)

    comments: dict[str, list[m.Comment]] = {}
    for c in (
        db.query(m.Comment)
        .filter(m.Comment.submission_id.in_(sub_ids))
        .order_by(m.Comment.created_at.asc())
    ):
        comments.setdefault(c.submission_id, []).append(c)

    commenter_ids = {c.user_id for cs in comments.values() for c in cs}
    commenters = {
        u.id: u for u in db.query(m.User).filter(m.User.id.in_(commenter_ids))
    } if commenter_ids else {}

    items: list[FeedItem] = []
    for sub in subs:
        author = users.get(sub.user_id)
        subs_reactions = reactions.get(sub.id, [])

        grouped: dict[str, list[m.Reaction]] = {}
        for r in subs_reactions:
            grouped.setdefault(r.emoji, []).append(r)

        all_comments = comments.get(sub.id, [])
        items.append(
            FeedItem(
                submission_id=sub.id,
                user_id=sub.user_id,
                user_name=author.name if author else "Someone",
                user_avatar=author.avatar_url if author else None,
                user_tier=author.tier if author else "Bronze",
                deed_type=sub.deed_type or "volunteer",
                org_name=sub.org_name or "",
                description=sub.description or "",
                points=sub.points,
                verified_presence=bool(sub.verified_presence),
                created_at=_iso(sub.scored_at),
                is_mine=sub.user_id == viewer.id,
                reactions=[
                    ReactionSummary(
                        emoji=emoji,
                        count=len(rs),
                        mine=any(r.user_id == viewer.id for r in rs),
                    )
                    for emoji, rs in sorted(grouped.items(), key=lambda kv: -len(kv[1]))
                ],
                comments=[
                    CommentOut(
                        id=c.id,
                        user_id=c.user_id,
                        user_name=(commenters.get(c.user_id).name if commenters.get(c.user_id) else "Someone"),
                        text=c.text,
                        created_at=_iso(c.created_at),
                        is_mine=c.user_id == viewer.id,
                    )
                    # Show the most recent few; the count carries the rest.
                    for c in all_comments[-COMMENT_PREVIEW:]
                ],
                comment_count=len(all_comments),
            )
        )
    return items


@router.get("/feed", response_model=list[FeedItem])
def activity_feed(
    limit: int = Query(default=30, ge=1, le=100),
    since: str | None = Query(default=None, description="ISO timestamp; only newer items"),
    db: DbSession = Depends(get_db),
    user: m.User = Depends(get_current_user),
) -> list[FeedItem]:
    """Recent scored deeds from your group.

    Zero-point submissions are excluded: a rejected photo is a private
    matter between the user and the scorer, not something to broadcast.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=FEED_DAYS)
    query = (
        db.query(m.Submission)
        .filter(
            m.Submission.user_id.in_(_friend_ids(db, user)),
            m.Submission.points > 0,
            m.Submission.scored_at >= cutoff,
        )
        .order_by(m.Submission.scored_at.desc())
    )

    if since:
        try:
            after = datetime.fromisoformat(since.replace("Z", "+00:00"))
            if after.tzinfo is None:
                after = after.replace(tzinfo=timezone.utc)
            query = query.filter(m.Submission.scored_at > after)
        except ValueError:
            raise HTTPException(status_code=400, detail="`since` must be an ISO timestamp")

    return _build_items(db, user, query.limit(limit).all())


def _visible_submission(db: DbSession, user: m.User, submission_id: str) -> m.Submission:
    sub = db.get(m.Submission, submission_id)
    if sub is None or sub.user_id not in _friend_ids(db, user):
        # Same response either way: "not in your feed" and "does not exist"
        # should be indistinguishable, or this endpoint probes other groups.
        raise HTTPException(status_code=404, detail="That deed isn't in your feed")
    return sub


@router.post("/feed/{submission_id}/react", response_model=FeedItem)
def toggle_reaction(
    submission_id: str,
    body: ReactIn,
    db: DbSession = Depends(get_db),
    user: m.User = Depends(get_current_user),
) -> FeedItem:
    """Add or remove one reaction. Tapping the same emoji again undoes it."""
    if body.emoji not in ALLOWED_EMOJI:
        raise HTTPException(
            status_code=400, detail=f"Pick one of {' '.join(ALLOWED_EMOJI)}"
        )
    sub = _visible_submission(db, user, submission_id)

    existing = (
        db.query(m.Reaction)
        .filter(
            m.Reaction.submission_id == submission_id,
            m.Reaction.user_id == user.id,
            m.Reaction.emoji == body.emoji,
        )
        .first()
    )
    if existing:
        db.delete(existing)
    else:
        db.add(m.Reaction(submission_id=submission_id, user_id=user.id, emoji=body.emoji))
    db.commit()

    return _build_items(db, user, [sub])[0]


@router.post("/feed/{submission_id}/comment", response_model=FeedItem)
def add_comment(
    submission_id: str,
    body: CommentIn,
    db: DbSession = Depends(get_db),
    user: m.User = Depends(get_current_user),
) -> FeedItem:
    sub = _visible_submission(db, user, submission_id)
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Write something first")

    db.add(m.Comment(submission_id=submission_id, user_id=user.id, text=text))
    db.commit()
    return _build_items(db, user, [sub])[0]


@router.delete("/feed/comments/{comment_id}", status_code=204)
def delete_comment(
    comment_id: str,
    db: DbSession = Depends(get_db),
    user: m.User = Depends(get_current_user),
) -> None:
    comment = db.get(m.Comment, comment_id)
    if comment is None:
        return  # already gone; deleting twice is not an error
    sub = db.get(m.Submission, comment.submission_id)
    # Your own comment, or any comment on your own deed.
    if comment.user_id != user.id and not (sub and sub.user_id == user.id):
        raise HTTPException(status_code=403, detail="That isn't yours to delete")
    db.delete(comment)
    db.commit()
