"""The points store and the user's portfolio.

Endpoints are deliberately small, because the interesting rules all live in
store.py (what exists, what it costs, what an egg becomes) and wallet.py
(where the coins went). This module is the part that says no:

* you cannot buy what is not in the catalog,
* you cannot buy a second copy of an avatar,
* you cannot equip something you do not own,
* you cannot hatch an egg that has not done its deeds, and you cannot
  hatch the same egg twice.

Every purchase debits through ``wallet.spend_coins``, so a balance is never
edited here directly and every movement lands in the transaction ledger.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DbSession

from .. import db_models as m
from .. import store
from ..database import get_db
from ..deps import get_current_user
from ..schemas import (
    EquipIn,
    HatchOut,
    OwnedItemOut,
    PortfolioOut,
    StoreBuy,
    StoreCatalogOut,
)
from ..wallet import spend_coins

log = logging.getLogger("gooddeed.store")

router = APIRouter(prefix="/store", tags=["store"])


def _owned(db: DbSession, user_id: str) -> list[m.OwnedItem]:
    return (
        db.query(m.OwnedItem)
        .filter(m.OwnedItem.user_id == user_id)
        .order_by(m.OwnedItem.acquired_at.desc())
        .all()
    )


def _species_owned(items: list[m.OwnedItem]) -> set[str]:
    """Distinct animal codes the user has hatched."""
    return {i.hatched_code for i in items if i.state == "hatched" and i.hatched_code}


@router.get("", response_model=StoreCatalogOut)
def get_catalog(
    db: DbSession = Depends(get_db),
    user: m.User = Depends(get_current_user),
) -> StoreCatalogOut:
    items = _owned(db, user.id)
    owned_codes = {i.code for i in items if i.kind == "avatar"}
    return StoreCatalogOut(**store.catalog_out(owned_codes, user.coins or 0))


@router.get("/portfolio", response_model=PortfolioOut)
def get_portfolio(
    db: DbSession = Depends(get_db),
    user: m.User = Depends(get_current_user),
) -> PortfolioOut:
    items = _owned(db, user.id)
    deeds = store.deeds_done(db, user.id)
    total_species = sum(len(pool) for pool in store.ANIMALS.values())
    return PortfolioOut(
        coins=user.coins or 0,
        equipped_avatar=user.equipped_avatar,
        deeds_done=deeds,
        items=[OwnedItemOut(**store.item_out(i, deeds)) for i in items],
        animals_collected=len(_species_owned(items)),
        animals_total=total_species,
    )


@router.post("/buy", response_model=OwnedItemOut)
def buy(
    body: StoreBuy,
    db: DbSession = Depends(get_db),
    user: m.User = Depends(get_current_user),
) -> OwnedItemOut:
    entry = store.catalog_item(body.code)
    if entry is None:
        raise HTTPException(status_code=404, detail="That item isn't in the store")

    if entry["kind"] == "avatar":
        already = (
            db.query(m.OwnedItem)
            .filter(m.OwnedItem.user_id == user.id, m.OwnedItem.code == body.code)
            .first()
        )
        if already is not None:
            # Not an error the user caused twice on purpose -- the UI marks
            # owned avatars -- but charging twice for one cosmetic would be
            # the worst bug this feature could have.
            raise HTTPException(status_code=409, detail="You already own that one")

    price = int(entry.get("price") or 0)
    # Raises 400 with the balance in the message when they cannot afford it.
    spend_coins(db, user, price, note=f"Bought {entry.get('label', body.code)}")

    deeds = store.deeds_done(db, user.id)
    item = m.OwnedItem(
        user_id=user.id,
        kind=entry["kind"],
        code=body.code,
        price_paid=price,
        state="owned" if entry["kind"] == "avatar" else "incubating",
        deeds_at_purchase=deeds if entry["kind"] == "egg" else 0,
        hatches_after=int(entry.get("hatches_after") or 0),
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    log.info("%s bought %s for %d coins", user.id, body.code, price)
    return OwnedItemOut(**store.item_out(item, deeds))


@router.post("/eggs/{item_id}/hatch", response_model=HatchOut)
def hatch(
    item_id: str,
    db: DbSession = Depends(get_db),
    user: m.User = Depends(get_current_user),
) -> HatchOut:
    """Open an egg that has met its deed requirement.

    The species is rolled here and only here. Rolling at purchase would mean
    the answer existed while the user was still doing the deeds, and any
    stored roll is a roll someone can eventually read.
    """
    item = db.get(m.OwnedItem, item_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(status_code=404, detail="No such egg")
    if item.kind != "egg":
        raise HTTPException(status_code=400, detail="That isn't an egg")
    if item.state == "hatched":
        raise HTTPException(status_code=409, detail="That egg already hatched")

    deeds = store.deeds_done(db, user.id)
    done, needed = store.egg_progress(item, deeds)
    if done < needed:
        raise HTTPException(
            status_code=400,
            detail=f"This egg needs {needed - done} more deed(s) before it hatches.",
        )

    before = _species_owned(_owned(db, user.id))
    rolled = store.roll_animal(item.code)

    item.hatched_code = rolled["code"]
    item.rarity = rolled["rarity"]
    item.state = "hatched"
    item.hatched_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(item)

    log.info("%s hatched %s (%s) from %s", user.id, rolled["code"], rolled["rarity"], item.code)
    return HatchOut(
        item=OwnedItemOut(**store.item_out(item, deeds)),
        rarity=rolled["rarity"],
        rarity_label=store.RARITIES[rolled["rarity"]]["label"],
        is_new_species=rolled["code"] not in before,
    )


@router.post("/equip", response_model=PortfolioOut)
def equip(
    body: EquipIn,
    db: DbSession = Depends(get_db),
    user: m.User = Depends(get_current_user),
) -> PortfolioOut:
    """Wear an owned avatar, or pass null to go back to your photo."""
    if body.code:
        owns = (
            db.query(m.OwnedItem)
            .filter(
                m.OwnedItem.user_id == user.id,
                m.OwnedItem.code == body.code,
                m.OwnedItem.kind == "avatar",
            )
            .first()
        )
        if owns is None:
            raise HTTPException(status_code=403, detail="You don't own that avatar")

    user.equipped_avatar = body.code or None
    db.commit()
    return get_portfolio(db=db, user=user)
