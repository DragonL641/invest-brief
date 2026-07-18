"""持仓分析管道测试：config 校验 + analyzer 分发（mock client）+ brief fallback + renderer。

无网络：analyzer 的 client 全部用 MagicMock + lambda 替换。
"""
from unittest.mock import MagicMock

import pandas as pd
import pytest

from investbrief.core.config import validate_config
from investbrief.holdings.analyzer import HoldingsAnalyzer, HoldingResult
from investbrief.holdings.brief import _fallback, generate_holdings_brief
from investbrief.holdings.renderer import render_holdings_section
from investbrief.holdings.etf.analyzer import ETFAnalysisResult

BASE_CFG = {
    "email_service": {"smtp_server": "s", "smtp_port": 465, "sender_email": "a@b.c", "sender_name": "测试"},
    "recipients": [{"email": "a@b.c"}],
}


def _mock_analyzer() -> HoldingsAnalyzer:
    """构造不触发 __init__（避免建真实 client）的 analyzer，方法逐个 mock。"""
    an = HoldingsAnalyzer.__new__(HoldingsAnalyzer)
    an._ak = MagicMock()
    an._etf = MagicMock()
    an._cache = {}
    # __init__ 被跳过, 手动补 __init__ 里初始化的属性(避免 task 触发 AttributeError)
    an._dragon_tiger_cache = {}
    an._research_batch = None
    # name task(_ak._lookup_name) 返回 None → r.name fallback 到 quote.get("name")
    an._ak._lookup_name = lambda s: None
    return an


# ==================== 配置校验 ====================

def test_config_no_holdings_ok():
    validate_config(dict(BASE_CFG))


def test_config_valid_holdings():
    validate_config({**BASE_CFG, "recipients": [{"email": "a@b.c", "holdings": [
        {"symbol": "600519", "market": "cn", "type": "stock"},
        {"symbol": "510300", "market": "cn", "type": "etf"},
        {"symbol": "000001", "market": "cn", "type": "fund"},
    ]}]})


def test_config_rejects_us_market():
    # US market 已整体移除：holdings 仅支持 cn
    with pytest.raises(ValueError, match="holding market"):
        validate_config({**BASE_CFG, "recipients": [{"email": "a@b.c", "holdings": [
            {"symbol": "AAPL", "market": "us", "type": "stock"}]}]})


def test_config_rejects_bad_market():
    with pytest.raises(ValueError, match="holding market"):
        validate_config({**BASE_CFG, "recipients": [{"email": "a@b.c", "holdings": [
            {"symbol": "X", "market": "de", "type": "stock"}]}]})


def test_config_rejects_missing_field():
    with pytest.raises(ValueError, match="missing 'type'"):
        validate_config({**BASE_CFG, "recipients": [{"email": "a@b.c", "holdings": [
            {"symbol": "X", "market": "cn"}]}]})


# ==================== analyzer 分发 ====================

def test_analyze_cn_stock_mock(monkeypatch):
    an = _mock_analyzer()
    an._ak._lookup_name = lambda s: "贵州茅台"  # name 独立调(quote 已弃)
    # quote 弃 → price 从 history today bar(收盘) 提取
    hist = pd.DataFrame(
        {"open": [1670], "close": [1680], "high": [1690], "low": [1660],
         "volume": [100000], "amount": [16800000], "change_pct": [-0.5]},
        index=pd.to_datetime(["2026-07-13"]))
    monkeypatch.setattr("investbrief.holdings.analyzer.history_db_first", lambda *a, **kw: hist)
    an._ak.get_analyst_rating_summary = lambda s, df=None: {"buy": 8, "outperform": 2, "total_reports": 10, "total_reports_all": 25, "institutions": 6, "change": {"buy": 5.0}, "days": 90}
    an._ak.get_research_reports = lambda s, limit=5, df=None: [{"institution": "中信", "rating": "买入", "date": "2026-07-01"}]
    an._ak.get_financial_indicators = lambda s: {"roe": 30.0, "gross_margin": 90.0}
    an._ak.get_stock_fund_flow = lambda s: {"main_net": 50000000, "main_pct": 2.5}
    r = an.analyze_one("600519", "cn", "stock")
    assert r.name == "贵州茅台"              # 来自 _lookup_name
    assert r.price["current"] == 1680        # 来自 history today bar close
    assert r.price["change_pct"] == -0.5
    assert r.rating["price_target"] == {}
    assert r.rating["distribution"]["buy"] == 8 and r.rating["total"] == 10
    assert r.rating["total_all"] == 25 and r.rating["trend"]["buy"] == 5.0
    assert r.flow["main_net"] == 50000000
    assert r.rating["actions"][0]["institution"] == "中信"


def test_analyze_cn_etf_mock():
    an = _mock_analyzer()
    an._etf.analyze = lambda s, with_ai=True, **kw: ETFAnalysisResult(
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
    # quote 抛异常 → price 维度降级，但 rating/fundamentals 走缓存独立可用
    an._ak.get_stock_quote = MagicMock(side_effect=RuntimeError("network"))
    an._ak.get_analyst_rating_summary = lambda s, df=None: {"buy": 5, "total_reports": 5}
    an._ak.get_research_reports = lambda s, limit=5, df=None: []
    an._ak.get_financial_indicators = lambda s: {"roe": 30.0}
    r = an.analyze_one("600519", "cn", "stock")
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
        {"symbol": "600519", "market": "cn", "type": "stock"},
        {"symbol": "600519", "market": "cn", "type": "stock"},
        {"symbol": "000001", "market": "cn", "type": "stock"},
    ])
    assert len(calls) == 2 and len(out) == 3


# ==================== brief ====================

def test_brief_all_failed_returns_placeholder():
    out = generate_holdings_brief([HoldingResult(symbol="X", market="cn", type="stock", error="boom")])
    assert "无可用" in out


def test_brief_fallback_summary():
    out = _fallback([HoldingResult(symbol="600519", market="cn", type="stock", name="贵州茅台",
                                   price={"current": 1680, "change_pct": 1.2},
                                   rating={"price_target": {"upside_pct": 10.0}})])
    assert "600519" in out and "1680" in out and "目标空间" in out


# ==================== renderer ====================

def test_renderer_3_types():
    rs = [
        HoldingResult(symbol="600519", market="cn", type="stock", name="贵州茅台",
                      price={"current": 1680, "change_pct": 1.2},
                      rating={"distribution": {"buy": 5}, "total": 5,
                              "price_target": {"mean": 1850, "upside_pct": 10.0},
                              "actions": [{"institution": "中信", "rating": "买入", "date": "2026-07-01"}]}),
        HoldingResult(symbol="510300", market="cn", type="etf", name="沪深300ETF",
                      price={"current": 4.5, "change_pct": 0.8, "iopv": 4.49},
                      flow={"main_net_flow": 1000000}, ai_conclusion="估值低位"),
        HoldingResult(symbol="000001", market="cn", type="fund", name="华夏成长", error="P2"),
    ]
    html = render_holdings_section(rs)
    # 三层层级：个股 / 场内基金 / 场外基金
    assert "个股" in html and "场内基金" in html and "场外基金" in html
    assert "600519" in html and "贵州茅台" in html
    assert "买入共识" in html  # rating distribution 走机构态度维度行
    assert "510300" in html and "沪深300ETF" in html and "估值低位" in html
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
    # Unix 时间戳（兼容性）
    out2 = _extract_news([{"headline": "快讯", "datetime": 1751500000, "source": "Yahoo"}])
    assert out2[0]["title"] == "快讯" and len(out2[0]["date"]) == 10
    assert _extract_news(None) == []


def test_with_ai_fills_conclusion():
    from unittest.mock import patch
    analyzer = HoldingsAnalyzer()
    r = HoldingResult(symbol="601138", market="cn", type="stock", name="工业富联",
                      price={"current": 64.72})
    with patch("investbrief.holdings.brief.generate_stock_conclusion", return_value="偏多。") as mock_gen:
        result = analyzer._with_ai(r)
    assert result.ai_conclusion == "偏多。"
    mock_gen.assert_called_once_with(r)


# ==================== 机构调研 run 级批量预取 ====================

def test_run_holdings_report_prefetches_research_batch(monkeypatch):
    """run_holdings_report 批量路径：多 recipients/多 CN stock →
    get_institutional_research_batch 调 1 次，每股不单独调 get_institutional_research。"""
    from investbrief.pipelines import holdings as h_mod

    recipients = [
        {"email": "a@b.com", "name": "A", "active": True, "language": "zh-CN",
         "holdings": [{"symbol": "600519", "market": "cn", "type": "stock"},
                      {"symbol": "510300", "market": "cn", "type": "etf"}]},
        {"email": "c@d.com", "name": "C", "active": True, "language": "zh-CN",
         "holdings": [{"symbol": "002371", "market": "cn", "type": "stock"},
                      {"symbol": "600519", "market": "cn", "type": "stock"}]},  # 600519 跨人去重
    ]
    monkeypatch.setattr(h_mod, "load_config", lambda: {"recipients": recipients})
    monkeypatch.setattr("investbrief.holdings.analyzer.init_cache", lambda *a, **k: None)

    batch_counter = {"n": 0}
    single_counter = {"n": 0}

    def fake_batch(self, symbols, days=7):
        batch_counter["n"] += 1
        return {s: [{"institution": "X", "date": "2026-06-01"}] for s in symbols}

    def fake_single(self, symbol, days=7):
        single_counter["n"] += 1
        return []

    monkeypatch.setattr(
        "investbrief.datasources.akshare.AKShareClient.get_institutional_research_batch", fake_batch)
    monkeypatch.setattr(
        "investbrief.datasources.akshare.AKShareClient.get_institutional_research", fake_single)

    fake_analyzer = MagicMock()
    fake_analyzer.analyze_one = lambda *a, **k: HoldingResult(
        symbol=a[0], market=a[1], type=a[2])
    monkeypatch.setattr("investbrief.holdings.analyzer.HoldingsAnalyzer", lambda: fake_analyzer)

    monkeypatch.setattr(h_mod, "now_cn", lambda: __import__("datetime").datetime.now())
    monkeypatch.setattr("investbrief.holdings.brief.generate_holdings_brief",
                        lambda sub: "<p>brief</p>")
    monkeypatch.setattr("investbrief.holdings.renderer.render_holdings_section",
                        lambda sub: "<div>sections</div>")
    monkeypatch.setattr("investbrief.mail.render.render_holdings_template",
                        lambda *a, **k: "<html></html>")
    monkeypatch.setattr("investbrief.mail.sender.EmailSender",
                        lambda cfg: MagicMock(send_bulk=lambda m: (2, [])))

    args = MagicMock(force=False, skip_summary=True, dry_run=False)
    h_mod.run_holdings_report(args)

    # batch 只调 1 次（2 只唯一 CN stock 共享），每股不单独调
    assert batch_counter["n"] == 1, (
        f"batch 应只调 1 次，实际 {batch_counter['n']}")
    assert single_counter["n"] == 0, (
        f"批量注入后不应再调单股接口，实际 {single_counter['n']} 次")
    # batch 结果通过 set_research_batch 注入 analyzer
    fake_analyzer.set_research_batch.assert_called_once()
    injected = fake_analyzer.set_research_batch.call_args[0][0]
    assert set(injected.keys()) == {"600519", "002371"}


def test_history_db_first_empty_db_uses_full_history():
    """DB 空时 _history_db_first 用 live_fetch_full(全历史), 不用 live_fetch(近期增量)。"""
    from investbrief.data.db_first import history_db_first as _history_db_first
    db = MagicMock()
    db.has_today_bar.return_value = False
    db.query_stock_daily.return_value = pd.DataFrame()  # DB 空
    db.upsert_stock_df = MagicMock()
    full_called = {"n": 0}
    recent_called = {"n": 0}
    sample = pd.DataFrame({"open": [1], "close": [2]},
                          index=pd.to_datetime(["2026-07-13"]))

    def live_fetch(sym, days):
        recent_called["n"] += 1
        return sample

    def live_fetch_full(sym):
        full_called["n"] += 1
        return sample

    _history_db_first("cn", "601138", days=180, db=db,
                      live_fetch=live_fetch, live_fetch_full=live_fetch_full)
    assert full_called["n"] == 1   # DB 空 → 全历史
    assert recent_called["n"] == 0  # 不调近期


def test_history_db_first_has_data_uses_recent_increment():
    """DB 有历史(没今天 bar)时 _history_db_first 用 live_fetch(近期增量), 不重拉全历史。"""
    from investbrief.data.db_first import history_db_first as _history_db_first
    db = MagicMock()
    db.has_today_bar.return_value = False  # 没今天 bar → 需增量
    # DB 有充足历史(600 行 >= 500 阈值) → 走近期增量而非全历史
    db.query_stock_daily.return_value = pd.DataFrame(
        {"market": ["cn"] * 600, "symbol": ["601138"] * 600,
         "date": ["2026-07-12"] * 600, "close": [10] * 600})
    db.upsert_stock_df = MagicMock()
    full_called = {"n": 0}
    recent_called = {"n": 0}
    sample = pd.DataFrame({"open": [1], "close": [2]},
                          index=pd.to_datetime(["2026-07-13"]))

    _history_db_first("cn", "601138", days=180, db=db,
                      live_fetch=lambda s, d: (recent_called.__setitem__("n", recent_called["n"] + 1), sample)[1],
                      live_fetch_full=lambda s: (full_called.__setitem__("n", full_called["n"] + 1), sample)[1])
    assert recent_called["n"] == 1  # DB 有 → 近期增量
    assert full_called["n"] == 0    # 不调全历史
