"""cn_activity：龙虎榜上榜次数 + 机构调研次数（CN 独有）。

- 龙虎榜数据源 AKShareClient.get_dragon_tiger_list 返回全市场最近 days 日上榜股票，
  字段为 `symbol`（已标准化）+ `date`，需按 symbol 后过滤统计次数。
- 机构调研数据源 AKShareClient.get_institutional_research(symbol, days) 已按 symbol 过滤，
  返回该股调研事件列表 [{institution, date, type, researchers}]。
- US 市场返回 {}（不适用）。
- 韧性：任一数据源异常 → 返回 {}，不阻塞整体分析。
"""
from unittest.mock import patch

from investbrief.holdings.analyzer import HoldingsAnalyzer


def test_cn_activity_counts():
    """龙虎榜：3 条中 2 条匹配 symbol，机构调研 2 条。"""
    a = HoldingsAnalyzer()
    dragon_data = [
        {"symbol": "002371", "date": "2026-06-01"},
        {"symbol": "002371", "date": "2026-06-10"},
        {"symbol": "999999", "date": "2026-06-05"},
    ]
    research_data = [
        {"institution": "中信证券", "date": "2026-06-01"},
        {"institution": "招商证券", "date": "2026-06-15"},
    ]
    with patch.object(a._ak, "get_dragon_tiger_list", return_value=dragon_data), \
         patch.object(a._ak, "get_institutional_research", return_value=research_data):
        act = a._collect_cn_activity("002371", "cn")
    assert act["dragon_tiger_count"] == 2
    assert act["institution_research_count"] == 2


def test_cn_activity_us_returns_empty():
    """US 市场不适用，直接返回 {}。"""
    a = HoldingsAnalyzer()
    assert a._collect_cn_activity("AAPL", "us") == {}


def test_cn_activity_resilient_on_failure():
    """任一数据源异常 → 返回 {}，不抛出。"""
    a = HoldingsAnalyzer()
    with patch.object(a._ak, "get_dragon_tiger_list", side_effect=Exception("net")):
        assert a._collect_cn_activity("002371", "cn") == {}


def test_cn_activity_empty_data():
    """数据源返回空列表 → 计数为 0。"""
    a = HoldingsAnalyzer()
    with patch.object(a._ak, "get_dragon_tiger_list", return_value=[]), \
         patch.object(a._ak, "get_institutional_research", return_value=[]):
        act = a._collect_cn_activity("002371", "cn")
    assert act == {"dragon_tiger_count": 0, "institution_research_count": 0}
