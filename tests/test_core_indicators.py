"""core.indicators: 共享取数 helper + TechnicalIndicator。"""
import pandas as pd
from investbrief.core.indicators import get_index_series, TechnicalIndicator


def test_get_index_series_cn():
    captured = {}

    class _FakeData:
        def query(self, sql, params=()):
            captured["sql"] = sql
            return pd.DataFrame([{"date": "2024-01-01", "close": 3000.0}])

    df = get_index_series(_FakeData(), "cn", days=10)
    assert len(df) == 1
    assert "cn_index_daily" in captured["sql"]


def test_get_index_series_gold_uses_macro():
    captured = {}

    class _FakeData:
        def query(self, sql, params=()):
            captured["sql"] = sql
            return pd.DataFrame([{"date": "2024-01-01", "close": 2000.0}])

    df = get_index_series(_FakeData(), "gold", days=10)
    assert len(df) == 1
    assert "macro_data" in captured["sql"]


def test_technical_indicator_calculate_returns_keys():
    """TechnicalIndicator 应产出 ma50_deviation + volume_shrinkage。"""

    class _FakeData:
        def query(self, sql, params=()):
            return pd.DataFrame([
                {"date": f"2024-01-{i:02d}", "close": 3000.0 + i, "volume": 1e8}
                for i in range(1, 101)
            ])

    cfg = {
        "ma50_deviation": {"thresholds": {"cn": 20}, "low_thresholds": {"cn": 0}},
        "volume_shrinkage": {"thresholds": {"cn": 0.7}},
    }
    ind = TechnicalIndicator(market="cn", config=cfg)
    result = ind.calculate(_FakeData())
    assert "ma50_deviation" in result
    assert "volume_shrinkage" in result
    assert "score" in result["ma50_deviation"]
    assert "score" in result["volume_shrinkage"]
