# tests/test_picks_cn_fund.py
"""picks.data._normalize_cn_fund: 回归 — get_financial_indicators 返回英文 key+百分数,
之前误用 normalize_fundamentals(找中文 key)→ CN 基本面全空,只剩 fcf_positive。"""
import pytest
from investbrief.picks.data import _normalize_cn_fund


def test_maps_english_keys_to_decimals():
    raw = {"roe": 10.35, "gross_margin": 36.33, "revenue_growth": 24.79,
           "profit_growth": 97.5, "debt_ratio": 51.37,
           "operating_cashflow_per_share": 1.05}
    out = _normalize_cn_fund(raw)
    assert out["roe"] == pytest.approx(0.1035)
    assert out["gross_margin"] == pytest.approx(0.3633)
    assert out["revenue_yoy"] == pytest.approx(0.2479)
    assert out["profit_yoy"] == pytest.approx(0.975)
    assert out["debt_ratio"] == pytest.approx(0.5137)
    assert out["fcf_positive"] is True


def test_negative_cashflow_is_fcf_negative():
    raw = {"operating_cashflow_per_share": -0.5}
    assert _normalize_cn_fund(raw)["fcf_positive"] is False


def test_missing_keys_safe():
    out = _normalize_cn_fund({})
    assert out["roe"] is None
    assert out["fcf_positive"] is None  # ocf absent → None (not mass-filtered)


def test_already_decimal_not_redivided():
    """roe 已是小数(<1.5)不再 /100。"""
    assert _normalize_cn_fund({"roe": 0.12})["roe"] == 0.12
