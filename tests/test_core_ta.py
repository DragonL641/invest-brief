"""core.ta: 抽取自 holdings/etf/indicators.py 的纯 TA 原语,数值与原实现一致。"""
import numpy as np
import pandas as pd

from investbrief.holdings.etf.indicators import compute_indicators


def _syn_hist(n=80, seed=42):
    rng = np.random.default_rng(seed)
    base = 10.0
    closes = base + np.cumsum(rng.normal(0, 0.2, n))
    vols = rng.integers(1_000_000, 5_000_000, n).astype(float)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame({"close": closes, "volume": vols}, index=idx)


def test_indicators_keys_present():
    """抽取 ta 后,compute_indicators 仍产出与基线一致的关键字段。"""
    out = compute_indicators(_syn_hist())
    for k in ("ma5", "ma10", "ma20", "ma60", "ma_alignment",
              "macd_dif", "macd_dea", "rsi", "return_5d", "return_60d",
              "volume_ratio", "regime"):
        assert k in out, f"missing {k}"
    assert out["ma_alignment"] in ("bullish", "bearish", "mixed")
    assert 0 <= out["rsi"] <= 100


def test_short_history_returns_empty():
    assert compute_indicators(pd.DataFrame({"close": [1, 2], "volume": [10, 20]})) == {}
