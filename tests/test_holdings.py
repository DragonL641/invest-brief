"""持仓分析管道测试：config 校验 + analyzer 分发（mock client）+ brief fallback + renderer。

无网络：analyzer 的 client 全部用 MagicMock + lambda 替换。
"""
from unittest.mock import MagicMock

import pandas as pd
import pytest

from investbrief.core.config import validate_config
from investbrief.holdings.analyzer import HoldingsAnalyzer, HoldingResult, _ratio
from investbrief.holdings.brief import _fallback, generate_holdings_brief
from investbrief.holdings.renderer import render_holdings_section
from investbrief.holdings.etf.analyzer import ETFAnalysisResult

BASE_CFG = {
    "email_service": {"smtp_server": "s", "smtp_port": 465, "sender_email": "a@b.c"},
    "recipients": [{"email": "a@b.c"}],
}


def _mock_analyzer() -> HoldingsAnalyzer:
    """构造不触发 __init__（避免建真实 client）的 analyzer，方法逐个 mock。"""
    an = HoldingsAnalyzer.__new__(HoldingsAnalyzer)
    an._yf = MagicMock()
    an._fh = MagicMock()
    an._ak = MagicMock()
    an._etf = MagicMock()
    an._cache = {}
    return an


# ==================== 配置校验 ====================

def test_config_no_holdings_ok():
    validate_config(dict(BASE_CFG))


def test_config_valid_holdings():
    validate_config({**BASE_CFG, "recipients": [{"email": "a@b.c", "holdings": [
        {"symbol": "AAPL", "market": "us", "type": "stock"},
        {"symbol": "510300", "market": "cn", "type": "etf"},
        {"symbol": "000001", "market": "cn", "type": "fund"},
    ]}]})


def test_config_rejects_us_etf():
    with pytest.raises(ValueError, match="US market only supports type=stock"):
        validate_config({**BASE_CFG, "recipients": [{"email": "a@b.c", "holdings": [
            {"symbol": "SPY", "market": "us", "type": "etf"}]}]})


def test_config_rejects_us_fund():
    # us+fund 先被 us-stock-only 规则拦截（fund-non-cn 规则在后，作防御深度）
    with pytest.raises(ValueError, match="US market only supports type=stock"):
        validate_config({**BASE_CFG, "recipients": [{"email": "a@b.c", "holdings": [
            {"symbol": "X", "market": "us", "type": "fund"}]}]})


def test_config_rejects_bad_market():
    with pytest.raises(ValueError, match="holding market"):
        validate_config({**BASE_CFG, "recipients": [{"email": "a@b.c", "holdings": [
            {"symbol": "X", "market": "de", "type": "stock"}]}]})


def test_config_rejects_missing_field():
    with pytest.raises(ValueError, match="missing 'type'"):
        validate_config({**BASE_CFG, "recipients": [{"email": "a@b.c", "holdings": [
            {"symbol": "X", "market": "cn"}]}]})


# ==================== analyzer 分发 ====================

def test_analyze_us_stock_mock():
    an = _mock_analyzer()
    an._yf.get_quote = lambda s: {"price": 150, "change_percent": 1.2, "previous_close": 148}
    an._yf.get_info = lambda s: {"longName": "Apple", "trailingPE": 28.5, "returnOnEquity": 0.15}
    an._fh.get_recommendation = lambda s: {
        "latest": {"strong_buy": 0, "buy": 5, "hold": 3, "sell": 1, "strong_sell": 0, "period": "2026-07-01"},
        "previous": {"buy": 3, "hold": 5, "sell": 1},
        "change": {"buy": 22.2, "hold": -22.2, "sell": 0.0},
    }
    an._fh.get_price_target = lambda s: {"target_mean": 165, "target_high": 180, "target_low": 140, "number_of_analysts": 9}
    an._yf.get_upgrades_downgrades = lambda s: [{"firm": "GS", "from_grade": "Hold", "to_grade": "Buy", "action": "up", "date": "2026-07-01"}]
    r = an.analyze_one("AAPL", "us", "stock")
    assert r.error == "" and r.name == "Apple"
    assert r.price["current"] == 150 and r.rating["total"] == 9
    assert r.rating["trend"]["buy"] == 22.2  # 多期变化
    assert r.rating["price_target"]["upside_pct"] == 10.0
    assert r.fundamentals["roe"] == 15.0  # _ratio: 0.15 → 15.0
    assert r.rating["actions"][0]["firm"] == "GS"


def test_analyze_cn_stock_mock():
    an = _mock_analyzer()
    an._ak.get_stock_quote = lambda s: {"name": "贵州茅台", "price": 1680, "change_pct": -0.5, "pe": 30.0}
    an._ak.get_analyst_rating_summary = lambda s: {"buy": 8, "outperform": 2, "total_reports": 10, "total_reports_all": 25, "institutions": 6, "change": {"buy": 5.0}, "days": 90}
    an._ak.get_research_reports = lambda s, limit=5: [{"institution": "中信", "rating": "买入", "date": "2026-07-01"}]
    an._ak.get_financial_indicators = lambda s: {"roe": 30.0, "gross_margin": 90.0}
    an._ak.get_stock_fund_flow = lambda s: {"main_net": 50000000, "main_pct": 2.5}
    r = an.analyze_one("600519", "cn", "stock")
    assert r.name == "贵州茅台" and r.rating["price_target"] == {}
    assert r.rating["distribution"]["buy"] == 8 and r.rating["total"] == 10
    assert r.rating["total_all"] == 25 and r.rating["trend"]["buy"] == 5.0
    assert r.flow["main_net"] == 50000000
    assert r.rating["actions"][0]["institution"] == "中信"


def test_analyze_cn_etf_mock():
    an = _mock_analyzer()
    an._etf.analyze = lambda s: ETFAnalysisResult(
        symbol="510300", name="沪深300ETF", price=4.5, change_pct=0.8,
        iopv=4.49, premium_rate=0.1, main_net_flow=1000000,
        rule_results=[{"dimension": "估值", "name": "PE", "signal": "bullish"}],
        ai_conclusion="估值低位",
    )
    r = an.analyze_one("510300", "cn", "etf")
    assert r.name == "沪深300ETF" and r.price["current"] == 4.5
    assert r.flow["main_net_flow"] == 1000000 and r.ai_conclusion == "估值低位"
    assert r.signals[0]["dimension"] == "估值"


def test_analyze_cn_fund_mock():
    an = _mock_analyzer()
    an._ak.get_open_fund_nav = lambda s: {
        "nav": 1.2345, "acc_nav": 3.4567, "date": "2026-07-03",
        "daily_change": 0.15, "return_1w": 0.8, "return_1m": 2.3, "return_3m": 5.1,
    }
    r = an.analyze_one("000001", "cn", "fund")
    assert r.error == "" and r.price["current"] == 1.2345
    assert r.price["acc_nav"] == 3.4567
    assert r.fundamentals["return_1m"] == 2.3


def test_analyze_fund_failure_degrades():
    an = _mock_analyzer()
    an._ak.get_open_fund_nav = lambda s: None
    r = an.analyze_one("000001", "cn", "fund")
    assert r.error  # 净值拿不到 → 明确失败


def test_analyze_unsupported_combo():
    an = _mock_analyzer()
    r = an.analyze_one("X", "jp", "stock")
    assert r.error.startswith("unsupported")


def test_analyze_resilience_on_exception():
    """单个 client 抛异常 → 该维度留空，不阻塞整体。"""
    an = _mock_analyzer()
    an._yf.get_quote = MagicMock(side_effect=RuntimeError("network"))
    an._yf.get_info = lambda s: {"longName": "Apple"}
    an._fh.get_recommendation = lambda s: {"latest": {"buy": 5}, "change": {}}
    an._fh.get_price_target = lambda s: None
    an._yf.get_upgrades_downgrades = lambda s: None
    r = an.analyze_one("AAPL", "us", "stock")
    assert r.error == ""  # quote 失败但其它维度可用，整体未失败
    assert r.price.get("current") is None  # 价格维度降级
    assert r.rating["distribution"]["buy"] == 5  # 评级维度正常


def test_analyze_dedup_cache():
    """同一 (symbol,market,type) 多收件人只分析一次。"""
    an = _mock_analyzer()
    calls = []
    def fake(symbol, market, type_):
        calls.append((symbol, market, type_))
        return HoldingResult(symbol=symbol, market=market, type=type_)
    an.analyze_one = fake
    out = an.analyze([
        {"symbol": "A", "market": "us", "type": "stock"},
        {"symbol": "A", "market": "us", "type": "stock"},
        {"symbol": "B", "market": "us", "type": "stock"},
    ])
    assert len(calls) == 2 and len(out) == 3


# ==================== brief ====================

def test_brief_all_failed_returns_placeholder():
    out = generate_holdings_brief([HoldingResult(symbol="X", market="us", type="stock", error="boom")])
    assert "无可用" in out


def test_brief_fallback_summary():
    out = _fallback([HoldingResult(symbol="AAPL", market="us", type="stock", name="Apple",
                                   price={"current": 150, "change_pct": 1.2},
                                   rating={"price_target": {"upside_pct": 10.0}})])
    assert "AAPL" in out and "150" in out and "目标空间" in out


# ==================== renderer ====================

def test_renderer_4_types():
    rs = [
        HoldingResult(symbol="AAPL", market="us", type="stock", name="Apple",
                      price={"current": 150, "change_pct": 1.2},
                      rating={"distribution": {"buy": 5}, "total": 5,
                              "price_target": {"mean": 165, "upside_pct": 10.0},
                              "actions": [{"firm": "GS", "to_grade": "Buy", "date": "2026-07-01"}]}),
        HoldingResult(symbol="510300", market="cn", type="etf", name="沪深300ETF",
                      price={"current": 4.5, "change_pct": 0.8, "iopv": 4.49},
                      flow={"main_net_flow": 1000000}, ai_conclusion="估值低位"),
        HoldingResult(symbol="000001", market="cn", type="fund", name="华夏成长", error="P2"),
    ]
    html = render_holdings_section(rs)
    assert "AAPL" in html and "Apple" in html and "GS" in html
    assert "510300" in html and "IOPV" in html and "估值低位" in html
    assert "000001" in html and "P2" in html


def test_renderer_empty():
    assert "暂无持仓数据" in render_holdings_section([])


# ==================== 工具 ====================

def test_extract_technicals():
    from investbrief.holdings.analyzer import _extract_technicals
    idx = pd.date_range("2026-04-01", periods=70, freq="D")
    close = [100 + i * 0.5 for i in range(70)]  # 单边上涨 → 多头排列
    df = pd.DataFrame({"close": close, "volume": [1000] * 70}, index=idx)
    t = _extract_technicals(df)
    assert t["ma_alignment"] == "bullish"
    assert t["rsi"] is None or 0 < t["rsi"] <= 100  # 单边行情 loss=0 时 RSI 可能 None
    assert t["return_60d"] > 0
    # uppercase columns (yfinance style) 自动 rename
    df2 = df.rename(columns={"close": "Close", "volume": "Volume"})
    assert _extract_technicals(df2, uppercase_cols=True)["ma_alignment"] == "bullish"
    assert _extract_technicals(None) == {}


def test_extract_news():
    from investbrief.holdings.analyzer import _extract_news
    out = _extract_news([
        {"title": "新闻1", "date": "2026-07-03T10:00:00", "source": "src"},
        {"headline": "新闻2", "date": "2026-07-02"},
    ])
    assert len(out) == 2
    assert out[0]["title"] == "新闻1" and out[0]["date"] == "2026-07-03"
    assert out[1]["title"] == "新闻2"
    # finnhub datetime（Unix 时间戳）
    out2 = _extract_news([{"headline": "快讯", "datetime": 1751500000, "source": "Yahoo"}])
    assert out2[0]["title"] == "快讯" and len(out2[0]["date"]) == 10
    assert _extract_news(None) == []


def test_ratio_conversion():
    assert _ratio(0.15) == 15.0      # 小数比率
    assert _ratio(1.45) == 145.0     # ROE 可 >100%
    assert _ratio(None) is None
