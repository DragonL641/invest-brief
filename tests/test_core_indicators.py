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


def test_ma50_deviation_uses_percentile_scoring():
    """#10: ma50_deviation 改分位打分(与其他技术/估值指标同口径)。

    构造近 3 年震荡序列 + 当前值大幅突破(+20% vs MA50)→ 历史高位 → 高分。
    get_index_series 对 fake 返回的 df 做 .iloc[::-1] 反转, 故 spike 放在 row0
    (反转后变 iloc[-1] = "最新")。
    """
    import numpy as np

    class _FakeData:
        def query(self, sql, params=()):
            n = 800
            base = 100 + np.sin(np.arange(n) / 20) * 5   # 震荡序列(deviation ±5%)
            base[0] = 120.0                                # "最新" bar: +20% vs MA50
            return pd.DataFrame([
                {"date": f"2020-01-{(i % 28) + 1:02d}", "close": float(base[i]), "volume": 1e8}
                for i in range(n)
            ])

    cfg = {"ma50_deviation": {"thresholds": {"cn": 0.15}, "low_thresholds": {"cn": 0}}}
    ind = TechnicalIndicator(market="cn", config=cfg)
    r = ind._ma50_deviation(_FakeData())
    # 当前偏离(+~20%)远超历史震荡幅度(±5%)→ 历史顶 → 高分
    assert r["score"] >= 8.0, f"高位偏离应高分, got {r['score']}"
    assert r["percentile"] is not None and r["percentile"] >= 80
    assert "近3年分位" in (r.get("scoring") or "")


def test_ma50_deviation_short_history_returns_neutral():
    """#10: 样本不足(<100 deviation 点)→ 中性 5.0(与其他 percentile 指标一致)。"""

    class _FakeData:
        def query(self, sql, params=()):
            return pd.DataFrame([
                {"date": f"2024-01-{i:02d}", "close": 100.0 + i, "volume": 1e8}
                for i in range(1, 60)   # 不足 100 点
            ])

    ind = TechnicalIndicator(market="cn", config={})
    r = ind._ma50_deviation(_FakeData())
    assert r["score"] == 5.0
    assert r["value"] is None
