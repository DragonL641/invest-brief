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
    client = AKShareClient()
    q = client.get_stock_quote("601138")
    assert q is not None
    assert q["symbol"] == "601138"
    assert q["price"] == 64.72
    assert q["change_pct"] == 1.09
    assert q["high"] == 66.22
    assert q["market_cap"] is None  # bid_ask 无市值


def test_get_stock_quote_bid_ask_failure_returns_none(monkeypatch):
    from investbrief.datasources.akshare import AKShareClient

    def fail(symbol):
        raise RuntimeError("throttled")

    monkeypatch.setattr("investbrief.datasources.akshare.ak.stock_bid_ask_em", fail)
    monkeypatch.setattr("investbrief.datasources.akshare.time.sleep", lambda s: None)
    client = AKShareClient()
    assert client.get_stock_quote("601138") is None
