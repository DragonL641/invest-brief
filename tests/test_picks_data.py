# tests/test_picks_data.py
"""picks.data: 归一化纯函数 normalize_fundamentals / normalize_valuation(不触网)。"""
from investbrief.picks import data


def test_normalize_fundamentals_maps_fields():
    raw = {"净资产收益率(加权)": "20.5", "销售毛利率": "40.1",
           "营业总收入同比增长率": "15.0", "净利润同比增长率": "18.0",
           "资产负债率": "35.0"}
    out = data.normalize_fundamentals(raw)
    assert out["roe"] == 0.205
    assert out["gross_margin"] == 0.401
    assert out["revenue_yoy"] == 0.15
    assert out["profit_yoy"] == 0.18
    assert out["debt_ratio"] == 0.35


def test_normalize_fundamentals_missing_keys_safe():
    out = data.normalize_fundamentals({})
    assert out.get("roe") is None
