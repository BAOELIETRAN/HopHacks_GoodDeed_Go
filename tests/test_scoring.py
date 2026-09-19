"""The points economy. Pure math, so these are the tests to trust."""

from __future__ import annotations

import pytest

from gooddeed_agent import scoring


class TestCategories:
    def test_known_category_passes_through(self):
        assert scoring.normalize_category("food_bank") == "food_bank"

    @pytest.mark.parametrize("raw", ["Food Bank", "food-bank", "  FOOD_BANK  "])
    def test_category_normalization_is_forgiving(self, raw):
        assert scoring.normalize_category(raw) == "food_bank"

    @pytest.mark.parametrize("raw", ["not_a_real_category", "", None])
    def test_unknown_category_falls_back_instead_of_raising(self, raw):
        assert scoring.normalize_category(raw) == "other"

    def test_every_category_has_base_points(self):
        for category in scoring.CATEGORY_BASE_POINTS:
            assert scoring.base_points_for(category) > 0

    def test_monthly_categories_are_all_real_categories(self):
        assert scoring.MONTHLY_CATEGORIES <= set(scoring.CATEGORY_BASE_POINTS)


class TestTimeBonus:
    @pytest.mark.parametrize(
        "minutes,expected",
        [(0, 0), (None, 0), (-30, 0), (9, 0), (10, 1), (65, 6), (300, 30)],
    )
    def test_one_point_per_ten_minutes(self, minutes, expected):
        assert scoring.time_bonus(minutes) == expected

    def test_bonus_is_capped(self):
        assert scoring.time_bonus(100_000) == scoring.MAX_TIME_BONUS

    def test_implausible_duration_does_not_earn_past_the_cap(self):
        assert scoring.time_bonus(10_000) == scoring.time_bonus(scoring.PLAUSIBLE_MAX_MINUTES)


class TestComputePoints:
    def test_low_authenticity_earns_nothing(self):
        assert scoring.compute_points("food_bank", 120, 0.2) == (0, 0)

    def test_just_below_threshold_earns_nothing(self):
        assert scoring.compute_points("food_bank", 120, scoring.MIN_AUTHENTICITY - 0.01) == (0, 0)

    def test_at_threshold_earns_something(self):
        points, _ = scoring.compute_points("food_bank", 120, scoring.MIN_AUTHENTICITY)
        assert points > 0

    def test_confident_submission_scores_close_to_base_plus_bonus(self):
        # food_bank base 30 + 60min bonus 6 = 36, at full confidence.
        assert scoring.compute_points("food_bank", 60, 1.0) == (36, 36)

    def test_more_time_never_scores_less(self):
        previous = -1
        for minutes in range(0, 400, 20):
            points, _ = scoring.compute_points("food_bank", minutes, 0.9)
            assert points >= previous
            previous = points

    def test_multiplier_moves_points_but_not_tier_points(self):
        points, tier_points = scoring.compute_points("food_bank", 60, 1.0, quest_multiplier=1.5)
        assert points == 54
        assert tier_points == 36

    def test_points_are_capped(self):
        points, tier_points = scoring.compute_points(
            "homeless_shelter", 100_000, 1.0, quest_multiplier=10.0
        )
        assert points == scoring.MAX_POINTS_PER_SUBMISSION
        assert tier_points <= scoring.MAX_POINTS_PER_SUBMISSION

    @pytest.mark.parametrize("confidence", [-5.0, 1.5, 99])
    def test_out_of_range_confidence_is_clamped_not_crashing(self, confidence):
        points, _ = scoring.compute_points("food_bank", 60, confidence)
        assert 0 <= points <= scoring.MAX_POINTS_PER_SUBMISSION

    def test_returns_plain_ints(self):
        points, tier_points = scoring.compute_points("food_bank", 47, 0.83)
        assert isinstance(points, int) and isinstance(tier_points, int)


class TestTiers:
    @pytest.mark.parametrize(
        "total,expected",
        [
            (0, "Bronze"), (50, "Bronze"), (99, "Bronze"),
            (100, "Silver"), (300, "Silver"), (499, "Silver"),
            (500, "Gold"), (10_000, "Gold"),
            (-20, "Bronze"),
        ],
    )
    def test_tier_boundaries_match_the_contract(self, total, expected):
        assert scoring.tier_for_points(total) == expected

    @pytest.mark.parametrize(
        "total,expected", [(0, 100), (99, 1), (100, 400), (499, 1), (500, None), (900, None)]
    )
    def test_distance_to_next_tier(self, total, expected):
        assert scoring.points_to_next_tier(total) == expected


class TestQuestType:
    def test_commitment_categories_get_monthly(self):
        assert scoring.quest_type_for("homeless_shelter") == "monthly"

    def test_drop_in_categories_get_daily(self):
        assert scoring.quest_type_for("food_bank") == "daily"

    def test_is_deterministic(self):
        assert scoring.quest_type_for("education") == scoring.quest_type_for("education")

    def test_always_returns_a_contract_value(self):
        for category in list(scoring.CATEGORY_BASE_POINTS) + ["nonsense", None]:
            assert scoring.quest_type_for(category) in {"daily", "monthly"}


class TestLeaderboard:
    def test_orders_by_points_descending(self):
        board = scoring.leaderboard([("a", 10), ("b", 50), ("c", 30)])
        assert [row["user_id"] for row in board] == ["b", "c", "a"]

    def test_ties_share_a_rank_and_skip_the_next(self):
        board = scoring.leaderboard([("a", 50), ("b", 50), ("c", 10)])
        assert [row["rank"] for row in board] == [1, 1, 3]

    def test_ties_break_deterministically_by_user_id(self):
        first = scoring.leaderboard([("z", 5), ("a", 5)])
        second = scoring.leaderboard([("a", 5), ("z", 5)])
        assert first == second

    def test_empty_is_empty(self):
        assert scoring.leaderboard([]) == []
