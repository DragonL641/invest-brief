# tests/test_picks_factors.py
"""picks.factors: 因子纯函数(对 hist_df/fundamentals/valuation 计算)。"""
import numpy as np
import pandas as pd

from investbrief.picks import factors


def _uptrend_hist(n=130):
    """稳定上涨序列:close 线性递增。"""
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    close = pd.Series(10 + 0.1 * np.arange(n), index=idx)
    vol = pd.Series(1e6 + 0 * np.arange(n), index=idx, dtype=float)
    return pd.DataFrame({"close": close, "volume": vol})


def test_factor_registry_contains_swing_keys():
    for k in ("trend_strength", "momentum_60d_ex5", "ma20_deviation",
              "volume_price", "low_volatility_20d"):
        assert k in factors.FACTOR_REGISTRY


def test_trend_strength_positive_in_uptrend():
    v = factors.FACTOR_REGISTRY["trend_strength"](_uptrend_hist(), {}, {})
    assert v is not None and v > 0


def test_momentum_60d_ex5_positive_in_uptrend():
    v = factors.FACTOR_REGISTRY["momentum_60d_ex5"](_uptrend_hist(), {}, {})
    assert v is not None and v > 0


def test_short_history_returns_none():
    short = _uptrend_hist(20)  # 不足 60 日
    assert factors.FACTOR_REGISTRY["momentum_60d_ex5"](short, {}, {}) is None


def test_low_volatility_returns_positive():
    v = factors.FACTOR_REGISTRY["low_volatility_20d"](_uptrend_hist(), {}, {})
    assert v is not None and v > 0


def test_fundamental_factors_in_registry():
    for k in ("growth", "quality", "valuation", "momentum_12m_ex1m",
              "moat", "industry_prosperity"):
        assert k in factors.FACTOR_REGISTRY


def test_growth_uses_fundamentals():
    fund = {"revenue_yoy": 0.20, "profit_yoy": 0.25}
    v = factors.FACTOR_REGISTRY["growth"](_uptrend_hist(130), fund, {})
    assert v is not None and v > 0


def test_valuation_invert_low_pe_better():
    """valuation 因子原始值越低越好(engine invert),本身返回 pe_pct_3y。"""
    v_low = factors.FACTOR_REGISTRY["valuation"](_uptrend_hist(130), {}, {"pe_pct_3y": 10.0, "pb_pct_3y": 10.0})
    v_high = factors.FACTOR_REGISTRY["valuation"](_uptrend_hist(130), {}, {"pe_pct_3y": 90.0, "pb_pct_3y": 90.0})
    assert v_low is not None and v_high is not None and v_low < v_high


def test_quality_combines_roe_margin_fcf():
    fund = {"roe": 0.20, "gross_margin": 0.40, "fcf_positive": True}
    v = factors.FACTOR_REGISTRY["quality"](_uptrend_hist(130), fund, {})
    assert v is not None and v > 0
