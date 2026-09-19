"""Small organizations must not be buried.

Most philanthropy is small -- neighborhood fridges, church pantries,
volunteer-run gardens. An earlier version scored review count with a 0.30
spread, which made "popular" and "legitimate" the same thing and pushed half
the discovered orgs off the map. These tests pin the fix.
"""

from __future__ import annotations

import pytest

from gooddeed_agent import find_opportunities
from gooddeed_agent.discovery import (
    GRASSROOTS_REVIEW_THRESHOLD,
    QUERY_PACKS,
    categorize,
    heuristic_legitimacy,
    is_grassroots,
)

OPERATIONAL = {"business_status": "OPERATIONAL"}


def place(**kw):
    return {**OPERATIONAL, **kw}


class TestSmallIsNotSuspicious:
    def test_few_reviews_is_never_a_penalty(self):
        # A brand-new org is unknown, not illegitimate.
        assert heuristic_legitimacy(place(rating_count=0)) >= 0.5
        assert heuristic_legitimacy(place(rating_count=2)) >= heuristic_legitimacy(
            place(rating_count=0)
        )

    def test_a_small_good_org_scores_close_to_a_huge_one(self):
        tiny = heuristic_legitimacy(place(rating=4.8, rating_count=9, website="https://x.org"))
        huge = heuristic_legitimacy(place(rating=4.6, rating_count=1380, website="https://x.org"))
        assert huge - tiny <= 0.10, f"popularity still dominates: {tiny} vs {huge}"

    def test_a_small_good_org_beats_a_big_badly_reviewed_one(self):
        tiny = heuristic_legitimacy(place(rating=4.8, rating_count=9, website="https://x.org"))
        bad_big = heuristic_legitimacy(place(rating=2.1, rating_count=200, website="https://x.org"))
        assert tiny > bad_big

    def test_review_signal_saturates(self):
        # 20 reviews confirm existence about as well as 2000 do.
        twenty = heuristic_legitimacy(place(rating_count=20))
        many = heuristic_legitimacy(place(rating_count=2000))
        assert many == twenty

    def test_a_tiny_org_clears_the_default_filter(self):
        assert heuristic_legitimacy(place(rating=5.0, rating_count=3)) >= 0.4

    def test_closure_still_overrides_everything(self):
        assert heuristic_legitimacy(
            place(rating=4.9, rating_count=900, website="x", business_status="CLOSED_PERMANENTLY")
        ) == 0.0


class TestGrassrootsFlag:
    @pytest.mark.parametrize("count,expected", [(0, True), (5, True), (24, True), (25, False), (900, False)])
    def test_threshold(self, count, expected):
        assert is_grassroots({"rating_count": count}) is expected

    def test_missing_count_is_treated_as_grassroots(self):
        assert is_grassroots({}) is True


class TestGrassrootsPack:
    def test_pack_exists_with_local_terms(self):
        assert "grassroots" in QUERY_PACKS
        assert {"mutual aid", "community fridge", "little free library"} <= set(
            QUERY_PACKS["grassroots"]
        )

    @pytest.mark.parametrize(
        "query,expected",
        [
            ("community fridge", "food_bank"),
            ("mutual aid", "community_center"),
            ("little free library", "education"),
            ("tool library", "community_center"),   # not "library" -> education
            ("free store", "thrift_donation"),
            ("neighborhood association", "community_center"),
        ],
    )
    def test_grassroots_terms_categorize_sensibly(self, query, expected):
        assert categorize([], query, "") == expected


class TestSmallOrgsReachTheMap:
    def _places(self, records):
        class Fixed:
            def search_nearby(self, *a, **k):
                return records
        return Fixed()

    def _org(self, name, query, rating_count, pid):
        return {
            "name": name, "address": "1 Main St", "lat": 39.29, "lng": -76.61,
            "types": [], "rating": 4.7, "rating_count": rating_count,
            "website": "https://x.org", "business_status": "OPERATIONAL",
            "place_id": pid, "matched_query": query,
        }

    def test_big_orgs_do_not_take_every_slot_in_a_category(self, llm):
        records = [self._org(f"Big Food Bank {i}", "food bank", 900, f"b{i}") for i in range(10)]
        records += [self._org(f"Corner Fridge {i}", "community fridge", 4, f"s{i}") for i in range(5)]
        result = find_opportunities(
            39.29, -76.61, 5.0, max_results=6, places=self._places(records), llm=llm
        )
        names = [o["org_name"] for o in result]
        assert any("Corner Fridge" in n for n in names), f"all big orgs: {names}"

    def test_grassroots_appear_early_not_only_at_the_tail(self, llm):
        records = []
        for i in range(6):
            records.append(self._org(f"Big Food Bank {i}", "food bank", 900, f"bf{i}"))
            records.append(self._org(f"Small Pantry {i}", "food pantry", 3, f"sf{i}"))
            records.append(self._org(f"Big Shelter {i}", "homeless shelter", 800, f"bs{i}"))
            records.append(self._org(f"Small Shelter {i}", "rescue mission", 2, f"ss{i}"))
        result = find_opportunities(
            39.29, -76.61, 5.0, max_results=8, places=self._places(records), llm=llm
        )
        top_half = [o["org_name"] for o in result[:4]]
        assert any("Small" in n for n in top_half), f"no small org in the top 4: {top_half}"

    def test_an_org_with_one_review_is_not_filtered_out(self, llm):
        records = [self._org("By Their Side", "disability services nonprofit", 1, "x1")]
        result = find_opportunities(39.29, -76.61, 5.0, places=self._places(records), llm=llm)
        assert [o["org_name"] for o in result] == ["By Their Side"]

    def test_threshold_is_the_documented_one(self):
        assert GRASSROOTS_REVIEW_THRESHOLD == 25
