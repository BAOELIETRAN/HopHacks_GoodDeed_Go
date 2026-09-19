"""Philanthropic search coverage: the query packs and the category mapping."""

from __future__ import annotations

import pytest

from gooddeed_agent import find_opportunities
from gooddeed_agent.discovery import (
    DEFAULT_QUERIES,
    QUERY_PACKS,
    all_queries,
    categorize,
    queries_for_packs,
)
from gooddeed_agent.scoring import CATEGORY_BASE_POINTS


class _RecordingPlaces:
    def __init__(self):
        self.queries: list[str] = []

    def search_nearby(self, lat, lng, radius_km, queries, max_results=20):
        self.queries = list(queries)
        return []


class TestQueryPacks:
    def test_every_query_is_a_non_empty_string(self):
        for name, pack in QUERY_PACKS.items():
            assert pack, f"{name} is empty"
            for query in pack:
                assert isinstance(query, str) and query.strip(), f"{name}: {query!r}"

    def test_covers_the_breadth_of_philanthropy(self):
        # Domains a volunteering app should not silently omit.
        required = {
            "food", "housing", "animals", "environment", "health", "seniors",
            "youth_education", "crisis", "veterans", "disability", "immigrant",
            "goods", "community", "disaster", "arts",
        }
        assert required <= set(QUERY_PACKS)

    def test_all_queries_is_deduped(self):
        everything = all_queries()
        assert len(everything) == len(set(everything))

    def test_default_draws_from_the_packs(self):
        everything = set(all_queries())
        assert set(DEFAULT_QUERIES) <= everything

    def test_default_touches_most_domains(self):
        hit = {
            name for name, pack in QUERY_PACKS.items()
            if set(pack) & set(DEFAULT_QUERIES)
        }
        assert len(hit) >= 12, f"default fan-out only reaches {sorted(hit)}"

    def test_queries_for_packs_selects_and_dedupes(self):
        selected = queries_for_packs(["food", "animals"])
        assert set(selected) == set(QUERY_PACKS["food"]) | set(QUERY_PACKS["animals"])
        assert len(selected) == len(set(selected))

    def test_unknown_pack_raises_with_the_valid_names(self):
        with pytest.raises(ValueError, match="Unknown query pack"):
            queries_for_packs(["food", "nonsense"])


class TestCategoryCoverage:
    @pytest.mark.parametrize("query", all_queries())
    def test_every_query_maps_to_a_real_category(self, query):
        assert categorize([], query, "") in CATEGORY_BASE_POINTS

    @pytest.mark.parametrize(
        "query,expected",
        [
            ("domestic violence shelter", "crisis_support"),
            ("addiction recovery center", "crisis_support"),
            ("animal shelter", "animal_shelter"),
            ("wildlife rehabilitation center", "animal_shelter"),
            ("rescue mission", "homeless_shelter"),
            ("homeless shelter", "homeless_shelter"),
            ("veterans organization", "veterans"),
            ("disability services nonprofit", "disability_services"),
            ("refugee resettlement agency", "refugee_services"),
            ("community garden", "environmental"),
            ("blood donation center", "healthcare"),
            ("meals on wheels", "senior_care"),
            ("museum", "arts_culture"),
            ("red cross", "disaster_relief"),
            ("boys and girls club", "youth_program"),
        ],
    )
    def test_specific_queries_beat_generic_substrings(self, query, expected):
        # These are the collisions that ordering has to get right:
        # "domestic violence shelter" vs "shelter", "rescue mission" vs
        # "animal rescue", "wildlife" vs nothing.
        assert categorize([], query, "") == expected

    def test_only_deliberately_generic_queries_fall_through(self):
        fell_through = {q for q in all_queries() if categorize([], q, "") == "other"}
        assert fell_through == {"volunteer organization", "nonprofit organization", "charity"}

    def test_every_category_is_reachable_from_some_query_or_name(self):
        reachable = {categorize([], q, "") for q in all_queries()}
        reachable |= {categorize([], "", n) for n in ["First Baptist Church", "Neighborhood Cleanup Day"]}
        missing = set(CATEGORY_BASE_POINTS) - reachable
        assert missing == set(), f"unreachable categories: {missing}"


class TestFanOutControls:
    def test_default_uses_the_default_fan_out(self, llm):
        places = _RecordingPlaces()
        find_opportunities(39.29, -76.61, 5.0, places=places, llm=llm)
        assert places.queries == list(DEFAULT_QUERIES)

    def test_packs_replace_the_default(self, llm):
        places = _RecordingPlaces()
        find_opportunities(39.29, -76.61, 5.0, packs=["food"], places=places, llm=llm)
        assert places.queries == list(QUERY_PACKS["food"])

    def test_all_expands_to_every_domain(self, llm):
        places = _RecordingPlaces()
        find_opportunities(39.29, -76.61, 5.0, packs=["all"], max_queries=99, places=places, llm=llm)
        assert set(places.queries) == set(all_queries())

    def test_explicit_queries_win_over_packs(self, llm):
        places = _RecordingPlaces()
        find_opportunities(
            39.29, -76.61, 5.0, queries=["beach cleanup"], packs=["food"], places=places, llm=llm
        )
        assert places.queries == ["beach cleanup"]

    def test_max_queries_caps_the_spend(self, llm):
        places = _RecordingPlaces()
        find_opportunities(39.29, -76.61, 5.0, packs=["all"], max_queries=5, places=places, llm=llm)
        assert len(places.queries) == 5

    def test_default_stays_within_the_default_cap(self):
        # A regression guard: growing DEFAULT_QUERIES past max_queries would
        # silently truncate it instead of erroring.
        assert len(DEFAULT_QUERIES) <= 24


class TestDiversification:
    """A map showing 20 food banks is a worse game than one showing 15
    different kinds of help, even if the food banks rank higher."""

    def _places(self, records):
        class Fixed:
            def search_nearby(self, *a, **k):
                return records
        return Fixed()

    def _record(self, name, query, rating_count, place_id):
        return {
            "name": name, "address": "1 Main St", "lat": 39.29, "lng": -76.61,
            "types": [], "rating": 4.5, "rating_count": rating_count,
            "website": "https://x.org", "business_status": "OPERATIONAL",
            "place_id": place_id, "matched_query": query,
        }

    def test_one_dominant_category_does_not_crowd_out_the_rest(self, llm):
        # 20 highly-rated food banks, 2 lower-rated animal shelters.
        records = [self._record(f"Food Bank {i}", "food bank", 900, f"f{i}") for i in range(20)]
        records += [self._record(f"Animal Rescue {i}", "animal shelter", 30, f"a{i}") for i in range(2)]
        result = find_opportunities(
            39.29, -76.61, 5.0, max_results=6, places=self._places(records), llm=llm
        )
        categories = {o["category"] for o in result}
        assert "animal_shelter" in categories, "lower-scoring category was starved out"

    def test_diversify_off_gives_a_strict_legitimacy_ranking(self, llm):
        records = [self._record(f"Food Bank {i}", "food bank", 900, f"f{i}") for i in range(20)]
        records += [self._record("Animal Rescue", "animal shelter", 30, "a0")]
        result = find_opportunities(
            39.29, -76.61, 5.0, max_results=5, diversify=False,
            places=self._places(records), llm=llm,
        )
        scores = [o["legitimacy_score"] for o in result]
        assert scores == sorted(scores, reverse=True)
        assert {o["category"] for o in result} == {"food_bank"}

    def test_best_org_overall_still_leads(self, llm):
        records = [self._record("Top Food Bank", "food bank", 5000, "f0")]
        records += [self._record(f"Animal Rescue {i}", "animal shelter", 10, f"a{i}") for i in range(3)]
        result = find_opportunities(
            39.29, -76.61, 5.0, max_results=4, places=self._places(records), llm=llm
        )
        assert result[0]["org_name"] == "Top Food Bank"

    def test_a_chain_does_not_take_every_slot_in_its_category(self, llm):
        # Four branches of one chain plus one independent, all same category.
        records = [self._record("Chain Thrift", "thrift store charity", 500, f"c{i}") for i in range(4)]
        records += [self._record("Indie Thrift", "thrift store charity", 100, "i0")]
        result = find_opportunities(
            39.29, -76.61, 5.0, max_results=2, places=self._places(records), llm=llm
        )
        assert {o["org_name"] for o in result} == {"Chain Thrift", "Indie Thrift"}

    def test_separate_branches_are_still_kept_not_deduped(self, llm):
        # Two real branches at different place_ids are two valid map pins.
        records = [self._record("Chain Thrift", "thrift store charity", 500, f"c{i}") for i in range(3)]
        result = find_opportunities(
            39.29, -76.61, 5.0, max_results=10, places=self._places(records), llm=llm
        )
        assert len(result) == 3
