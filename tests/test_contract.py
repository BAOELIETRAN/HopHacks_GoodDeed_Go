"""Guards on the shared data contract.

These exist so a future refactor cannot silently rename a field the backend
or the UI depends on. Every name below is copied from the team contract.
"""

from __future__ import annotations

from dataclasses import fields

import pytest

from gooddeed_agent import classify_report, find_opportunities, score_submission, trust_check
from gooddeed_agent.models import (
    CommunityReport,
    Opportunity,
    ReportClassification,
    ScoreResult,
    Submission,
    TrustResult,
)
from gooddeed_agent.vision import classify_report_from_dict, score_submission_from_dict

CONTRACT = {
    Submission: [
        "user_id", "org_name", "photo_url", "description",
        "time_spent_minutes", "lat", "lng", "submitted_at",
    ],
    Opportunity: [
        "org_name", "address", "lat", "lng", "category", "legitimacy_score", "quest_type",
    ],
    TrustResult: ["legit", "confidence", "summary"],
    CommunityReport: [
        "report_id", "photo_url", "description", "lat", "lng",
        "status", "claimed_by", "created_at",
    ],
}


@pytest.mark.parametrize("model,expected", CONTRACT.items(), ids=lambda v: getattr(v, "__name__", ""))
def test_model_fields_match_the_contract_exactly(model, expected):
    assert [f.name for f in fields(model)] == expected


def test_score_result_contract_fields_come_first_and_debug_is_extra():
    names = [f.name for f in fields(ScoreResult)]
    assert names[:4] == ["points", "tier_points", "authenticity_confidence", "rationale"]
    assert names[4:] == ["debug"]


def test_report_classification_leads_with_the_two_contract_fields():
    assert [f.name for f in fields(ReportClassification)][:2] == ["category", "is_valid"]


def test_opportunity_output_is_contract_exact_by_default(places, llm):
    [first, *_] = find_opportunities(39.29, -76.61, 5.0, places=places, llm=llm)
    assert list(first) == CONTRACT[Opportunity]


def test_description_is_opt_in_and_never_replaces_a_contract_field(places, llm):
    [first, *_] = find_opportunities(
        39.29, -76.61, 5.0, verify=True, max_verify=1, include_description=True,
        places=places, llm=llm,
    )
    assert set(CONTRACT[Opportunity]) < set(first)
    assert "description" in first


def test_score_result_output_is_contract_exact(photo_bytes, llm):
    result = score_submission(photo_bytes, "A specific, detailed deed description here.", "Org", 60, llm=llm)
    assert list(result) == ["points", "tier_points", "authenticity_confidence", "rationale"]


def test_trust_result_output_is_contract_exact(llm):
    assert list(trust_check("Org", "1 Main St", llm=llm)) == ["legit", "confidence", "summary"]


def test_classify_report_includes_both_contract_fields(photo_bytes, llm):
    result = classify_report(photo_bytes, "Trash piled at the bus stop on 3rd", llm=llm)
    assert {"category", "is_valid"} <= set(result)


class TestBackendAdapters:
    """The backend stores `photo_url`; the functions take `photo`. These
    adapters are what keeps that mismatch from becoming a bug."""

    SUBMISSION = {
        "user_id": "u-1",
        "org_name": "Riverside Community Food Bank",
        "photo_url": "https://cdn.example.com/deed.jpg",
        "description": "Sorted canned goods into family boxes for three hours.",
        "time_spent_minutes": 180,
        "lat": 39.29,
        "lng": -76.61,
        "submitted_at": "2026-09-19T14:03:00Z",
    }
    REPORT = {
        "report_id": "r-1",
        "photo_url": "https://cdn.example.com/trash.jpg",
        "description": "Overflowing bins at 3rd and Maple",
        "lat": 39.29,
        "lng": -76.61,
        "status": "open",
        "claimed_by": None,
        "created_at": "2026-09-19T09:00:00Z",
    }

    def test_scores_a_submission_dict(self, llm):
        result = score_submission_from_dict(self.SUBMISSION, llm=llm)
        assert list(result) == ["points", "tier_points", "authenticity_confidence", "rationale"]

    def test_scores_a_submission_dataclass(self, llm):
        result = score_submission_from_dict(Submission.from_dict(self.SUBMISSION), llm=llm)
        assert "points" in result

    def test_extra_backend_keys_are_ignored(self, llm):
        noisy = {**self.SUBMISSION, "id": 99, "internal_flag": True}
        assert "points" in score_submission_from_dict(noisy, llm=llm)

    def test_options_pass_through(self, llm):
        result = score_submission_from_dict(self.SUBMISSION, category="food_bank", include_debug=True, llm=llm)
        assert result["debug"]["category_used"] == "food_bank"

    def test_triages_a_report_dict(self, llm):
        result = classify_report_from_dict(self.REPORT, llm=llm)
        assert {"category", "is_valid"} <= set(result)

    def test_report_roundtrips_through_the_model(self):
        assert CommunityReport.from_dict(self.REPORT).to_dict() == self.REPORT

    def test_submission_roundtrips_through_the_model(self):
        assert Submission.from_dict(self.SUBMISSION).to_dict() == self.SUBMISSION

    def test_report_defaults_match_the_contract(self):
        minimal = CommunityReport("r-2", "u", "d", 1.0, 2.0)
        assert minimal.status == "open" and minimal.claimed_by is None
