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
