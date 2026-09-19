"""The donation-promotion marketplace.

Someone with points offers them to whoever will share their cause on
Instagram, Snapchat or TikTok. The bounty is held from the moment the
campaign is posted, so an open campaign always has the points behind it.

Three things this module is careful about:

* **Nothing goes live unchecked.** The link is verified before the campaign
  is visible to anyone. Broadcasting a phishing page to a stranger's
  followers is the worst thing this feature could do.
* **Points are conserved.** Every movement goes through wallet.py and
  writes a transaction row. No balance is ever edited directly here.
* **Expiry is lazy.** Stale campaigns are swept when anyone touches the
  endpoints, which keeps held points from being stranded without needing a
  scheduler.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session as DbSession

from gooddeed_agent import PLATFORMS, verify_donation_link
from gooddeed_agent.vision import score_campaign_proof

from .. import db_models as m
from ..database import get_db
from ..deps import get_current_user
from ..schemas import (
    CampaignCreate,
    CampaignOut,
    CampaignProofIn,
    TransactionOut,
    WalletOut,
)
from ..wallet import available, hold, pay_out, release

router = APIRouter(tags=["marketplace"])

#: How long a claim holds before the campaign returns to the board. Long
#: enough to actually make a post, short enough that a forgotten claim does
#: not park someone else's points indefinitely.
CLAIM_HOURS = 24


def _aware(dt):
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso(dt) -> str | None:
    d = _aware(dt)
    return d.isoformat() if d else None


def sweep(db: DbSession) -> None:
    """Expire stale campaigns and release abandoned claims.

    Run on every read. A held bounty that nobody can claim is the worst
    state this system can be in, so the recovery path is the common path.
    """
    now = datetime.now(timezone.utc)
    changed = False

    for c in db.query(m.Campaign).filter(m.Campaign.status.in_(("open", "claimed"))):
        expires = _aware(c.expires_at)
        claimed = _aware(c.claimed_at)

        if c.status == "claimed" and claimed and now - claimed > timedelta(hours=CLAIM_HOURS):
            # The claimer never posted. Back on the board, bounty still held.
            c.status = "open"
            c.claimed_by = None
            c.claimed_at = None
            changed = True
            continue

        if expires and now > expires and c.status == "open":
            poster = db.get(m.User, c.poster_id)
            if poster:
                release(db, poster, c.bounty, c.id, "Campaign expired unclaimed")
            c.status = "expired"
            changed = True

    if changed:
        db.commit()


def _to_out(c: m.Campaign, viewer: m.User) -> CampaignOut:
    return CampaignOut(
        campaign_id=c.id,
        title=c.title,
        donation_url=c.donation_url,
        note=c.note or "",
        platforms=[p for p in (c.platforms or "").split(",") if p],
        bounty=c.bounty,
        status=c.status,  # type: ignore[arg-type]
        created_at=_iso(c.created_at) or "",
        expires_at=_iso(c.expires_at),
        link_ok=bool(c.link_ok),
        link_org=c.link_org,
        link_note=c.link_note,
        is_mine=c.poster_id == viewer.id,
        claimed_by_me=c.claimed_by == viewer.id,
        awaiting_review=c.status == "claimed" and c.proof_photo_url is not None,
    )


@router.get("/campaigns", response_model=list[CampaignOut])
def list_campaigns(
    mine: bool = Query(default=False, description="Only campaigns you posted or claimed"),
    db: DbSession = Depends(get_db),
    user: m.User = Depends(get_current_user),
) -> list[CampaignOut]:
    sweep(db)
    q = db.query(m.Campaign).order_by(m.Campaign.created_at.desc())
    if mine:
        rows = [c for c in q if c.poster_id == user.id or c.claimed_by == user.id]
    else:
        # The open board: live, verified, and not your own -- you cannot
        # collect your own bounty.
        rows = [
            c for c in q
            if c.status == "open" and c.link_ok and c.poster_id != user.id
        ]
    return [_to_out(c, user) for c in rows]


@router.get("/wallet", response_model=WalletOut)
def wallet(
    db: DbSession = Depends(get_db), user: m.User = Depends(get_current_user)
) -> WalletOut:
    sweep(db)
    rows = (
        db.query(m.PointsTransaction)
        .filter(
            (m.PointsTransaction.from_user_id == user.id)
            | (m.PointsTransaction.to_user_id == user.id)
        )
        .order_by(m.PointsTransaction.created_at.desc())
        .limit(50)
        .all()
    )
    names = {
        u.id: u.name
        for u in db.query(m.User).filter(
            m.User.id.in_({t.from_user_id for t in rows} | {t.to_user_id for t in rows} - {None})
        )
    }
    out = []
    for t in rows:
        if t.kind == "escrow":
            direction, other = "hold", None
        elif t.to_user_id == user.id:
            direction, other = "in", names.get(t.from_user_id)
        else:
            direction, other = "out", names.get(t.to_user_id)
        out.append(
            TransactionOut(
                id=t.id, kind=t.kind, amount=t.amount, campaign_id=t.campaign_id,
                direction=direction, counterparty=other, note=t.note or "",
                created_at=_iso(t.created_at) or "",
            )
        )
    return WalletOut(
        total_points=user.tier_points or 0,
        available_points=available(user),
        escrow_points=user.escrow_points or 0,
        transactions=out,
    )


@router.post("/campaigns", response_model=CampaignOut, status_code=201)
def create_campaign(
    body: CampaignCreate,
    db: DbSession = Depends(get_db),
    user: m.User = Depends(get_current_user),
) -> CampaignOut:
    sweep(db)

    bad = [p for p in body.platforms if p not in PLATFORMS]
    if bad:
        raise HTTPException(
            status_code=400,
            detail=f"Pick from: {', '.join(PLATFORMS)}. Not recognised: {', '.join(bad)}",
        )
    if body.bounty > available(user):
        raise HTTPException(
            status_code=400,
            detail=(
                f"You only have {available(user)} points available. "
                "Earn more, or lower the bounty."
            ),
        )

    # Check the link before anything is created or held. A campaign that
    # fails this never exists, so there is no half-state to clean up.
    check = verify_donation_link(body.donation_url, body.title)
    if not check["looks_legitimate"]:
        raise HTTPException(status_code=400, detail=check["reason"])

    campaign = m.Campaign(
        poster_id=user.id,
        title=body.title.strip(),
        donation_url=body.donation_url.strip(),
        note=body.note.strip(),
        platforms=",".join(body.platforms),
        bounty=body.bounty,
        status="open",
        link_ok=True,
        link_org=check["organization"] or None,
        link_note=check["reason"],
        expires_at=(
            datetime.now(timezone.utc) + timedelta(days=body.expires_in_days)
            if body.expires_in_days else None
        ),
    )
    db.add(campaign)
    db.flush()

    hold(db, user, body.bounty, campaign.id, f"Bounty for “{campaign.title}”")
    db.commit()
    db.refresh(campaign)
    return _to_out(campaign, user)


@router.post("/campaigns/{campaign_id}/claim", response_model=CampaignOut)
def claim_campaign(
    campaign_id: str,
    db: DbSession = Depends(get_db),
    user: m.User = Depends(get_current_user),
) -> CampaignOut:
    sweep(db)
    c = db.get(m.Campaign, campaign_id)
    if c is None:
        raise HTTPException(status_code=404, detail="No such campaign")
    if c.poster_id == user.id:
        raise HTTPException(status_code=400, detail="You can't claim your own campaign")
    if c.status != "open":
        raise HTTPException(status_code=409, detail=f"That campaign is {c.status}")

    c.status = "claimed"
    c.claimed_by = user.id
    c.claimed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(c)
    return _to_out(c, user)


@router.post("/campaigns/{campaign_id}/proof", response_model=CampaignOut)
def submit_proof(
    campaign_id: str,
    body: CampaignProofIn,
    db: DbSession = Depends(get_db),
    user: m.User = Depends(get_current_user),
) -> CampaignOut:
    """Submit the screenshot, and pay out on the spot if it checks out.

    No manual approval step: the poster asked for a post on a platform, and
    the check answers whether there is one. Making them approve as well
    would let a poster take the promotion and keep the points.
    """
    c = db.get(m.Campaign, campaign_id)
    if c is None:
        raise HTTPException(status_code=404, detail="No such campaign")
    if c.claimed_by != user.id:
        raise HTTPException(status_code=403, detail="You haven't claimed this campaign")
    if c.status != "claimed":
        raise HTTPException(status_code=409, detail=f"That campaign is {c.status}")

    result = score_campaign_proof(
        body.photo_url,
        [p for p in (c.platforms or "").split(",") if p],
        c.title,
        c.donation_url,
        body.note,
    )
    if not result["verified"]:
        # Not a rejection of the person -- the claim stays theirs so they
        # can retake the screenshot and try again.
        raise HTTPException(status_code=400, detail=result["rationale"])

    poster = db.get(m.User, c.poster_id)
    if poster is None:
        raise HTTPException(status_code=409, detail="The poster's account no longer exists")

    c.proof_photo_url = body.photo_url
    c.proof_note = body.note
    c.status = "done"
    c.completed_at = datetime.now(timezone.utc)

    pay_out(db, poster, user, c.bounty, c.id, f"Promoted “{c.title}”")
    db.commit()
    db.refresh(c)
    return _to_out(c, user)


@router.post("/campaigns/{campaign_id}/cancel", response_model=CampaignOut)
def cancel_campaign(
    campaign_id: str,
    db: DbSession = Depends(get_db),
    user: m.User = Depends(get_current_user),
) -> CampaignOut:
    c = db.get(m.Campaign, campaign_id)
    if c is None:
        raise HTTPException(status_code=404, detail="No such campaign")
    if c.poster_id != user.id:
        raise HTTPException(status_code=403, detail="That isn't your campaign")
    if c.status not in ("open", "claimed"):
        raise HTTPException(status_code=409, detail=f"That campaign is already {c.status}")

    release(db, user, c.bounty, c.id, "Campaign cancelled")
    c.status = "cancelled"
    db.commit()
    db.refresh(c)
    return _to_out(c, user)


@router.delete("/campaigns/{campaign_id}", status_code=204)
def delete_campaign(
    campaign_id: str,
    db: DbSession = Depends(get_db),
    user: m.User = Depends(get_current_user),
) -> None:
    """Remove a campaign you posted.

    Any bounty still held comes back first, so deleting can never strand
    points. A campaign that already paid out can still be deleted -- the
    PointsTransaction rows reference it by id rather than by foreign key,
    so the ledger survives and the payout stays accountable.
    """
    c = db.get(m.Campaign, campaign_id)
    if c is None:
        return
    if c.poster_id != user.id:
        raise HTTPException(status_code=403, detail="That isn't your campaign")

    if c.status in ("open", "claimed"):
        release(db, user, c.bounty, c.id, "Campaign deleted")

    db.delete(c)
    db.commit()
