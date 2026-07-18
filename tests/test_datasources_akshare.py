"""akshare 数据层韧性测试：headers patch + retry + 负缓存 + bid_ask 解析。"""
import pandas as pd


def test_patched_session_request_adds_headers_for_eastmoney(monkeypatch):
    from investbrief.datasources import akshare as ak_mod
    captured = {}

    def fake_orig(self, method, url, **kwargs):
        captured.update(kwargs)
        captured["url"] = url
        return "resp"

    monkeypatch.setattr(ak_mod, "_orig_session_request", fake_orig)
    ak_mod._patched_session_request(object(), "GET", "https://push2.eastmoney.com/api/x")
    assert "headers" in captured
    assert "User-Agent" in captured["headers"]
    assert "Chrome" in captured["headers"]["User-Agent"]
    assert "eastmoney.com" in captured["headers"]["Referer"]


def test_patched_session_request_skips_non_eastmoney(monkeypatch):
    from investbrief.datasources import akshare as ak_mod
    captured = {}

    def fake_orig(self, method, url, **kwargs):
        captured.update(kwargs)
        return "resp"

    monkeypatch.setattr(ak_mod, "_orig_session_request", fake_orig)
    ak_mod._patched_session_request(object(), "GET", "https://api.github.com/x")
    assert "headers" not in captured or "User-Agent" not in (captured.get("headers") or {})


def test_with_retry_succeeds_after_retries(monkeypatch):
    from investbrief.datasources import akshare as ak_mod
    # _throttle 设 0 间隔，使本次只测 retry/backoff（throttle 行为由 test_akshare_throttle 覆盖）
    monkeypatch.setattr(ak_mod, "_MIN_INTERVAL", 0.0)
    from investbrief.datasources.akshare import _with_retry
    sleeps = []
    monkeypatch.setattr("investbrief.datasources.akshare.time.sleep", lambda s: sleeps.append(s))
    state = {"n": 0}

    def flaky():
        state["n"] += 1
        if state["n"] < 3:
            raise RuntimeError("x")
        return "ok"

    assert _with_retry(flaky, label="test") == "ok"
    assert state["n"] == 3
    assert len(sleeps) == 2


def test_with_retry_all_fail_returns_none(monkeypatch):
    from investbrief.datasources import akshare as ak_mod
    monkeypatch.setattr(ak_mod, "_MIN_INTERVAL", 0.0)
    from investbrief.datasources.akshare import _with_retry
    sleeps = []
    monkeypatch.setattr("investbrief.datasources.akshare.time.sleep", lambda s: sleeps.append(s))

    def always_fail():
        raise RuntimeError("x")

    assert _with_retry(always_fail, label="test", attempts=3) is None
    assert len(sleeps) == 2
    assert sleeps[-1] >= 10.0  # 最后一次重试前长退避 ≥10s


def test_dataframe_cache_negative(monkeypatch):
    from investbrief.datasources.akshare import _DataFrameCache
    c = _DataFrameCache()
    assert not c.is_recently_failed("zh_a_spot")
    c.mark_failed("zh_a_spot", 60)
    assert c.is_recently_failed("zh_a_spot")


def test_dataframe_cache_negative_expiry(monkeypatch):
    from investbrief.datasources.akshare import _DataFrameCache
    import investbrief.datasources.akshare as ak_mod
    t = [100.0]
    monkeypatch.setattr(ak_mod.time, "monotonic", lambda: t[0])
    c = _DataFrameCache()
    c.mark_failed("k", 60)
    t[0] = 100.0  # mark 瞬间
    assert c.is_recently_failed("k")
    t[0] = 200.0  # 100s 后，超过 ttl 60
    assert not c.is_recently_failed("k")


def test_get_stock_quote_bid_ask(monkeypatch):
    from investbrief.datasources.akshare import AKShareClient
    df = pd.DataFrame([
        {"item": "最新", "value": 64.72},
        {"item": "涨跌", "value": 0.7},
        {"item": "涨幅", "value": 1.09},
        {"item": "今开", "value": 63.5},
        {"item": "最高", "value": 66.22},
        {"item": "最低", "value": 62.99},
        {"item": "总手", "value": 1301297},
        {"item": "金额", "value": 8461745562},
        {"item": "换手", "value": 0.66},
    ])
    monkeypatch.setattr("investbrief.datasources.akshare.ak.stock_bid_ask_em", lambda symbol: df)
    # _lookup_name 走 _get_name_map_df → _get_all_stocks_df，全 mock 避免触网（本测试只验 bid_ask 解析）
    monkeypatch.setattr(AKShareClient, "_get_name_map_df", lambda self: None)
    monkeypatch.setattr(AKShareClient, "_get_all_stocks_df", lambda self: pd.DataFrame())
    client = AKShareClient()
    q = client.get_stock_quote("601138")
    assert q is not None
    assert q["symbol"] == "601138"
    assert q["price"] == 64.72
    assert q["change_pct"] == 1.09
    assert q["high"] == 66.22
    assert q["market_cap"] is None  # bid_ask 无市值
    assert q["name"] is None        # 全量 df mock 为空 → name 兜底 None


def test_get_stock_quote_bid_ask_failure_returns_none(monkeypatch):
    from investbrief.datasources.akshare import AKShareClient

    def fail(symbol):
        raise RuntimeError("throttled")

    monkeypatch.setattr("investbrief.datasources.akshare.ak.stock_bid_ask_em", fail)
    monkeypatch.setattr("investbrief.datasources.akshare.time.sleep", lambda s: None)
    client = AKShareClient()
    assert client.get_stock_quote("601138") is None


def test_get_stock_quote_name_from_all_df(monkeypatch):
    """问题3回归：bid_ask 无 name，应从 cached 全量 A 股 df 补。"""
    from investbrief.datasources.akshare import AKShareClient
    bid_ask = pd.DataFrame([{"item": "最新", "value": 10.0}])
    all_df = pd.DataFrame([{"代码": "601138", "名称": "工业富联"}])
    monkeypatch.setattr("investbrief.datasources.akshare.ak.stock_bid_ask_em", lambda symbol: bid_ask)
    monkeypatch.setattr(AKShareClient, "_get_all_stocks_df", lambda self: all_df)
    client = AKShareClient()
    q = client.get_stock_quote("601138")
    assert q is not None
    assert q["name"] == "工业富联"


def test_get_stock_quote_name_none_when_all_df_miss(monkeypatch):
    """问题3回归：全量 df 也查不到时 name 为 None（调用方 symbol 兜底）。"""
    from investbrief.datasources.akshare import AKShareClient
    bid_ask = pd.DataFrame([{"item": "最新", "value": 10.0}])
    monkeypatch.setattr("investbrief.datasources.akshare.ak.stock_bid_ask_em", lambda symbol: bid_ask)
    monkeypatch.setattr(AKShareClient, "_get_all_stocks_df", lambda self: pd.DataFrame())
    client = AKShareClient()
    q = client.get_stock_quote("999999")
    assert q is not None
    assert q["name"] is None


def test_research_report_df_shared_calls_api_once(monkeypatch):
    """P1-2 回归: summary + reports 共享同一 df 时, stock_research_report_em 只被调一次。"""
    from investbrief.datasources.akshare import AKShareClient

    calls = {"n": 0}

    def fake_em(symbol):
        calls["n"] += 1
        return pd.DataFrame([
            {"报告名称": "Q2 业绩前瞻", "东财评级": "买入", "机构": "中信",
             "日期": "2026-07-01", "盈利预测-收益2026": 42.0,
             "盈利预测-市盈率2026": 30.5},
            {"报告名称": "维持增持", "东财评级": "增持", "机构": "华泰",
             "日期": "2026-06-20", "盈利预测-收益2026": 41.0,
             "盈利预测-市盈率2026": 31.0},
        ])

    monkeypatch.setattr("investbrief.datasources.akshare.ak.stock_research_report_em", fake_em)
    client = AKShareClient()

    # 共享 df 流程: get_research_report_df 拉一次 → 传给两个方法
    df = client.get_research_report_df("600519")
    assert df is not None
    summary = client.get_analyst_rating_summary("600519", df=df)
    reports = client.get_research_reports("600519", limit=5, df=df)

    assert calls["n"] == 1, f"stock_research_report_em 应只调 1 次, 实际 {calls['n']}"
    assert summary is not None and summary["buy"] == 1 and summary["total_reports_all"] == 2
    assert len(reports) == 2 and reports[0]["institution"] == "中信"


def test_research_reports_fallback_fetches_when_no_df(monkeypatch):
    """向后兼容: get_research_reports 不传 df 时自行调 get_research_report_df(仍只拉一次)。"""
    from investbrief.datasources.akshare import AKShareClient

    calls = {"n": 0}

    def fake_em(symbol):
        calls["n"] += 1
        return pd.DataFrame([
            {"报告名称": "点评", "东财评级": "买入", "机构": "中信", "日期": "2026-07-01"},
        ])

    monkeypatch.setattr("investbrief.datasources.akshare.ak.stock_research_report_em", fake_em)
    client = AKShareClient()

    reports = client.get_research_reports("600519", limit=5)  # 不传 df
    assert calls["n"] == 1, f"fallback 路径应拉 1 次, 实际 {calls['n']}"
    assert len(reports) == 1 and reports[0]["rating"] == "买入"


def test_get_etf_hist_sina_fallback(monkeypatch):
    """em(fund_etf_hist_em)失败/空 → sina(fund_etf_hist_sina)兜底, 保证 ETF hist 不空。"""
    from investbrief.datasources import akshare as ak_mod
    from investbrief.datasources.akshare import AKShareClient

    # em 源返空(触发 sina fallback; 不抛异常, 走 if df empty 后继续)
    monkeypatch.setattr(ak_mod.ak, "fund_etf_hist_em", lambda **kw: pd.DataFrame())
    # sina 源返有效(英文小写列, date 为列 — 实测 fund_etf_hist_sina 返回格式)
    sina_df = pd.DataFrame({
        "date": ["2026-07-17"], "open": [1.0], "high": [1.1],
        "low": [0.9], "close": [1.05], "volume": [1000], "amount": [1050],
    })
    monkeypatch.setattr(ak_mod.ak, "fund_etf_hist_sina", lambda symbol: sina_df)
    # NAV fallback 不应触达(sina 已兜底)
    monkeypatch.setattr(AKShareClient, "get_etf_nav_history",
                        lambda self, fund, days=60: None)

    df = AKShareClient().get_etf_hist("510300", days=10)

    assert df is not None and len(df) == 1
    assert float(df.iloc[0]["close"]) == 1.05


def test_get_all_stocks_df_persist_fallback(monkeypatch):
    """_persist 跨 run 持久层命中 → 读昨日全市场快照, em 限流日 picks 不再 'no candidates'。"""
    from investbrief.datasources import akshare as ak_mod
    from investbrief.datasources.akshare import AKShareClient

    # 持久层命中(昨日收盘快照)
    monkeypatch.setattr(ak_mod._persist, "get",
                        lambda key, ttl: [{"代码": "000001", "名称": "平安", "最新价": 10}])
    # 持久层命中应直接返回, 不触达 live(stock_zh_a_spot_em 触网)
    def _fail_live(*a, **k):
        raise AssertionError("持久层命中不应触达 live 拉取")
    monkeypatch.setattr(ak_mod.ak, "stock_zh_a_spot_em", _fail_live)

    df = AKShareClient()._get_all_stocks_df()

    assert df is not None and len(df) == 1
    assert df.iloc[0]["代码"] == "000001"
