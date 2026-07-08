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
    # NOTE: weights intentionally do NOT sum to 1.0. The 4 newer indicators
    # (market_breadth / pledge_ratio / north_flow / real_yield) were added on top
    # of the existing weights without reallocation (per task spec: "不重分配估值权重"),
    # because risk/models.py:calculate_score auto-normalizes via weighted_sum/total_weight
    # — only relative proportions matter, not the absolute total.
    CN_TOTAL = 1.26  # was 1.00 before B1/B2/B3 added market_breadth+pledge+north (+0.26)
    US_TOTAL = 1.10  # was 1.00 before B1 added market_breadth (+0.10)
    COMMON_TOTAL = 0.09
    CN_SPECIFIC_TOTAL = 1.17  # was 0.91
    US_SPECIFIC_TOTAL = 1.01  # was 0.91

    def test_cn_weights_documented(self):
        total = sum(ind["weight"] for ind in CN_ALL_INDICATORS.values())
        assert abs(total - self.CN_TOTAL) < 0.001, f"CN weights sum to {total}, expected {self.CN_TOTAL}"

    def test_us_weights_documented(self):
        total = sum(ind["weight"] for ind in US_ALL_INDICATORS.values())
        assert abs(total - self.US_TOTAL) < 0.001, f"US weights sum to {total}, expected {self.US_TOTAL}"

    def test_common_weights_sum(self):
        total = sum(ind["weight"] for ind in COMMON_INDICATORS.values())
        assert abs(total - self.COMMON_TOTAL) < 0.001

    def test_cn_specific_weights_sum(self):
        total = sum(ind["weight"] for ind in CN_INDICATORS.values())
        assert abs(total - self.CN_SPECIFIC_TOTAL) < 0.001

    def test_us_specific_weights_sum(self):
        total = sum(ind["weight"] for ind in US_INDICATORS.values())
        assert abs(total - self.US_SPECIFIC_TOTAL) < 0.001

    def test_market_state_has_six_entries(self):
        assert len(MARKET_STATE_MAP) == 6

    def test_market_state_covers_full_range(self):
        assert MARKET_STATE_MAP[0][0] == 0
        assert MARKET_STATE_MAP[-1][1] == 100

    def test_all_thresholds_are_numeric(self):
        # 纯分位指标(market_breadth/pledge_ratio/north_flow/real_yield)无固定阈值,
        # 由 percentile_score_from_series 算分; 这里只校验声明了 thresholds 的指标。
        for indicators in [CN_ALL_INDICATORS, US_ALL_INDICATORS]:
            for key, ind in indicators.items():
                thresholds = ind.get("thresholds", {})
                if not thresholds:
                    continue  # 纯分位指标, 无固定阈值
                market = "cn" if "cn" in thresholds else "us"
                threshold = thresholds.get(market)
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


class TestPercentileScoreFromSeries:
    """percentile_score_from_series 是 market_breadth/pledge_ratio/north_flow/real_yield
    共用的分位打分 helper。核心契约: latest 行该列为 NULL -> value None -> 退出加权
    (north_flow 2024-08 停发后行为关键)。"""

    def _data_source(self, tmp_path, sentiment_rows=None, macro_rows=None):
        from investbrief.data.cn_data import CNData
        db = CNData(db_path=str(tmp_path / "t.db"))
        if sentiment_rows:
            for market, date, breadth, pledge, north in sentiment_rows:
                db.conn.execute(
                    "INSERT OR REPLACE INTO sentiment_data "
                    "(market, date, market_breadth, pledge_ratio, north_flow) VALUES (?,?,?,?,?)",
                    (market, date, breadth, pledge, north),
                )
        if macro_rows:
            for indicator, country, date, value in macro_rows:
                db.conn.execute(
                    "INSERT OR REPLACE INTO macro_data (indicator, country, date, value) VALUES (?,?,?,?)",
                    (indicator, country, date, value),
                )
        db.conn.commit()
        return db

    def _many_history_rows(self, n, start_value=0.5):
        """生成 n 行 cn market_breadth 历史(升序日期), 全部非 NULL."""
        from datetime import date, timedelta
        base = date(2020, 1, 1)
        return [
            ("cn", (base + timedelta(days=i)).isoformat(), start_value, None, None)
            for i in range(n)
        ]

    def test_exits_weighting_when_latest_is_null(self, tmp_path):
        """latest 行该列为 NULL -> value None (退出加权, 见 models.py:79)。

        模拟 north_flow 2024-08-16 后停发: 历史有充足数据, 但最新行 NULL。
        """
        from investbrief.core.indicators import percentile_score_from_series
        rows = self._many_history_rows(150)  # 足够多历史, 全非 NULL
        # 追加一个 latest 行, north_flow=NULL (停发后)
        rows.append(("cn", "2026-07-08", None, None, None))
        ds = self._data_source(tmp_path, sentiment_rows=rows)
        try:
            r = percentile_score_from_series(
                ds, "sentiment_data", "north_flow", "market='cn'", invert=True,
            )
            assert r["value"] is None
            assert r["score"] == 5.0  # neutral, 退出加权
        finally:
            ds.close()

    def test_exits_weighting_when_sample_below_min(self, tmp_path):
        """历史样本 < min_samples -> value None (避免少量历史点导致分位失真)."""
        from investbrief.core.indicators import percentile_score_from_series
        rows = self._many_history_rows(50)  # < min_samples=100
        ds = self._data_source(tmp_path, sentiment_rows=rows)
        try:
            r = percentile_score_from_series(
                ds, "sentiment_data", "market_breadth", "market='cn'", invert=True,
            )
            assert r["value"] is None
            assert r["score"] == 5.0
        finally:
            ds.close()

    def test_normal_percentile_score(self, tmp_path):
        """充足历史 + 最新非 NULL -> 正常分位打分."""
        from investbrief.core.indicators import percentile_score_from_series
        # 150 行历史, 全 = 0.5; 最新行 = 0.9 (高分位 -> 高 score, 不 invert)
        rows = self._many_history_rows(150, start_value=0.5)
        rows.append(("cn", "2026-07-08", 0.9, None, None))
        ds = self._data_source(tmp_path, sentiment_rows=rows)
        try:
            r = percentile_score_from_series(
                ds, "sentiment_data", "market_breadth", "market='cn'", invert=False,
            )
            assert r["value"] is not None
            assert r["score"] >= 9.0  # 0.9 在 [0.5]*150 序列里接近 100 分位
            assert r["percentile"] is not None
        finally:
            ds.close()

    def test_invert_flips_score(self, tmp_path):
        """invert=True: 高分位 -> 低 score (e.g. 高 market_breadth = 低风险)."""
        from investbrief.core.indicators import percentile_score_from_series
        rows = self._many_history_rows(150, start_value=0.5)
        rows.append(("cn", "2026-07-08", 0.9, None, None))  # 高分位
        ds = self._data_source(tmp_path, sentiment_rows=rows)
        try:
            r_invert = percentile_score_from_series(
                ds, "sentiment_data", "market_breadth", "market='cn'", invert=True,
            )
            r_normal = percentile_score_from_series(
                ds, "sentiment_data", "market_breadth", "market='cn'", invert=False,
            )
            assert r_invert["score"] + r_normal["score"] == 10.0  # 互补
            assert r_invert["score"] <= 1.0  # 高分位 + invert -> 低 score
        finally:
            ds.close()

    def test_real_yield_via_macro_data(self, tmp_path):
        """helper 对 macro_data 单列(value)同样适用(REAL_YIELD_10Y 用途)."""
        from investbrief.core.indicators import percentile_score_from_series
        from datetime import date, timedelta
        base = date(2020, 1, 1)
        macro_rows = [
            ("REAL_YIELD_10Y", "us", (base + timedelta(days=i)).isoformat(), 1.0)
            for i in range(150)
        ]
        macro_rows.append(("REAL_YIELD_10Y", "us", "2026-07-08", 5.0))  # 高分位
        ds = self._data_source(tmp_path, macro_rows=macro_rows)
        try:
            r = percentile_score_from_series(
                ds, "macro_data", "value",
                "indicator='REAL_YIELD_10Y' AND country='us'", invert=True,
            )
            assert r["value"] is not None
            assert r["score"] <= 1.0  # 高分位 + invert -> 低 score
        finally:
            ds.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
