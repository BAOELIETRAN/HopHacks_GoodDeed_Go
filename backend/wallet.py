"""Point movements for the campaign marketplace.

One balance, one source of truth: ``User.tier_points``. Everything the app
already does -- quests, donations, everyday deeds -- writes there, and so
does this. ``escrow_points`` is a *hold* against that same balance, not a
second currency:

    available = tier_points - escrow_points

Escrow never changes a tier by itself, because holding points is not
spending them. A payout does change both users' totals, and therefore can
change a tier in either direction. That is correct: the poster really did
give those points away.

Every movement writes a PointsTransaction. Balances alone cannot answer
"where did those points go", and a feature that moves value between users
has to be able to answer that.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException
from sqlalchemy.orm import Session as DbSession

from . import db_models as m
from .agent_client import tier_for_points

log = logging.getLogger("gooddeed.wallet")


def available(user: m.User) -> int:
    """Spendable balance: the total minus whatever is on hold."""
    return max(0, (user.tier_points or 0) - (user.escrow_points or 0))


def _record(db: DbSession, *, kind: str, amount: int, campaign_id: str | None,
            from_user_id: str | None, to_user_id: str | None, note: str) -> None:
    db.add(
        m.PointsTransaction(
            kind=kind, amount=amount, campaign_id=campaign_id,
            from_user_id=from_user_id, to_user_id=to_user_id, note=note,
        )
    )


def hold(db: DbSession, user: m.User, amount: int, campaign_id: str, note: str = "") -> None:
    """Put a bounty on hold when a campaign is posted."""
    if amount <= 0:
        raise HTTPException(status_code=400, detail="A bounty has to be at least 1 point")
    if amount > available(user):
        raise HTTPException(
            status_code=400,
            detail=(
                f"You have {available(user)} points available "
                f"({user.escrow_points or 0} already held on other campaigns)."
            ),
        )
    user.escrow_points = (user.escrow_points or 0) + amount
    _record(db, kind="escrow", amount=amount, campaign_id=campaign_id,
            from_user_id=user.id, to_user_id=None, note=note or "Bounty held")


def release(db: DbSession, user: m.User, amount: int, campaign_id: str, note: str = "") -> None:
    """Return a hold to the poster -- cancelled, or expired unclaimed."""
    amount = min(amount, user.escrow_points or 0)
    if amount <= 0:
        return
    user.escrow_points = (user.escrow_points or 0) - amount
    _record(db, kind="refund", amount=amount, campaign_id=campaign_id,
            from_user_id=None, to_user_id=user.id, note=note or "Bounty returned")


def pay_out(db: DbSession, poster: m.User, claimer: m.User, amount: int,
            campaign_id: str, note: str = "") -> None:
    """Move a held bounty from poster to claimer.

    The hold is released and the total debited in the same step, so the
    pair of balances is never briefly wrong. Totals are conserved: what
    leaves one account arrives in the other.
    """
    amount = min(amount, poster.escrow_points or 0)
    if amount <= 0:
        log.warning("Payout for %s had nothing held", campaign_id)
        return

    poster.escrow_points = (poster.escrow_points or 0) - amount
    poster.tier_points = max(0, (poster.tier_points or 0) - amount)
    poster.tier = tier_for_points(poster.tier_points)

    claimer.tier_points = (claimer.tier_points or 0) + amount
    claimer.tier = tier_for_points(claimer.tier_points)

    _record(db, kind="payout", amount=amount, campaign_id=campaign_id,
            from_user_id=poster.id, to_user_id=claimer.id,
            note=note or "Campaign completed")


# --- store coins ----------------------------------------------------------
#
# Coins live here beside the point ledger so there is one module that moves
# balances, but they deliberately do NOT write PointsTransaction rows.
#
# That table records points moving *between two people*, which is what makes
# a campaign bounty auditable. Coins never change hands: they are minted by
# your own deeds and burned on your own cosmetics. Writing a row per deed
# would bury the bounty ledger under thousands of self-to-self entries and
# make `kind` mean two different things.
#
# The coin trail is already complete without it. Every credit has a
# Submission or MicroDeedDone row behind it, and every debit has an
# OwnedItem row carrying `price_paid` and `acquired_at`.


def earn_coins(db: DbSession, user: m.User, amount: int, note: str = "") -> None:
    """Credit store coins for a deed that also awarded points.

    Called next to every ``tier_points +=`` in the app, with the same amount.
    Coins are a spendable mirror of the lifetime record, so the two only ever
    diverge by what someone has actually bought.

    ``note`` is accepted for symmetry with the ledger functions above and for
    the log line; it is not persisted.
    """
    if amount <= 0:
        return
    user.coins = (user.coins or 0) + amount


def spend_coins(db: DbSession, user: m.User, amount: int, note: str = "") -> None:
    """Debit coins for a store purchase.

    Deliberately does not touch ``tier_points``: a purchase is not a
    donation, and the tier ladder is a record of what someone did, not of
    what they still have. Raises rather than clamping, because a purchase
    that silently costs less than its price is worse than a refused one.
    """
    if amount <= 0:
        raise HTTPException(status_code=400, detail="That item has no price")
    balance = user.coins or 0
    if amount > balance:
        raise HTTPException(
            status_code=400,
            detail=f"That costs {amount} coins and you have {balance}. Go do some good.",
        )
    user.coins = balance - amount
    log.info("%s spent %d coins: %s", user.id, amount, note or "store purchase")


def refund_coins(db: DbSession, user: m.User, amount: int, note: str = "") -> None:
    """Return coins for a purchase that could not be completed."""
    if amount <= 0:
        return
    user.coins = (user.coins or 0) + amount
    log.info("%s refunded %d coins: %s", user.id, amount, note or "purchase refunded")
