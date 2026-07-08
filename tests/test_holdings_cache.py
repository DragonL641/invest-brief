"""#12 holdings 季频维度跨日缓存(rating/fundamentals/cn_activity, TTL=7d)。

验证: 缓存命中时第二次取同一 symbol 不再调底层 API(限流缓解)。
init_cache 注入 FactorCache; 测试结束 reset 模块单例避免污染其他测试。
"""
from unittest.mock import MagicMock

import pytest

from investbrief.holdings import analyzer as analyzer_mod
from investbrief.holdings.analyzer import HoldingsAnalyzer


def _mock_analyzer() -> HoldingsAnalyzer:
    """与 test_holdings.py 同款: __new__ 绕过 __init__, client 逐个 mock。"""
    an = HoldingsAnalyzer.__new__(HoldingsAnalyzer)
    an._yf = MagicMock()
    an._fh = MagicMock()
    an._ak = MagicMock()
    an._etf = MagicMock()
    an._cache = {}
    return an


@pytest.fixture
def fresh_cache(tmp_path):
    """init_cache 到 tmp 路径, 测试后 reset 模块单例。"""
    analyzer_mod.init_cache(str(tmp_path / "h.db"))
    yield analyzer_mod._factor_cache()
    analyzer_mod._fcache = None


# ==================== rating ====================

def test_rating_cn_cache_hit_skips_api(fresh_cache):
    """CN rating 第二次取同 symbol → API 只调一次(缓存命中)。"""
    an = _mock_analyzer()
    calls = {"summary": 0, "reports": 0}

    def _count_summary(symbol):
        calls["summary"] += 1
        return {"buy": 8, "outperform": 2, "total_reports": 10,
                "total_reports_all": 25, "institutions": 6,
                "change": {"buy": 5.0}, "days": 90}

    def _count_reports(symbol, limit=5):
        calls["reports"] += 1
        return [{"institution": "中信", "rating": "买入", "date": "2026-07-01"}]

    an._ak.get_analyst_rating_summary = _count_summary
    an._ak.get_research_reports = _count_reports

    r1 = an._collect_rating("600519", "cn")
    r2 = an._collect_rating("600519", "cn")

    assert calls["summary"] == 1, f"summary API 应只调 1 次, 实际 {calls['summary']}"
    assert calls["reports"] == 1
    assert r1["distribution"]["buy"] == 8 and r2["distribution"]["buy"] == 8
    assert r1["actions"][0]["institution"] == "中信"


def test_rating_us_cache_hit_skips_api(fresh_cache):
    """US rating 第二次取同 symbol → rating API 只调一次; upside 仍用 live current fresh build。"""
    an = _mock_analyzer()
    calls = {"rec": 0}

    def _count_rec(symbol):
        calls["rec"] += 1
        return {"latest": {"strong_buy": 0, "buy": 5, "hold": 3, "sell": 1, "strong_sell": 0,
                           "period": "2026-07-01"},
                "previous": None, "change": {"buy": 22.2}, "periods": []}

    an._fh.get_recommendation = _count_rec
    an._yf.get_recommendations = lambda s: None
    an._fh.get_price_target = lambda s: {"target_mean": 165, "target_high": 180,
                                          "target_low": 140, "number_of_analysts": 9}
    an._yf.get_price_targets = lambda s: None
    an._yf.get_upgrades_downgrades = lambda s: []

    r1 = an._collect_rating("AAPL", "us", current=150)
    r2 = an._collect_rating("AAPL", "us", current=165)   # price moved

    assert calls["rec"] == 1, f"recommendation API 应只调 1 次, 实际 {calls['rec']}"
    # raw rating 缓存复用 → distribution 一致
    assert r1["distribution"]["buy"] == 5 and r2["distribution"]["buy"] == 5
    # upside 用 live current fresh build → price 变化反映在 upside
    assert r1["price_target"]["upside_pct"] == 10.0   # (165-150)/150
    assert r2["price_target"]["upside_pct"] == 0.0    # (165-165)/165


# ==================== fundamentals ====================

def test_fundamentals_cn_cache_hit_skips_api(fresh_cache):
    """CN fundamentals(get_financial_indicators) 第二次取 → API 只调一次。"""
    an = _mock_analyzer()
    calls = {"n": 0}

    def _count(symbol):
        calls["n"] += 1
        return {"roe": 30.0, "gross_margin": 90.0, "eps": 42.0}

    an._ak.get_financial_indicators = _count

    f1 = an._collect_fundamentals("600519", "cn")
    f2 = an._collect_fundamentals("600519", "cn")

    assert calls["n"] == 1, f"financial_indicators API 应只调 1 次, 实际 {calls['n']}"
    assert f1 == f2
    assert f1["roe"] == 30.0


def test_fundamentals_us_cache_hit_skips_api(fresh_cache):
    """US fundamentals(get_info) 第二次取 → API 只调一次。"""
    an = _mock_analyzer()
    calls = {"n": 0}

    def _count(symbol):
        calls["n"] += 1
        return {"longName": "Apple", "trailingPE": 28.5, "returnOnEquity": 0.15}

    an._yf.get_info = _count

    i1 = an._collect_fundamentals("AAPL", "us")
    i2 = an._collect_fundamentals("AAPL", "us")

    assert calls["n"] == 1
    assert i1["trailingPE"] == 28.5 and i2["longName"] == "Apple"


# ==================== disabled when no init_cache ====================

def test_no_init_cache_disables_caching(monkeypatch):
    """未 init_cache(模块 _fcache=None, 如纯单测)→ _cached 透传直调, 无缓存副作用。"""
    monkeypatch.setattr(analyzer_mod, "_fcache", None)
    an = _mock_analyzer()
    calls = {"n": 0}

    def _count(symbol):
        calls["n"] += 1
        return {"roe": 30.0}

    an._ak.get_financial_indicators = _count
    an._collect_fundamentals("600519", "cn")
    an._collect_fundamentals("600519", "cn")
    assert calls["n"] == 2, "无缓存 → 每次都应直调 API"
