"""score_submission / classify_report, against mock providers."""

from __future__ import annotations

import pytest

from gooddeed_agent import MIN_AUTHENTICITY, REPORT_CATEGORIES, classify_report, score_submission
from gooddeed_agent.providers.base import ProviderError

GOOD_DESCRIPTION = (
    "Spent the morning sorting canned goods into family boxes with two other "
    "volunteers in the back warehouse."
)


class _StubLLM:
    """Returns a fixed assessment, so the points math can be asserted exactly."""

    def __init__(self, **overrides):
        self.payload = {
            "photo_matches_description": True,
            "photo_matches_org": True,
            "description_specificity": 0.8,
            "time_plausible": True,
            "authenticity_confidence": 1.0,
            "likely_category": "food_bank",
            "concerns": [],
            "rationale": "Looks genuine.",
        }
        self.payload.update(overrides)
        self.calls: list[dict] = []

    def complete_json(self, **kwargs):
        self.calls.append(kwargs)
        return self.payload


class TestScoreSubmissionContract:
    def test_returns_exactly_the_contract_keys(self, photo_bytes, llm):
        result = score_submission(photo_bytes, GOOD_DESCRIPTION, "Riverside Food Bank", 90, llm=llm)
        assert set(result) == {"points", "tier_points", "authenticity_confidence", "rationale"}

    def test_types_match_the_contract(self, photo_bytes, llm):
        result = score_submission(photo_bytes, GOOD_DESCRIPTION, "Riverside Food Bank", 90, llm=llm)
        assert isinstance(result["points"], int)
        assert isinstance(result["tier_points"], int)
        assert isinstance(result["authenticity_confidence"], float)
        assert isinstance(result["rationale"], str) and result["rationale"]
        assert 0.0 <= result["authenticity_confidence"] <= 1.0

    def test_debug_is_opt_in(self, photo_bytes, llm):
        plain = score_submission(photo_bytes, GOOD_DESCRIPTION, "Org", 60, llm=llm)
        verbose = score_submission(photo_bytes, GOOD_DESCRIPTION, "Org", 60, include_debug=True, llm=llm)
        assert "debug" not in plain
        assert "debug" in verbose and "model_assessment" in verbose["debug"]


class TestScoreSubmissionMath:
    def test_confident_submission_uses_the_passed_category(self, photo_bytes):
        # food_bank base 30 + 60min bonus 6, full confidence.
        result = score_submission(
            photo_bytes, GOOD_DESCRIPTION, "Riverside", 60, category="food_bank", llm=_StubLLM()
        )
        assert result["points"] == 36

    def test_passed_category_overrides_the_models_guess(self, photo_bytes):
        stub = _StubLLM(likely_category="religious")  # base 15
        result = score_submission(
            photo_bytes, GOOD_DESCRIPTION, "Riverside", 60, category="food_bank", llm=stub
        )
        assert result["points"] == 36  # food_bank base, not religious

    def test_model_category_used_when_none_is_passed(self, photo_bytes):
        result = score_submission(photo_bytes, GOOD_DESCRIPTION, "Riverside", 60, llm=_StubLLM())
        assert result["points"] == 36

    def test_quest_multiplier_lifts_points_not_tier_points(self, photo_bytes):
        result = score_submission(
            photo_bytes, GOOD_DESCRIPTION, "Riverside", 60,
            category="food_bank", quest_multiplier=1.5, llm=_StubLLM(),
        )
        assert result["points"] == 54
        assert result["tier_points"] == 36

    def test_low_confidence_earns_zero(self, photo_bytes):
        stub = _StubLLM(authenticity_confidence=0.1)
        result = score_submission(photo_bytes, "helped out", "Org", 60, llm=stub)
        assert result["points"] == 0 and result["tier_points"] == 0

    def test_photo_description_mismatch_is_capped_hard(self, photo_bytes):
        # Even if the model reports high overall confidence, a declared
        # mismatch must drag the score below the payout threshold.
        stub = _StubLLM(photo_matches_description=False, authenticity_confidence=0.95)
        result = score_submission(photo_bytes, GOOD_DESCRIPTION, "Org", 60, llm=stub)
        assert result["authenticity_confidence"] <= 0.35
        assert result["points"] == 0

    def test_implausible_time_reduces_confidence(self, photo_bytes):
        honest = score_submission(photo_bytes, GOOD_DESCRIPTION, "Org", 60, llm=_StubLLM())
        padded = score_submission(
            photo_bytes, GOOD_DESCRIPTION, "Org", 60, llm=_StubLLM(time_plausible=False)
        )
        assert padded["authenticity_confidence"] < honest["authenticity_confidence"]

    def test_absurd_duration_does_not_pay_more_than_the_cap(self, photo_bytes):
        result = score_submission(
            photo_bytes, GOOD_DESCRIPTION, "Org", 99_999, category="food_bank", llm=_StubLLM()
        )
        assert result["points"] <= 100

    def test_vague_description_scores_lower_than_specific_one(self, photo_bytes):
        specific = score_submission(photo_bytes, GOOD_DESCRIPTION, "Org", 60, llm=_StubLLM())
        vague = score_submission(
            photo_bytes, "helped", "Org", 60, llm=_StubLLM(description_specificity=0.05)
        )
        assert vague["points"] < specific["points"]

    def test_threshold_is_the_documented_one(self, photo_bytes):
        below = score_submission(
            photo_bytes, GOOD_DESCRIPTION, "Org", 60,
            llm=_StubLLM(authenticity_confidence=MIN_AUTHENTICITY - 0.01),
        )
        at = score_submission(
            photo_bytes, GOOD_DESCRIPTION, "Org", 60,
            llm=_StubLLM(authenticity_confidence=MIN_AUTHENTICITY),
        )
        assert below["points"] == 0 and at["points"] > 0


class TestScoreSubmissionRobustness:
    @pytest.mark.parametrize("minutes", [0, None])
    def test_zero_or_missing_time_still_scores_the_visit(self, photo_bytes, minutes):
        result = score_submission(photo_bytes, GOOD_DESCRIPTION, "Org", minutes, llm=_StubLLM())
        assert result["points"] == 30  # base only, no time bonus

    def test_unreadable_photo_is_a_friendly_zero_not_a_crash(self, llm):
        result = score_submission("/no/such/file.jpg", GOOD_DESCRIPTION, "Org", 60, llm=llm)
        assert result["points"] == 0
        assert result["authenticity_confidence"] == 0.0
        assert "photo" in result["rationale"].lower()

    def test_provider_failure_is_a_retryable_zero(self, photo_bytes):
        class BrokenLLM:
            def complete_json(self, **kwargs):
                raise ProviderError("503")

        result = score_submission(photo_bytes, GOOD_DESCRIPTION, "Org", 60, llm=BrokenLLM())
        assert result["points"] == 0 and result["authenticity_confidence"] == 0.0

    def test_empty_model_response_does_not_crash(self, photo_bytes):
        class TerseLLM:
            def complete_json(self, **kwargs):
                return {}

        result = score_submission(photo_bytes, GOOD_DESCRIPTION, "Org", 60, llm=TerseLLM())
        assert result["points"] == 0
        assert result["rationale"]

    def test_accepts_a_file_path(self, photo_file, llm):
        assert score_submission(photo_file, GOOD_DESCRIPTION, "Org", 60, llm=llm)["rationale"]

    def test_accepts_a_url_without_downloading_it(self, llm):
        result = score_submission(
            "https://cdn.example.com/photo.jpg", GOOD_DESCRIPTION, "Org", 60, llm=llm
        )
        assert set(result) == {"points", "tier_points", "authenticity_confidence", "rationale"}

    def test_the_photo_is_actually_sent_to_the_model(self, photo_bytes):
        stub = _StubLLM()
        score_submission(photo_bytes, GOOD_DESCRIPTION, "Org", 60, llm=stub)
        content = stub.calls[0]["content"]
        assert any(block["type"] == "image" for block in content)
        assert any(block["type"] == "text" for block in content)

    def test_web_search_is_not_used_for_scoring(self, photo_bytes):
        stub = _StubLLM()
        score_submission(photo_bytes, GOOD_DESCRIPTION, "Org", 60, llm=stub)
        assert not stub.calls[0].get("use_web_search", False)


class TestClassifyReport:
    def test_returns_the_contract_keys(self, photo_bytes, llm):
        result = classify_report(photo_bytes, "Pile of trash bags at the bus stop", llm=llm)
        assert "category" in result and "is_valid" in result
        assert isinstance(result["is_valid"], bool)
        assert result["category"] in REPORT_CATEGORIES

    def test_category_is_coerced_into_the_known_set(self, photo_bytes):
        class InventiveLLM:
            def complete_json(self, **kwargs):
                return {"category": "space_debris", "is_valid": True, "confidence": 0.9, "reason": "x"}

        assert classify_report(photo_bytes, "x", llm=InventiveLLM())["category"] == "other"

    def test_spam_is_rejected_by_the_mock(self, photo_bytes, llm):
        result = classify_report(photo_bytes, "spam spam buy now", llm=llm)
        assert result["is_valid"] is False

    def test_unreadable_photo_is_rejected(self, llm):
        result = classify_report("/no/such/file.jpg", "trash", llm=llm)
        assert result["is_valid"] is False and result["confidence"] == 0.0

    def test_provider_failure_rejects_rather_than_publishing_unreviewed(self, photo_bytes):
        class BrokenLLM:
            def complete_json(self, **kwargs):
                raise ProviderError("timeout")

        result = classify_report(photo_bytes, "trash", llm=BrokenLLM())
        assert result["is_valid"] is False
        assert result["confidence"] == 0.0

    def test_works_without_a_description(self, photo_bytes, llm):
        assert "category" in classify_report(photo_bytes, llm=llm)
