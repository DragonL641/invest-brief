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
