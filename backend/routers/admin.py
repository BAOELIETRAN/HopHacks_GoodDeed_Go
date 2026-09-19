"""Operator endpoints. Not part of the user-facing API.

Guarded by a shared secret rather than a user session: the caller is a cron
job, not a person, and no user should be able to trigger a full Places
fan-out by finding the URL.
"""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Header, HTTPException
from sqlalchemy.orm import Session as DbSession
from fastapi import Depends

from ..config import REFRESH_TOKEN
from ..database import get_db
from ..refresh import refresh_cached_areas

router = APIRouter(prefix="/admin", tags=["admin"])


def _require_token(token: str | None) -> None:
    if not REFRESH_TOKEN:
        # Disabled rather than open. See the module docstring.
        raise HTTPException(status_code=404, detail="Not found")
    # compare_digest, not ==, so a wrong token can't be found a character at
    # a time by timing the response.
    if not token or not hmac.compare_digest(token, REFRESH_TOKEN):
        raise HTTPException(status_code=401, detail="Bad or missing refresh token")


@router.post("/refresh-opportunities")
def refresh_opportunities(
    x_refresh_token: str | None = Header(default=None),
    db: DbSession = Depends(get_db),
) -> dict:
    """Re-fetch every cached area now.

    Idempotent: each area's cached rows are replaced wholesale, so calling
    this twice leaves the same data, not two copies of it.
    """
    _require_token(x_refresh_token)
    return refresh_cached_areas(db)
