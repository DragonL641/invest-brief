"""宏观 provider 单测：US/CN monetary_policy & asset_performance。

用 MagicMock 替换底层 client（yfinance / AKShare），保证测试无网络、确定性、快速。
验证两类行为：
1. 结构 — 返回正确 key / name。
2. 韧性 — 底层抛异常时不崩溃，返回降级空结构。
"""

from unittest.mock import MagicMock

from investbrief.cn.provider import CNMarketProvider
from investbrief.us.provider import USMarketProvider


# ---------------------------------------------------------------------------
# US provider — self.yf
# ---------------------------------------------------------------------------

def test_us_monetary_policy_structure():
    p = USMarketProvider()
    p.yf = MagicMock()
    p.yf.get_quote.side_effect = lambda s: (
        {"price": 4.3, "change_percent": 0.1} if s == "^TNX" else None
    )
    m = p.get_monetary_policy()
    assert m["us_10y_yield"] == 4.3
    assert "us_5y_yield" in m and m["us_5y_yield"] is None
    assert "fed_funds_rate" in m
    assert "cn_10y_yield" in m and "cn_us_spread" in m


def test_us_monetary_policy_resilient():
    p = USMarketProvider()
    p.yf = MagicMock()
    p.yf.get_quote.side_effect = RuntimeError("boom")
    m = p.get_monetary_policy()
    assert isinstance(m, dict)
    assert m["us_10y_yield"] is None


def test_us_asset_performance_has_gold():
    p = USMarketProvider()
    p.yf = MagicMock()
    p.yf.get_quote.side_effect = lambda s: (
        {"price": 4100.0, "change_percent": -0.5} if s == "GC=F" else None
    )
    assets = p.get_asset_performance()
    names = [a["name"] for a in assets]
    assert "黄金(COMEX)" in names


# ---------------------------------------------------------------------------
# CN provider — self.client
# ---------------------------------------------------------------------------

def test_cn_monetary_policy_delegates():
    p = CNMarketProvider()
    p.client = MagicMock()
    p.client.get_cn_monetary_policy.return_value = {"lpr_1y": 3.0, "m2_yoy": 8.6}
    assert p.get_monetary_policy() == {"lpr_1y": 3.0, "m2_yoy": 8.6}


def test_cn_monetary_policy_resilient():
    p = CNMarketProvider()
    p.client = MagicMock()
    p.client.get_cn_monetary_policy.side_effect = RuntimeError("boom")
    assert p.get_monetary_policy() == {}


def test_cn_asset_performance_has_fx():
    p = CNMarketProvider()
    p.client = MagicMock()
    p.client.get_index_quotes.return_value = []
    p.client.get_fx_rate_usdcny.return_value = {
        "pair": "USDCNY",
        "price": 6.78,
        "change_pct": 0.2,
    }
    assets = p.get_asset_performance()
    fx = [a for a in assets if a["name"] == "人民币汇率(USDCNY)"]
    assert fx and fx[0]["point"] == 6.78
