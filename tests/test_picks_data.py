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


def test_normalize_fundamentals_fcf_positive_from_cashflow():
    """TODO C: 每股经营现金流 > 0 → fcf_positive True;负值 → False;缺失 → 不设。"""
    out_pos = data.normalize_fundamentals({"每股经营现金流": "0.5"})
    assert out_pos.get("fcf_positive") is True

    out_neg = data.normalize_fundamentals({"每股经营现金流": "-0.27"})
    assert out_neg.get("fcf_positive") is False

    out_absent = data.normalize_fundamentals({"roe": "10"})
    assert "fcf_positive" not in out_absent

    # 空字符串/破折号视同缺失
    out_dash = data.normalize_fundamentals({"每股经营现金流": "-"})
    assert "fcf_positive" not in out_dash


def test_normalize_fundamentals_fcf_from_english_alias():
    """get_financial_indicators 已把 cashflow 转为 operating_cashflow_per_share
    (英文 key),normalize 应能识别。"""
    out = data.normalize_fundamentals({"operating_cashflow_per_share": 1.2})
    assert out.get("fcf_positive") is True


def test_count_profitable_years_basic():
    """TODO B 纯函数: > 0 的年数。None/NaN/0/负值不计入。"""
    assert data.count_profitable_years({}) == 0
    assert data.count_profitable_years({"2020": 1.0, "2021": 2.0, "2022": 0.5}) == 3
    assert data.count_profitable_years({"2020": 1.0, "2021": -0.5, "2022": 0.0}) == 1
    # None / NaN / 非数 都不计入
    assert data.count_profitable_years({"2020": None, "2021": float("nan")}) == 0
    assert data.count_profitable_years({"2020": "abc"}) == 0
    # 全负
    assert data.count_profitable_years({"2020": -1.0, "2021": -2.0}) == 0


def test_cn_amount_to_float_parses_suffixes():
    """TODO B 辅助: CN 金额简写(亿/万/纯数字/负值/破折号)。"""
    assert data._cn_amount_to_float("1.47亿") == 1.47e8
    assert data._cn_amount_to_float("5000万") == 5e7
    assert data._cn_amount_to_float("123.45") == 123.45
    assert data._cn_amount_to_float("-0.5亿") == -5e7
    # 缺失值
    import math
    assert math.isnan(data._cn_amount_to_float("-"))
    assert math.isnan(data._cn_amount_to_float(""))
    assert math.isnan(data._cn_amount_to_float(None))
