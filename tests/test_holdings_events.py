"""events 采集：US 用 yfinance；CN 用季报规则推算。"""
from datetime import date, timedelta
from unittest.mock import patch
from investbrief.holdings.analyzer import HoldingsAnalyzer


def test_us_events_from_yfinance():
    a = HoldingsAnalyzer()
    # yfinance get_earnings_dates 返回 [{"date": "YYYY-MM-DD"}, ...]（无 type 字段）
    fake_dates = [{"date": (date.today() + timedelta(days=20)).isoformat()}]
    with patch.object(a._yf, "get_earnings_dates", return_value=fake_dates):
        ev = a._collect_events("AAPL", "us")
    assert ev["days_to_next"] is not None
    assert 15 <= ev["days_to_next"] <= 25
    assert ev["next_earnings"] == fake_dates[0]["date"]
    assert ev["is_in_window"] is False


def test_cn_events_rule_based():
    a = HoldingsAnalyzer()
    ev = a._collect_events("002371", "cn")
    assert "next_earnings" in ev
    assert "days_to_next" in ev
    assert ev["days_to_next"] >= 0


def test_events_empty_on_failure():
    a = HoldingsAnalyzer()
    with patch.object(a._yf, "get_earnings_dates", side_effect=Exception("net")):
        ev = a._collect_events("AAPL", "us")
    assert ev == {}
