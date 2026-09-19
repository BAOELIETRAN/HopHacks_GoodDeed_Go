"""Vision-backed grading: submissions and community reports.

Both functions send a photo plus text to Claude and get a constrained JSON
verdict back. The model judges *authenticity and effort only* -- whether the
photo plausibly shows the described deed at the named org. It never estimates
real-world impact; that is unverifiable from a photo and rewarding guesses at
it would just teach users to write better captions.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .models import CommunityReport, ReportClassification, ScoreResult, Submission
from .providers import LLMProvider, get_llm_provider
from .scoring import (
    MIN_AUTHENTICITY,
    PLAUSIBLE_MAX_MINUTES,
    compute_points,
    normalize_category,
)

log = logging.getLogger("gooddeed_agent.vision")

PhotoInput = str | bytes | Path

# --- Submission scoring -----------------------------------------------------

_SCORE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "photo_matches_description": {"type": "boolean"},
        "photo_matches_org": {"type": "boolean"},
        "description_specificity": {"type": "number"},
        "time_plausible": {"type": "boolean"},
        "authenticity_confidence": {"type": "number"},
        "likely_category": {
            "type": "string",
            "enum": [
                "food_bank", "homeless_shelter", "animal_shelter", "environmental",
                "community_cleanup", "education", "healthcare", "senior_care",
                "youth_program", "disaster_relief", "religious", "thrift_donation",
                "community_center", "other",
            ],
        },
        "concerns": {"type": "array", "items": {"type": "string"}},
        "rationale": {"type": "string"},
    },
    "required": [
        "photo_matches_description", "photo_matches_org", "description_specificity",
        "time_plausible", "authenticity_confidence", "likely_category", "concerns", "rationale",
    ],
    "additionalProperties": False,
}

_SCORE_SYSTEM = """You verify volunteering submissions for GoodDeed Go, an app \
where users photograph themselves doing a good deed.

Judge AUTHENTICITY AND EFFORT ONLY. Never judge, estimate, or reward real-world \
impact -- you cannot see it and guessing at it rewards good writing over good \
deeds.

Assess:
1. photo_matches_description -- does the image actually show what the text \
claims? A generic selfie with an unrelated caption does not.
2. photo_matches_org -- is the setting consistent with the named organization \
and its type? Absence of signage is weak evidence, not disqualifying.
3. description_specificity (0-1) -- specific, first-hand detail (what they did, \
who with, what it looked like) scores high; vague filler like "helped out, felt \
good" scores low.
4. time_plausible -- could the claimed minutes match the activity shown? \
Ten minutes for "sorted donations all morning" is not plausible.
5. authenticity_confidence (0-1) -- overall confidence this is a genuine \
first-hand submission from this person at this org.

Push authenticity_confidence low for: screenshots, stock or promotional images, \
photos of a screen, obvious AI generation, images with no person or activity \
visible, text that contradicts the image, or reused/duplicate-looking content.

Do not penalize a submission merely for a low-quality camera, poor lighting, an \
awkward angle, or a short but specific description.

rationale: one or two sentences the user will see. Concrete and kind. If you \
scored low, say exactly what was missing so they can fix it next time. Never \
accuse the user of fraud outright -- describe what you could not confirm."""


def score_submission(
    photo: PhotoInput,
    description: str,
    org_name: str,
    time_spent_minutes: int | float,
    *,
    category: str | None = None,
    quest_multiplier: float = 1.0,
    include_debug: bool = False,
    llm: LLMProvider | None = None,
) -> dict[str, Any]:
    """Grade one submission and award points.

    Args:
        photo: URL, file path, raw bytes, or base64 image data.
        description: The user's short write-up.
        org_name: Organization the quest was attached to.
        time_spent_minutes: Minutes the user claims they spent.
        category: Opportunity category, if the backend knows it. When omitted,
            the model's ``likely_category`` is used, which is less reliable --
            pass it when you have it, since it sets the base points.
        quest_multiplier: Applied to leaderboard ``points`` only, never to
            ``tier_points``. Use 1.5 for monthly quests, 1.0 for daily.
        include_debug: Add a ``debug`` key with the model's full assessment.
        llm: Injected provider; defaults to the environment's.

    Returns:
        ``{"points": int, "tier_points": int,
           "authenticity_confidence": float, "rationale": str}``

    A provider failure returns zero points with confidence 0.0 and a rationale
    saying so, rather than raising -- a submission should queue for retry, not
    500 the app.
    """
    llm = llm or get_llm_provider()

    from .providers.claude_llm import build_image_block

    try:
        image_block = build_image_block(photo)
    except Exception as exc:
        log.warning("Could not read submission photo: %s", exc)
        return ScoreResult(0, 0, 0.0, f"We couldn't read that photo ({exc}). Try uploading it again.").to_dict()

    minutes = max(0, int(time_spent_minutes or 0))
    prompt = (
        f"Organization: {org_name}\n"
        f"Claimed time spent: {minutes} minutes\n"
        f"User description: {description or '(none provided)'}\n\n"
        "Assess this submission."
    )

    try:
        raw = llm.complete_json(
            system=_SCORE_SYSTEM,
            content=[image_block, {"type": "text", "text": prompt}],
            schema=_SCORE_SCHEMA,
            effort="medium",
        )
    except Exception as exc:
        log.warning("score_submission failed for %r: %s", org_name, exc)
        return ScoreResult(
            0, 0, 0.0, "We couldn't verify this submission right now. It'll be retried shortly."
        ).to_dict()

    confidence = _clamp01(raw.get("authenticity_confidence", 0.0))
    confidence = _apply_penalties(confidence, raw, minutes)

    effective_category = normalize_category(category or raw.get("likely_category"))
    points, tier_points = compute_points(
        effective_category, minutes, confidence, quest_multiplier=quest_multiplier
    )

    rationale = str(raw.get("rationale", "")).strip() or _default_rationale(confidence)

    result = ScoreResult(
        points=points,
        tier_points=tier_points,
        authenticity_confidence=round(confidence, 2),
        rationale=rationale,
        debug={
            "category_used": effective_category,
            "minutes_counted": min(minutes, PLAUSIBLE_MAX_MINUTES),
            "quest_multiplier": quest_multiplier,
            "model_assessment": raw,
        },
    )
    return result.to_dict(include_debug=include_debug)


def _apply_penalties(confidence: float, raw: dict[str, Any], minutes: int) -> float:
    """Fold the structured sub-judgments back into one confidence number.

    The model already sets ``authenticity_confidence``, but these are the two
    hard signals we don't want it to smooth over.
    """
    if not raw.get("photo_matches_description", True):
        confidence = min(confidence, 0.35)
    if not raw.get("time_plausible", True):
        confidence *= 0.8
    specificity = _clamp01(raw.get("description_specificity", 0.5))
    if specificity < 0.25:
        confidence *= 0.85
    if minutes > PLAUSIBLE_MAX_MINUTES:
        confidence *= 0.7
    return _clamp01(confidence)


def _default_rationale(confidence: float) -> str:
    if confidence >= MIN_AUTHENTICITY:
        return "Submission looks genuine. Points awarded."
    return "We couldn't confirm this photo matches the described deed."


def score_submission_from_dict(
    submission: Submission | dict[str, Any], **options: Any
) -> dict[str, Any]:
    """Score a stored Submission record directly.

    Saves the backend from unpacking the contract shape by hand -- note that
    the record's field is ``photo_url`` while the function parameter is
    ``photo``, which is exactly the kind of mismatch this avoids.

    Accepts a ``Submission`` or a plain dict; extra keys are ignored. All
    :func:`score_submission` keyword options pass through.
    """
    record = submission if isinstance(submission, Submission) else Submission.from_dict(submission)
    return score_submission(
        record.photo_url,
        record.description,
        record.org_name,
        record.time_spent_minutes,
        **options,
    )


# --- Community report triage ------------------------------------------------

REPORT_CATEGORIES = [
    "litter",
    "illegal_dumping",
    "graffiti",
    "broken_infrastructure",
    "overgrowth",
    "hazard",
    "abandoned_item",
    "other",
]

_REPORT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": REPORT_CATEGORIES},
        "is_valid": {"type": "boolean"},
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["category", "is_valid", "confidence", "reason"],
    "additionalProperties": False,
}

_REPORT_SYSTEM = """You triage community "this needs fixing" reports for \
GoodDeed Go. Users photograph a local problem -- trash, graffiti, something \
broken -- and other users go fix it.

Pick the best category, then decide is_valid.

is_valid = true when the photo shows a real, physical, publicly visible problem \
that a volunteer could plausibly fix or clean up.

is_valid = false for: spam or advertising, memes and screenshots, selfies or \
photos of people as the subject, images showing nothing wrong, anything \
unrelated to a fixable local problem, and anything requiring emergency \
services or professional crews rather than volunteers (downed power lines, \
structural collapse, fire, flooding, a medical emergency) -- say so in the \
reason so the app can redirect them.

Also mark is_valid = false if the photo prominently features an identifiable \
person's face as the subject, a vehicle license plate as the subject, or a \
private residence's interior. Reason: privacy.

reason: one short sentence, addressed to the person who posted it."""


def classify_report(
    photo: PhotoInput,
    description: str = "",
    *,
    llm: LLMProvider | None = None,
) -> dict[str, Any]:
    """Categorize and sanity-check a community "needs fixing" report.

    Returns ``{"category": str, "is_valid": bool, "confidence": float,
    "reason": str}``. ``category`` and ``is_valid`` are the contract; the other
    two are extra context and can be ignored.

    Failures return ``is_valid=False`` with confidence 0.0 so nothing
    unreviewed reaches the public feed.
    """
    llm = llm or get_llm_provider()

    from .providers.claude_llm import build_image_block

    try:
        image_block = build_image_block(photo)
    except Exception as exc:
        log.warning("Could not read report photo: %s", exc)
        return ReportClassification("other", False, 0.0, f"We couldn't read that photo ({exc}).").to_dict()

    prompt = f"User description: {description or '(none provided)'}\n\nTriage this report."

    try:
        raw = llm.complete_json(
            system=_REPORT_SYSTEM,
            content=[image_block, {"type": "text", "text": prompt}],
            schema=_REPORT_SCHEMA,
            effort="low",
            max_tokens=4096,
        )
    except Exception as exc:
        log.warning("classify_report failed: %s", exc)
        return ReportClassification(
            "other", False, 0.0, "We couldn't check this report right now. Please try again."
        ).to_dict()

    category = str(raw.get("category", "other"))
    if category not in REPORT_CATEGORIES:
        category = "other"

    return ReportClassification(
        category=category,
        is_valid=bool(raw.get("is_valid", False)),
        confidence=round(_clamp01(raw.get("confidence", 0.0)), 2),
        reason=str(raw.get("reason", "")).strip(),
    ).to_dict()


def classify_report_from_dict(
    report: CommunityReport | dict[str, Any], **options: Any
) -> dict[str, Any]:
    """Triage a stored CommunityReport record directly.

    Same purpose as :func:`score_submission_from_dict`: the record carries
    ``photo_url``, the function takes ``photo``.
    """
    record = report if isinstance(report, CommunityReport) else CommunityReport.from_dict(report)
    return classify_report(record.photo_url, record.description, **options)


def _clamp01(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0
