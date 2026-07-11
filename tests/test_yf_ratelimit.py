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


def test_get_quote_derives_price_from_history(monkeypatch):
    """get_quote 改用 history 派生(避开 fast_info 多属性访问触发 yahoo 429)。"""
    import pandas as pd
    df = pd.DataFrame({
        "Close": [100.0, 105.0],
        "High": [101.0, 106.0],
        "Low": [99.0, 104.0],
        "Volume": [1000, 2000],
    })

    class _T:
        def __init__(self, symbol, session):
            pass
        def history(self, period="6mo"):
            return df

    monkeypatch.setattr("yfinance.Ticker", _T)
    monkeypatch.setattr("time.sleep", lambda *_: None)

    q = YFinanceClient().get_quote("AMD")
    assert q is not None
    assert q["price"] == 105.0           # 最后一根 bar Close
    assert q["previous_close"] == 100.0  # 倒数第二根 bar Close
    assert q["change"] == 5.0
    assert q["change_percent"] == 5.0
    assert q["day_high"] == 106.0
    assert q["day_low"] == 104.0
    assert q["volume"] == 2000
    assert q["source"] == "yfinance"
    assert "market_cap" not in q  # 已删(死端字段,analyzer.py:474 有 info 兜底)


def test_get_quote_returns_none_when_history_empty(monkeypatch):
    """history 空 → None(保持健康探针语义:yfinance 不可达即跳过其余 endpoint)。"""
    import pandas as pd

    class _T:
        def __init__(self, symbol, session):
            pass
        def history(self, period="6mo"):
            return pd.DataFrame()

    monkeypatch.setattr("yfinance.Ticker", _T)
    assert YFinanceClient().get_quote("AMD") is None
