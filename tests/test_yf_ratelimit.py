# tests/test_yf_ratelimit.py
"""YFinanceClient 限流退避单测。无网络：mock Ticker。"""
from investbrief.datasources.yfinance import YFinanceClient


def _ticker_that_rate_limits_then_succeeds(final_df):
    """返回一个 mock Ticker：前 2 次 .history 抛限流异常，第 3 次返回 final_df。"""
    calls = {"n": 0}

    class _Hist:
        def __init__(self, symbol, session):
            self.symbol = symbol
        def history(self, period="6mo"):
            calls["n"] += 1
            if calls["n"] < 3:
                raise Exception("Too Many Requests. Rate limited. Try after a while.")
            return final_df
    return _Hist


def test_get_history_retries_on_rate_limit(monkeypatch):
    import pandas as pd
    df = pd.DataFrame({"Open": [1], "High": [2], "Low": [0.5],
                       "Close": [1.5], "Volume": [100]})
    fake_ticker_cls = _ticker_that_rate_limits_then_succeeds(df)
    monkeypatch.setattr("yfinance.Ticker", fake_ticker_cls)
    monkeypatch.setattr("time.sleep", lambda *_: None)

    client = YFinanceClient()
    out = client.get_history("AMD", period="5d")
    assert out is not None and not out.empty
    assert "Close" in out.columns


def test_get_history_gives_up_after_max_retries(monkeypatch):
    class _AlwaysLimited:
        def __init__(self, symbol, session): pass
        def history(self, period="6mo"):
            raise Exception("429 Too Many Requests")
    monkeypatch.setattr("yfinance.Ticker", _AlwaysLimited)
    monkeypatch.setattr("time.sleep", lambda *_: None)

    client = YFinanceClient()
    out = client.get_history("AMD", period="5d")
    assert out is None
