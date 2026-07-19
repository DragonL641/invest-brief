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
