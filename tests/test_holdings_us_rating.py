"""US 评级：yfinance 优先，finnhub 403 静默降级。

Finnhub free tier 对 stock/price-target 与 stock/recommendation 经常返回 403。
本测试验证：finnhub 全部失败时，US 评级仍能从 yfinance 数据构造，
HoldingResult.error 为空，流程不阻塞，也不抛异常。

数据形状参考（实际 yfinance client 契约）：
- get_recommendations → {strong_buy, buy, hold, sell, strong_sell, source}（flat，无 trend）
- get_price_targets   → {current, low, high, mean, median, source}
- get_upgrades_downgrades → [{firm, to_grade, from_grade, action, price_target, date}]
"""
from unittest.mock import patch

from investbrief.holdings.analyzer import HoldingsAnalyzer


def test_us_rating_works_when_finnhub_403():
    """finnhub 全部 403 → yfinance 兜底，rating 仍构造，无 error。"""
    a = HoldingsAnalyzer()
    # finnhub 抛 403（requests.HTTPError）→ client 内部已降级为 debug + return None
    with patch.object(a._fh, "get_recommendation", side_effect=Exception("403 Forbidden")), \
         patch.object(a._fh, "get_price_target", side_effect=Exception("403 Forbidden")), \
         patch.object(a._fh, "get_company_news", return_value=[]), \
         patch.object(a._yf, "get_quote", return_value={
             "price": 150, "change_percent": 1.2, "previous_close": 148,
         }), \
         patch.object(a._yf, "get_info", return_value={"longName": "Apple"}), \
         patch.object(a._yf, "get_history", return_value=None), \
         patch.object(a._yf, "get_recommendations", return_value={
             "strong_buy": 5, "buy": 10, "hold": 2, "sell": 1, "strong_sell": 0,
             "source": "yfinance",
         }), \
         patch.object(a._yf, "get_price_targets", return_value={
             "current": 150, "low": 140, "high": 200, "mean": 175, "median": 170,
             "source": "yfinance",
         }), \
         patch.object(a._yf, "get_upgrades_downgrades", return_value=[]), \
         patch.object(a._yf, "get_insider_transactions", return_value=[]), \
         patch.object(a._yf, "get_earnings_dates", return_value=[]), \
         patch.object(a._yf, "get_earnings_estimate", return_value={}):
        r = a._analyze_us_stock("AAPL")

    assert not r.error, f"expected no error, got: {r.error}"
    # rating distribution 从 yfinance 构造
    assert r.rating["distribution"].get("buy") == 10
    assert r.rating["distribution"].get("strong_buy") == 5
    assert r.rating["total"] == 18  # 5+10+2+1
    # yfinance 无 previous → trend 空 dict（不阻塞 renderer）
    assert r.rating["trend"] == {}
    # price_target 从 yfinance mean=175 构造，upside = (175-150)/150*100 = 16.7
    assert r.rating["price_target"]["mean"] == 175
    assert r.rating["price_target"]["upside_pct"] == 16.7
    # source 标注
    assert "yfinance" in r.rating["source"]


def test_us_rating_finnhub_preferred_when_available():
    """finnhub 成功（含 trend）→ 优先使用，trend 字段保留。"""
    a = HoldingsAnalyzer()
    with patch.object(a._fh, "get_recommendation", return_value={
        "latest": {"strong_buy": 0, "buy": 5, "hold": 3, "sell": 1, "strong_sell": 0,
                   "period": "2026-07-01"},
        "previous": {"buy": 3, "hold": 5, "sell": 1},
        "change": {"buy": 22.2, "hold": -22.2, "sell": 0.0},
        "periods": [],
    }), \
         patch.object(a._fh, "get_price_target", return_value={
             "target_mean": 165, "target_high": 180, "target_low": 140,
             "number_of_analysts": 9,
         }), \
         patch.object(a._fh, "get_company_news", return_value=[]), \
         patch.object(a._yf, "get_quote", return_value={
             "price": 150, "change_percent": 1.2, "previous_close": 148,
         }), \
         patch.object(a._yf, "get_info", return_value={"longName": "Apple"}), \
         patch.object(a._yf, "get_history", return_value=None), \
         patch.object(a._yf, "get_recommendations", return_value={
             "strong_buy": 99, "buy": 99, "hold": 0, "sell": 0, "strong_sell": 0,
         }), \
         patch.object(a._yf, "get_price_targets", return_value=None), \
         patch.object(a._yf, "get_upgrades_downgrades", return_value=[]), \
         patch.object(a._yf, "get_insider_transactions", return_value=[]), \
         patch.object(a._yf, "get_earnings_dates", return_value=[]), \
         patch.object(a._yf, "get_earnings_estimate", return_value={}):
        r = a._analyze_us_stock("AAPL")

    assert not r.error
    # finnhub 数据胜出（buy=5），yfinance 的 99 被忽略
    assert r.rating["distribution"].get("buy") == 5
    assert r.rating["trend"]["buy"] == 22.2  # finnhub 提供的 trend 保留


def test_us_rating_both_sources_empty():
    """finnhub + yfinance 都无数据 → rating 结构仍构造，distribution 为空。"""
    a = HoldingsAnalyzer()
    with patch.object(a._fh, "get_recommendation", return_value=None), \
         patch.object(a._fh, "get_price_target", return_value=None), \
         patch.object(a._fh, "get_company_news", return_value=[]), \
         patch.object(a._yf, "get_quote", return_value={"price": 100}), \
         patch.object(a._yf, "get_info", return_value={}), \
         patch.object(a._yf, "get_history", return_value=None), \
         patch.object(a._yf, "get_recommendations", return_value=None), \
         patch.object(a._yf, "get_price_targets", return_value=None), \
         patch.object(a._yf, "get_upgrades_downgrades", return_value=[]), \
         patch.object(a._yf, "get_insider_transactions", return_value=[]), \
         patch.object(a._yf, "get_earnings_dates", return_value=[]), \
         patch.object(a._yf, "get_earnings_estimate", return_value={}):
        r = a._analyze_us_stock("AAPL")

    assert not r.error
    assert r.rating["distribution"] == {}
    assert r.rating["total"] is None
    assert r.rating["price_target"] == {}
