"""Checks for the donation-promotion marketplace.

Two jobs, both deliberately lenient. This is a hackathon demo: the goal is
"does this plausibly show a real cause and a real post", not fraud-proofing.
A check strict enough to stop a determined faker would also reject most
honest submissions, and rejecting honest people is the worse failure here.

The one thing that is *not* lenient is the link check. Points are moving
between users on the strength of a URL, and an app that promotes a phishing
page to someone's followers has done real harm.
"""

from __future__ import annotations

import logging
from typing import Any

from .providers import LLMProvider, get_llm_provider

log = logging.getLogger("gooddeed_agent.campaigns")

#: Platforms a campaign can ask for. Fixed set: the screenshot rubric has
#: to know which UI to look for.
PLATFORMS: dict[str, str] = {
    "instagram": "Instagram Story",
    "snapchat": "Snapchat",
    "tiktok": "TikTok",
}

_LINK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "looks_legitimate": {"type": "boolean"},
        "organization": {"type": "string"},
        "cause_summary": {"type": "string"},
        "has_donation_mechanism": {"type": "boolean"},
        "concerns": {"type": "array", "items": {"type": "string"}},
        "reason": {"type": "string"},
    },
    "required": [
        "looks_legitimate", "organization", "cause_summary",
        "has_donation_mechanism", "concerns", "reason",
    ],
    "additionalProperties": False,
}

_LINK_SYSTEM = """You check whether a link is a real donation or fundraising \
page before an app promotes it to people's social media followers.

Search the web for the URL and the organization behind it, then judge:

1. Does the page exist and belong to a real organization or a real personal \
fundraiser on a recognised platform (GoFundMe, JustGiving, GiveButter, \
Donorbox, a charity's own site, a hospital or school foundation)?
2. Is there an actual way to give money -- a donation form, a platform \
checkout, a registered payment processor?
3. Is there any sign of a scam: a lookalike domain imitating a known \
charity, a page asking for card details outside a payment processor, \
pressure language, a cause with no verifiable organization behind it, or a \
URL shortener hiding the destination?

Set looks_legitimate=false for anything you cannot place, anything \
impersonating a known charity, and anything that is not a donation page at \
all. A small personal fundraiser on a reputable platform is fine and should \
pass -- most giving is small and personal.

Do not judge the worthiness of the cause. That is not your call; you are \
only checking that the page is real and that giving to it does what it says.

reason: one sentence the poster will read. If you rejected it, say exactly \
what was wrong so they can fix the link."""


def verify_donation_link(
    url: str, title: str = "", *, llm: LLMProvider | None = None
) -> dict[str, Any]:
    """Check a donation link before a campaign goes live.

    Returns ``{looks_legitimate, organization, cause_summary,
    has_donation_mechanism, concerns, reason}``.

    A checker failure returns ``looks_legitimate=False`` -- when the
    question is "should we broadcast this URL", the safe default on an
    error is no.
    """
    llm = llm or get_llm_provider()
    clean = (url or "").strip()
    if not clean:
        return _rejected("Add a link to the donation page.")
    if not clean.lower().startswith(("http://", "https://")):
        return _rejected("That doesn't look like a web address — it should start with https://.")

    prompt = (
        f"Donation page URL: {clean}\n"
        f"Poster's title for it: {title or '(none given)'}\n\n"
        "Search for this page and report whether it is a real donation page."
    )
    try:
        raw = llm.complete_json(
            system=_LINK_SYSTEM,
            content=[{"type": "text", "text": prompt}],
            schema=_LINK_SCHEMA,
            effort="medium",
            use_web_search=True,
        )
    except Exception as exc:
        log.warning("Link check failed for %s: %s", clean, exc)
        return _rejected(f"We couldn't check that link right now ({exc}). Try again shortly.")

    return {
        "looks_legitimate": bool(raw.get("looks_legitimate")),
        "organization": str(raw.get("organization", "")).strip(),
        "cause_summary": str(raw.get("cause_summary", "")).strip(),
        "has_donation_mechanism": bool(raw.get("has_donation_mechanism")),
        "concerns": list(raw.get("concerns") or []),
        "reason": str(raw.get("reason", "")).strip() or "Checked.",
    }


def _rejected(reason: str) -> dict[str, Any]:
    return {
        "looks_legitimate": False,
        "organization": "",
        "cause_summary": "",
        "has_donation_mechanism": False,
        "concerns": [reason],
        "reason": reason,
    }


def promo_rubric(platforms: list[str], campaign_title: str, donation_url: str) -> str:
    """The rubric for checking a promotion screenshot.

    Assembled per campaign so the model knows which platform's UI to expect
    and what the post was supposed to be about.
    """
    wanted = ", ".join(PLATFORMS.get(p, p) for p in platforms) or "a social platform"
    return f"""The user was asked to promote a donation campaign on {wanted} \
and has uploaded a screenshot of their own post as proof.

Campaign: {campaign_title}
Donation link: {donation_url}

Check two things, and be generous about both:

1. Does the screenshot show {wanted}? Look for that platform's interface --
   a story ring or reply bar, a TikTok video frame with the side action
   column, Snapchat's capture UI. A cropped or partial screenshot is fine
   as long as the platform is recognisable.
2. Is the post visibly about this campaign? A visible link, the cause or
   organization name, a matching sticker or caption -- any one of those is
   enough.

Pass it if both are plausibly true. Do not require the link to be readable,
the post to be well designed, engagement numbers, or the account name to be
visible. People blur personal details in screenshots and that is sensible.

Fail it only when the screenshot clearly is not the platform asked for, is
obviously unrelated to the campaign, is a stock image or a screenshot of
someone else's post, or shows nothing at all."""
