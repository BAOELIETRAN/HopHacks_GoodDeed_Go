"""Deed types, and the rubric each one is judged by.

Not every good deed is a person photographed at a building. A donation is a
receipt, a fundraiser is a page, advocacy is a link. Forcing all of them
through "does this photo plausibly show you doing the thing" produced
nonsense -- a receipt has no person in it and scored zero.

Each type declares three things: what it costs the person (base points),
what evidence to expect, and what the model should actually check. The
scoring prompt is assembled from the type rather than shared.

Points reflect effort and verifiability, not moral worth. Advocacy is
cheapest because it is a tap; a shelter shift is highest because it costs a
morning. Kindness is capped low precisely because it is the hardest to
verify -- it exists so the app recognises small good behaviour, not so it
can be farmed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DeedType = Literal[
    "volunteer",
    "donation_money",
    "donation_item",
    "fundraising",
    "kindness",
    "remote",
    "advocacy",
    "blood_donation",
]


@dataclass(frozen=True)
class DeedSpec:
    key: str
    label: str
    icon: str
    blurb: str                 # shown in the type picker
    evidence: str              # what the user is asked to upload
    photo_required: bool
    time_required: bool
    location_required: bool
    base_points: int
    max_points: int
    rubric: str                # appended to the scoring system prompt


_SHARED_TAIL = """
Judge only what the evidence can support. Never estimate real-world impact:
you cannot see it, and rewarding a guess at it teaches people to write
better captions rather than do more good.

Be concrete and kind in the rationale. If you scored low, say exactly what
was missing so they can fix it next time. Never accuse anyone of fraud --
describe what you could not confirm.
"""

DEEDS: dict[str, DeedSpec] = {
    "volunteer": DeedSpec(
        key="volunteer",
        label="Volunteered in person",
        icon="🙌",
        blurb="A shift at an organization",
        evidence="A photo of you doing the work",
        photo_required=True, time_required=True, location_required=True,
        base_points=30, max_points=100,
        rubric="""The user says they volunteered in person at an organization.

Check:
1. Does the photo show the activity described, at a plausible setting for
   that kind of organization?
2. Is the description specific and first-hand -- what they did, with whom,
   what it looked like -- rather than vague filler?
3. Is the claimed time believable for the activity shown?

Push confidence low for: stock or promotional images, screenshots, photos of
a screen, obvious AI generation, no person or activity visible, or text that
contradicts the image. Do not penalise a poor camera, bad lighting, an
awkward angle, or a short but specific description.""",
    ),
    "donation_money": DeedSpec(
        key="donation_money",
        label="Donated money",
        icon="💳",
        blurb="A financial gift to a cause",
        evidence="A screenshot of the confirmation or receipt",
        photo_required=True, time_required=False, location_required=False,
        base_points=25, max_points=80,
        rubric="""The user donated money and uploaded a receipt or confirmation.

This is a document check, not a photo-authenticity check. There is no person
in the image and there should not be.

Check:
1. Does it read as a genuine donation confirmation -- a recipient
   organization, an amount, and a date all visible?
2. Does the organization named look like a real charitable cause rather than
   a purchase, subscription, bill or transfer to an individual?
3. Does the receipt match the description the user wrote?

Push confidence low for: an obviously edited or hand-typed image, a template
with placeholder text, a shopping receipt, or a screenshot with the amount
or recipient cropped out. A redacted card number or address is normal and
sensible -- never penalise that.""",
    ),
    "donation_item": DeedSpec(
        key="donation_item",
        label="Donated goods",
        icon="📦",
        blurb="Clothes, food, books, supplies",
        evidence="A photo of the items, and where you dropped them off",
        photo_required=True, time_required=False, location_required=False,
        base_points=20, max_points=70,
        rubric="""The user donated physical items and photographed them.

Check:
1. Does the photo show actual goods in a quantity consistent with the
   description?
2. Is a drop-off organization or location named?
3. Do the items look like a genuine donation rather than a stock photo or a
   product listing?

Judge the donation, not its presentation. A boot full of carrier bags is a
real donation and should score like one.""",
    ),
    "fundraising": DeedSpec(
        key="fundraising",
        label="Raised money",
        icon="🎽",
        blurb="A charity run, drive or fundraiser page",
        evidence="A screenshot of the fundraiser page",
        photo_required=True, time_required=False, location_required=False,
        base_points=30, max_points=90,
        rubric="""The user ran a fundraiser and uploaded a screenshot of the page.

Check:
1. Does it look like a real fundraising page -- a named cause, an amount
   raised or a goal, and a recognisable platform layout?
2. Is the beneficiary a cause or organization rather than a personal expense?
3. Does the page match the description given?

Push confidence low for: a plain screenshot of a bank balance, a page with
no cause named, or an image that is only text. A modest amount raised is not
a reason to score low -- the effort is in running it.""",
    ),
    "kindness": DeedSpec(
        key="kindness",
        label="Act of kindness",
        icon="💛",
        blurb="Helped someone directly",
        evidence="A short description; a photo is optional",
        photo_required=False, time_required=False, location_required=False,
        base_points=8, max_points=20,
        rubric="""The user describes an everyday act of kindness -- helping a
stranger, buying someone a meal, checking on a neighbour.

This is the hardest category to verify and is deliberately worth the least,
so the bar is honesty rather than proof.

Check:
1. Is this a specific, plausible account of something that actually
   happened, rather than a generic sentence?
2. Does it describe helping a person or the community?
3. If a photo is attached, does it contradict the description?

Accept ordinary, small, unglamorous things -- that is the point of the
category. Push confidence low only for: obvious jokes, copied text, empty
filler like "did a good thing", or anything describing harm.

Never require a photo here, and never penalise its absence.""",
    ),
    "remote": DeedSpec(
        key="remote",
        label="Helped remotely",
        icon="💻",
        blurb="Tutoring, pro-bono work, online support",
        evidence="A screenshot of the session, or a thank-you message",
        photo_required=True, time_required=True, location_required=False,
        base_points=25, max_points=85,
        rubric="""The user did unpaid work for a cause remotely -- tutoring,
design, writing, code, translation, helpline support.

Check:
1. Does the evidence show remote work or an acknowledgement of it -- a call
   screenshot, a delivered piece of work, a thank-you message?
2. Is the beneficiary a nonprofit, a community, or someone who needed help,
   rather than paid client work?
3. Is the claimed time plausible for what is shown?

There is no location to check, and that is expected. Never penalise the
absence of a place or a person in frame.""",
    ),
    "advocacy": DeedSpec(
        key="advocacy",
        label="Civic action",
        icon="📣",
        blurb="Signed a petition, contacted a representative",
        evidence="A screenshot or link showing the action",
        photo_required=False, time_required=False, location_required=False,
        base_points=5, max_points=15,
        rubric="""The user took a civic action -- signed or shared a petition,
wrote to a representative, attended a public meeting.

This is the cheapest action to log and is scored accordingly. It is included
because low-effort civic action is still real, not because it should compete
with a shelter shift.

Check:
1. Does the description name a specific issue and a specific action?
2. If evidence is attached, is it consistent with that?

Accept without a screenshot. Push confidence low only for: no issue named,
copied slogans with no action, or anything advocating harm toward a group.
Do not judge the politics of the cause -- only whether an action was
plausibly taken.""",
    ),
    "blood_donation": DeedSpec(
        key="blood_donation",
        label="Gave blood",
        icon="🩸",
        blurb="A donation or drive appointment",
        evidence="A photo at the drive, or your confirmation",
        photo_required=True, time_required=False, location_required=False,
        base_points=35, max_points=90,
        rubric="""The user donated blood or plasma.

Check:
1. Does the evidence show a donation setting -- a chair, a drive banner, a
   bandaged arm, a donor card -- or a confirmation from a blood service?
2. Does the organization look like a genuine blood service or drive?

A confirmation screenshot is as good as a photo here; many centres do not
allow photography. Never require a face to be visible.""",
    ),
}

DEED_KEYS = tuple(DEEDS)
DEFAULT_DEED = "volunteer"


def get_deed(deed_type: str | None) -> DeedSpec:
    """Look up a deed spec, falling back to volunteering for anything
    unrecognised rather than raising -- an unknown type should degrade, not
    reject a submission someone spent an hour earning."""
    return DEEDS.get((deed_type or "").strip().lower(), DEEDS[DEFAULT_DEED])


def rubric_for(deed_type: str | None) -> str:
    return get_deed(deed_type).rubric + _SHARED_TAIL
