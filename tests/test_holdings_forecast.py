"""forecast 采集：US 盈利预估（EPS next-quarter + yoy growth）。CN 返回 {}（无免费源）。

yfinance.get_earnings_estimate 真实返回结构：
    {"+1q": {"avg": 2.1, "low": 1.9, "high": 2.3, "growth": 18.0, "num_analysts": 25}, ...}
按 period key 分桶（0q/+1q/0y/+1y）。我们取 +1q（下一季度）作为 eps_next；
growth 即 yoy_pct；revenue 无免费源 → None。
"""
from unittest.mock import patch
from investbrief.holdings.analyzer import HoldingsAnalyzer


def test_us_forecast_from_yfinance():
    """US: 从 +1q（下一季度）取 EPS avg；growth 即 yoy_pct。"""
    a = HoldingsAnalyzer()
    fake = {
        "0q": {"avg": 1.8, "low": 1.7, "high": 1.9, "growth": 10.0, "num_analysts": 20},
        "+1q": {"avg": 2.1, "low": 1.9, "high": 2.3, "growth": 18.0, "num_analysts": 25},
        "0y": {"avg": 7.5, "low": 7.0, "high": 8.0, "growth": 12.0, "num_analysts": 30},
    }
    with patch.object(a._yf, "get_earnings_estimate", return_value=fake):
        f = a._collect_forecast("AAPL", "us")
    assert f["eps_next"] == 2.1
    assert f["yoy_pct"] == 18.0
    # revenue 无免费源 → None
    assert f["revenue_next"] is None


def test_forecast_cn_returns_empty():
    """CN 返回 {}（无免费 forecast 源）。"""
    a = HoldingsAnalyzer()
    assert a._collect_forecast("002371", "cn") == {}


def test_forecast_resilient_on_failure():
    """异常 → {}（不阻塞整体）。"""
    a = HoldingsAnalyzer()
    with patch.object(a._yf, "get_earnings_estimate", side_effect=Exception("net")):
        assert a._collect_forecast("AAPL", "us") == {}


def test_forecast_empty_when_no_next_quarter():
    """源缺 +1q → eps_next=None（降级）。"""
    a = HoldingsAnalyzer()
    fake = {"0q": {"avg": 1.8, "low": 1.7, "high": 1.9, "growth": 10.0, "num_analysts": 20}}
    with patch.object(a._yf, "get_earnings_estimate", return_value=fake):
        f = a._collect_forecast("AAPL", "us")
    assert f["eps_next"] is None
    assert f["yoy_pct"] is None
