"""Tests for risk config + scoring helpers (formerly risk/calc_utils)."""

import pandas as pd
import pytest

from investbrief.risk.config import (
    CN_ALL_INDICATORS, US_ALL_INDICATORS, MARKET_STATE_MAP,
    COMMON_INDICATORS, CN_INDICATORS, US_INDICATORS,
)
from investbrief.core.scoring import (
    moving_average, normalize_score, percentile_rank,
    calculate_macd, consecutive_count, safe_divide,
)


class TestConfig:
    def test_cn_weights_sum_to_one(self):
        total = sum(ind["weight"] for ind in CN_ALL_INDICATORS.values())
        assert abs(total - 1.0) < 0.001, f"CN weights sum to {total}, expected 1.0"

    def test_us_weights_sum_to_one(self):
        total = sum(ind["weight"] for ind in US_ALL_INDICATORS.values())
        assert abs(total - 1.0) < 0.001, f"US weights sum to {total}, expected 1.0"

    def test_common_weights_sum(self):
        total = sum(ind["weight"] for ind in COMMON_INDICATORS.values())
        assert abs(total - 0.09) < 0.001

    def test_cn_specific_weights_sum(self):
        total = sum(ind["weight"] for ind in CN_INDICATORS.values())
        assert abs(total - 0.91) < 0.001

    def test_us_specific_weights_sum(self):
        total = sum(ind["weight"] for ind in US_INDICATORS.values())
        assert abs(total - 0.91) < 0.001

    def test_market_state_has_six_entries(self):
        assert len(MARKET_STATE_MAP) == 6

    def test_market_state_covers_full_range(self):
        assert MARKET_STATE_MAP[0][0] == 0
        assert MARKET_STATE_MAP[-1][1] == 100

    def test_all_thresholds_are_numeric(self):
        for indicators in [CN_ALL_INDICATORS, US_ALL_INDICATORS]:
            for key, ind in indicators.items():
                market = "cn" if "cn" in ind.get("thresholds", {}) else "us"
                threshold = ind["thresholds"].get(market)
                if threshold is not None:
                    assert isinstance(threshold, (int, float)), \
                        f"{key} threshold is not numeric: {threshold}"


class TestCalcUtils:
    def test_moving_average(self):
        s = pd.Series([1, 2, 3, 4, 5])
        result = moving_average(s, 3)
        assert pd.isna(result.iloc[0])
        assert pd.isna(result.iloc[1])
        assert result.iloc[2] == 2.0
        assert result.iloc[3] == 3.0
        assert result.iloc[4] == 4.0

    def test_normalize_score_at_boundaries(self):
        assert normalize_score(0, 0, 10) == 0.0
        assert normalize_score(10, 0, 10) == 10.0
        assert normalize_score(5, 0, 10) == 5.0

    def test_normalize_score_beyond_boundaries(self):
        assert normalize_score(-5, 0, 10) == 0.0
        assert normalize_score(15, 0, 10) == 10.0

    def test_normalize_score_inverted(self):
        assert normalize_score(2.0, 1.0, 0.5, invert=True) == 0.0
        assert normalize_score(0.5, 1.0, 0.5, invert=True) == 10.0

    def test_percentile_rank(self):
        s = pd.Series([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
        assert percentile_rank(5, s) == 40.0
        assert percentile_rank(1, s) == 0.0
        assert percentile_rank(10, s) == 90.0

    def test_macd_returns_three_series(self):
        s = pd.Series(range(100), dtype=float)
        macd, signal, hist = calculate_macd(s)
        assert len(macd) == 100
        assert len(signal) == 100
        assert len(hist) == 100

    def test_consecutive_count(self):
        s = pd.Series([True, True, True, False, True])
        assert consecutive_count(s, lambda x: x) == 1
        s2 = pd.Series([True, True, True])
        assert consecutive_count(s2, lambda x: x) == 3

    def test_safe_divide(self):
        assert safe_divide(10, 2) == 5.0
        assert safe_divide(10, 0) == 0.0
        assert safe_divide(10, 0, default=-1) == -1


def test_score_to_risk_level_thresholds():
    """score_to_risk_level maps score ranges to low/moderate/high/extreme."""
    from investbrief.risk.config import score_to_risk_level
    assert score_to_risk_level(0) == "low"
    assert score_to_risk_level(19.9) == "low"
    assert score_to_risk_level(20) == "moderate"
    assert score_to_risk_level(39.9) == "moderate"
    assert score_to_risk_level(40) == "high"
    assert score_to_risk_level(69.9) == "high"
    assert score_to_risk_level(70) == "extreme"
    assert score_to_risk_level(100) == "extreme"


def test_score_to_risk_level_out_of_range():
    from investbrief.risk.config import score_to_risk_level
    # >100 (theoretical) clamps to moderate (no match in RISK_LEVEL_MAP)
    assert score_to_risk_level(150) == "moderate"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
