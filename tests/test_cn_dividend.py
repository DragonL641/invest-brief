from unittest.mock import MagicMock

import pytest

from investbrief.market.cn.provider import CNMarketProvider


def test_render_dividend_valuation_card():
    p = CNMarketProvider.__new__(CNMarketProvider)
    data = {"dividend_valuation": {"yield": 4.94, "cn_10y": 1.74, "spread": 3.20, "signal": "低估"}}
    html = p._render_dividend_valuation(data.get("dividend_valuation"))
    assert "红利低波100" in html
    assert "4.94" in html
    assert "3.20" in html  # spread
    assert "低估" in html


def test_render_dividend_valuation_empty():
    p = CNMarketProvider.__new__(CNMarketProvider)
    assert p._render_dividend_valuation(None) == ""
    assert p._render_dividend_valuation({}) == ""


def _provider(dy=4.94, cn_10y=1.74):
    """构造 mock self.data 的 provider，用于测 get_dividend_valuation。"""
    p = CNMarketProvider.__new__(CNMarketProvider)
    p.data = MagicMock()
    p.data.latest_macro.side_effect = lambda ind, c: {
        ("DIVIDEND_YIELD_930955", "cn"): dy,
        ("10Y_TREASURY", "cn"): cn_10y,
    }.get((ind, c))
    return p


@pytest.mark.parametrize("dy,expected", [
    (5.0, "低估"),    # ≥5 边界
    (4.99, "中性"),   # 4≤dy<5
    (4.0, "中性"),    # 4≤dy<5 边界（4.0 不 <4）
    (3.99, "偏高"),   # <4
    (6.0, "低估"),
])
def test_get_dividend_valuation_signal_thresholds(dy, expected):
    dv = _provider(dy=dy).get_dividend_valuation()
    assert dv["signal"] == expected
    assert dv["yield"] == round(dy, 2)


def test_get_dividend_valuation_dy_missing_returns_empty():
    assert _provider(dy=None).get_dividend_valuation() == {}


def test_get_dividend_valuation_cn10y_missing_spread_none():
    dv = _provider(dy=4.94, cn_10y=None).get_dividend_valuation()
    assert dv["yield"] == 4.94
    assert dv["spread"] is None
    assert dv["cn_10y"] is None


def test_render_dividend_valuation_spread_none_shows_dash():
    p = CNMarketProvider.__new__(CNMarketProvider)
    html = p._render_dividend_valuation({"yield": 4.94, "cn_10y": None, "spread": None, "signal": "中性"})
    assert "4.94" in html
    assert "−CN10Y利差" in html  # U+2212 minus（与 provider.py 一致）
    assert "<span class=\"label\">−CN10Y利差:</span> -" in html  # spread None → spread_str "-"


def test_render_monetary_policy_cn10y_pct_sub():
    p = CNMarketProvider.__new__(CNMarketProvider)
    mp = {"cn_10y_yield": 1.74, "cn_10y_pct": 35.0}
    html = p._render_monetary_policy(mp, {})
    assert "中国10Y国债" in html
    assert "近10年" in html
    assert "35%分位" in html


def test_render_monetary_policy_cn10y_no_pct_omits_sub():
    p = CNMarketProvider.__new__(CNMarketProvider)
    mp = {"cn_10y_yield": 1.74}  # 无 cn_10y_pct
    html = p._render_monetary_policy(mp, {})
    assert "中国10Y国债" in html
    assert "近10年" not in html


def test_render_section_includes_dividend_card_when_data_present():
    # 模拟 pipeline 组装：market_macro["cn"] 含 dividend_valuation → render_section 渲染卡片
    p = CNMarketProvider.__new__(CNMarketProvider)
    p.country_name = "A股市场"
    data = {
        "monetary_policy": {},
        "asset_performance": [],
        "economic_calendar": [],
        "dividend_valuation": {"yield": 4.94, "cn_10y": 1.74, "spread": 3.20, "signal": "低估"},
    }
    html = p.render_section(data, {"color_up": "#e74c3c", "color_down": "#27ae60"})
    assert "红利低波100" in html  # dividend card 渲染
