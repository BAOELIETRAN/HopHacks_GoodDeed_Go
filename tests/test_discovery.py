"""find_opportunities / trust_check, against mock providers."""

from __future__ import annotations

import pytest

from gooddeed_agent import categorize, find_opportunities, heuristic_legitimacy, trust_check
from gooddeed_agent.providers.base import ProviderError

BALTIMORE = (39.2904, -76.6122)


class TestCategorize:
    @pytest.mark.parametrize(
        "query,name,expected",
        [
            ("animal shelter", "Second Chance Animal Rescue", "animal_shelter"),
            ("homeless shelter", "Hope Street Shelter", "homeless_shelter"),
            ("food bank", "Riverside Food Bank", "food_bank"),
            ("thrift store charity", "Northgate Thrift", "thrift_donation"),
            ("", "Lincoln Library Literacy Program", "education"),
        ],
    )
    def test_query_and_name_drive_the_category(self, query, name, expected):
        assert categorize([], query, name) == expected

    def test_animal_shelter_is_not_mistaken_for_homeless_shelter(self):
        # "shelter" is a substring of "animal shelter"; specificity must win.
        assert categorize([], "animal shelter", "City Animal Shelter") == "animal_shelter"

    def test_falls_back_to_places_types(self):
        assert categorize(["food_bank", "establishment"], "", "Anonymous Org") == "food_bank"

    def test_unrecognizable_place_is_other(self):
        assert categorize(["point_of_interest"], "", "Untitled") == "other"


class TestHeuristicLegitimacy:
    def test_well_reviewed_org_with_a_website_scores_high(self):
        score = heuristic_legitimacy(
            {"rating": 4.7, "rating_count": 600, "website": "https://x.org", "business_status": "OPERATIONAL"}
        )
        assert score >= 0.8

    def test_permanently_closed_org_scores_low(self):
        score = heuristic_legitimacy(
            {"rating": 4.7, "rating_count": 600, "website": "https://x.org", "business_status": "CLOSED_PERMANENTLY"}
        )
        assert score < 0.4

    def test_unknown_org_lands_near_neutral(self):
        assert 0.3 <= heuristic_legitimacy({}) <= 0.6

    def test_always_in_range(self):
        extremes = [
            {"rating": 5.0, "rating_count": 10_000, "website": "x", "business_status": "OPERATIONAL"},
            {"rating": 0.0, "rating_count": 0, "business_status": "CLOSED_PERMANENTLY"},
        ]
        for place in extremes:
            assert 0.0 <= heuristic_legitimacy(place) <= 1.0


class TestFindOpportunities:
    def test_returns_contract_shaped_dicts(self, places, llm):
        results = find_opportunities(*BALTIMORE, 5.0, places=places, llm=llm)
        assert results
        expected_keys = {
            "org_name", "address", "lat", "lng", "category", "legitimacy_score", "quest_type"
        }
        for opportunity in results:
            assert set(opportunity) == expected_keys
            assert 0.0 <= opportunity["legitimacy_score"] <= 1.0
            assert opportunity["quest_type"] in {"daily", "monthly"}
            assert isinstance(opportunity["lat"], float)

    def test_results_are_near_the_requested_point(self, places, llm):
        lat, lng = BALTIMORE
        for opportunity in find_opportunities(lat, lng, 3.0, places=places, llm=llm):
            assert abs(opportunity["lat"] - lat) < 0.1
            assert abs(opportunity["lng"] - lng) < 0.1

    def test_sorted_by_legitimacy_descending(self, places, llm):
        scores = [o["legitimacy_score"] for o in find_opportunities(*BALTIMORE, 5.0, places=places, llm=llm)]
        assert scores == sorted(scores, reverse=True)

    def test_respects_max_results(self, places, llm):
        assert len(find_opportunities(*BALTIMORE, 5.0, max_results=3, places=places, llm=llm)) == 3

    def test_min_legitimacy_filters(self, places, llm):
        strict = find_opportunities(*BALTIMORE, 5.0, min_legitimacy=0.85, places=places, llm=llm)
        loose = find_opportunities(*BALTIMORE, 5.0, min_legitimacy=0.0, places=places, llm=llm)
        assert len(strict) < len(loose)
        assert all(o["legitimacy_score"] >= 0.85 for o in strict)

    def test_impossible_threshold_returns_empty_not_an_error(self, places, llm):
        assert find_opportunities(*BALTIMORE, 5.0, min_legitimacy=1.01, places=places, llm=llm) == []

    def test_deterministic_for_the_same_input(self, places, llm):
        first = find_opportunities(*BALTIMORE, 5.0, places=places, llm=llm)
        second = find_opportunities(*BALTIMORE, 5.0, places=places, llm=llm)
        assert first == second

    def test_verify_mode_still_returns_the_contract_shape(self, places, llm):
        results = find_opportunities(*BALTIMORE, 5.0, verify=True, max_verify=2, places=places, llm=llm)
        assert results
        assert all(0.0 <= o["legitimacy_score"] <= 1.0 for o in results)

    def test_places_failure_degrades_to_empty_not_a_crash(self, llm):
        class BrokenPlaces:
            def search_nearby(self, *args, **kwargs):
                raise ProviderError("quota exceeded")

        assert find_opportunities(*BALTIMORE, 5.0, places=BrokenPlaces(), llm=llm) == []

    def test_custom_queries_are_used(self, llm):
        seen: list[str] = []

        class RecordingPlaces:
            def search_nearby(self, lat, lng, radius_km, queries, max_results=20):
                seen.extend(queries)
                return []

        find_opportunities(*BALTIMORE, 5.0, queries=["beach cleanup"], places=RecordingPlaces(), llm=llm)
        assert seen == ["beach cleanup"]


class TestTrustCheck:
    def test_returns_contract_shape(self, llm):
        result = trust_check("Riverside Community Food Bank", "2625 Maple Ave", llm=llm)
        assert set(result) == {"legit", "confidence", "summary"}
        assert isinstance(result["legit"], bool)
        assert 0.0 <= result["confidence"] <= 1.0
        assert isinstance(result["summary"], str)

    def test_provider_failure_returns_unverifiable_not_an_exception(self):
        class BrokenLLM:
            def complete_json(self, **kwargs):
                raise ProviderError("network down")

        result = trust_check("Some Org", "Somewhere", llm=BrokenLLM())
        assert result["legit"] is False
        # confidence 0.0 is how callers tell "couldn't check" from "checked, it's fake".
        assert result["confidence"] == 0.0

    def test_confidence_is_clamped_when_the_model_misbehaves(self):
        class WildLLM:
            def complete_json(self, **kwargs):
                return {"legit": True, "confidence": 7.4, "summary": "sure"}

        assert trust_check("Org", "", llm=WildLLM())["confidence"] == 1.0

    def test_missing_fields_do_not_crash(self):
        class TerseLLM:
            def complete_json(self, **kwargs):
                return {}

        result = trust_check("Org", "", llm=TerseLLM())
        assert result == {"legit": False, "confidence": 0.0, "summary": ""}
