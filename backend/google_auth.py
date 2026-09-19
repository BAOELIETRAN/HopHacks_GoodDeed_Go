"""Google Sign-In verification.

Uses the ID-token flow: the browser's Google Identity Services button hands
the frontend a signed JWT, the frontend POSTs it here, and we verify the
signature against Google's public keys. Nothing secret is involved -- the
client ID is public and there is no client secret to leak, which is why this
flow is preferable to the server-side redirect dance for a SPA.

Verifying rather than decoding matters: an unverified JWT is attacker-supplied
JSON, and trusting its `email` would let anyone sign in as anyone.
"""

from __future__ import annotations

import logging

from .config import GOOGLE_CLIENT_ID

log = logging.getLogger("gooddeed.google")

# Google mints tokens under one of these two issuers.
_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}


class GoogleAuthError(Exception):
    """The credential could not be verified as a genuine Google token."""


def is_enabled() -> bool:
    return bool(GOOGLE_CLIENT_ID)


def verify_credential(credential: str) -> dict:
    """Verify a Google ID token and return its claims.

    Raises GoogleAuthError for anything we should not trust.
    """
    if not GOOGLE_CLIENT_ID:
        raise GoogleAuthError("Google sign-in is not configured on this server")
    if not credential or credential.count(".") != 2:
        raise GoogleAuthError("That does not look like a Google credential")

    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token
    except ImportError as exc:  # pragma: no cover - dependency is in requirements
        raise GoogleAuthError(
            "google-auth is not installed on the server (pip install google-auth)"
        ) from exc

    try:
        claims = id_token.verify_oauth2_token(
            credential, google_requests.Request(), GOOGLE_CLIENT_ID
        )
    except ValueError as exc:
        # Covers a bad signature, a wrong audience, and an expired token.
        log.warning("Rejected Google credential: %s", exc)
        raise GoogleAuthError("Google sign-in failed. Please try again.") from exc

    if claims.get("iss") not in _ISSUERS:
        raise GoogleAuthError("Unexpected token issuer")
    if not claims.get("email"):
        raise GoogleAuthError("That Google account has no email address")
    # An unverified address could be an address the user does not control,
    # which would let them collide with someone else's email signup.
    if claims.get("email_verified") is False:
        raise GoogleAuthError("Please verify your email with Google first")
    if not claims.get("sub"):
        raise GoogleAuthError("Google credential is missing a subject")

    return claims
