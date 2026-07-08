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


def test_quality_consumes_debt_ratio_low_leverage_bonus():
    """C2: debt_ratio 接入 quality 因子。低杠杆(0.1)应比高杠杆(0.8)得分高。"""
    base = {"roe": 0.20, "gross_margin": 0.40, "fcf_positive": True}
    v_low_debt = factors.FACTOR_REGISTRY["quality"](
        _uptrend_hist(130), {**base, "debt_ratio": 0.1}, {})
    v_high_debt = factors.FACTOR_REGISTRY["quality"](
        _uptrend_hist(130), {**base, "debt_ratio": 0.8}, {})
    assert v_low_debt is not None and v_high_debt is not None
    assert v_low_debt > v_high_debt
    # 差值应约等于 (1-0.1 - (1-0.8)) * 30 = 0.7 * 30 = 21
    assert abs((v_low_debt - v_high_debt) - 21.0) < 0.01


def test_quality_missing_debt_ratio_uses_neutral():
    """C2: debt_ratio 缺失走 0.5 中性,介于低杠杆(0.1)与高杠杆(0.8)之间。"""
    base = {"roe": 0.20, "gross_margin": 0.40, "fcf_positive": True}
    v_missing = factors.FACTOR_REGISTRY["quality"](
        _uptrend_hist(130), base, {})
    v_low = factors.FACTOR_REGISTRY["quality"](
        _uptrend_hist(130), {**base, "debt_ratio": 0.1}, {})
    v_high = factors.FACTOR_REGISTRY["quality"](
        _uptrend_hist(130), {**base, "debt_ratio": 0.8}, {})
    assert v_high < v_missing < v_low


def test_main_flow_factor_reads_from_fund():
    """C3: main_flow 因子从 fund['main_flow_5d'] 读取(由 pipeline 注入)。"""
    fund = {"main_flow_5d": 5.5}
    v = factors.FACTOR_REGISTRY["main_flow"](_uptrend_hist(130), fund, {})
    assert v == 5.5


def test_main_flow_factor_none_when_missing():
    fund = {}
    assert factors.FACTOR_REGISTRY["main_flow"](_uptrend_hist(130), fund, {}) is None


def test_main_flow_in_registry_and_labels():
    assert "main_flow" in factors.FACTOR_REGISTRY
    assert factors.FACTOR_LABELS["main_flow"] == "主力资金"
    # flow 类别:不参与行业中性化
    assert factors.FACTOR_CATEGORY["main_flow"] == "flow"
