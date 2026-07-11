"""cn_activity：龙虎榜上榜次数 + 机构调研次数（CN 独有）。

- 龙虎榜数据源 AKShareClient.get_dragon_tiger_list 返回全市场最近 days 日上榜股票，
  字段为 `symbol`（已标准化）+ `date`，需按 symbol 后过滤统计次数。
- 机构调研数据源 AKShareClient.get_institutional_research(symbol, days) 已按 symbol 过滤，
  返回该股调研事件列表 [{institution, date, type, researchers}]。
- 非 CN 市场（防御性）返回 {}。
- 韧性：dragon_tiger 异常 → 降级 dt_count=0（run 级缓存吞异常，多只 CN stock 共享一次拉取）；research 异常 → 返回已采集部分。不阻塞整体分析。
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


def test_cn_activity_non_cn_returns_empty():
    """非 CN 市场（防御性）直接返回 {}。"""
    a = HoldingsAnalyzer()
    assert a._collect_cn_activity("XXX", "us") == {}
    assert a._collect_cn_activity("XXX", "jp") == {}


def test_cn_activity_resilient_on_failure():
    """dragon_tiger 异常 → 降级 dt_count=0（不整体失败）；research 正常返回。"""
    a = HoldingsAnalyzer()
    a._dragon_tiger_cache.clear()
    with patch.object(a._ak, "get_dragon_tiger_list", side_effect=Exception("net")), \
         patch.object(a._ak, "get_institutional_research", return_value=[]):
        result = a._collect_cn_activity("002371", "cn")
    assert result == {"dragon_tiger_count": 0, "institution_research_count": 0}


def test_dragon_tiger_cache_shared_across_calls():
    """run 级缓存：多只 CN stock 共享一次 dragon_tiger 全市场拉取。"""
    a = HoldingsAnalyzer()
    a._dragon_tiger_cache.clear()
    call_count = {"n": 0}

    def counting(*args, **kwargs):
        call_count["n"] += 1
        return [{"symbol": "002371"}]

    with patch.object(a._ak, "get_dragon_tiger_list", side_effect=counting), \
         patch.object(a._ak, "get_institutional_research", return_value=[]):
        a._collect_cn_activity("002371", "cn")
        a._collect_cn_activity("300750", "cn")
        a._collect_cn_activity("002230", "cn")
    assert call_count["n"] == 1, f"dragon_tiger 应只拉 1 次（缓存共享），实际 {call_count['n']}"


def test_cn_activity_empty_data():
    """数据源返回空列表 → 计数为 0。"""
    a = HoldingsAnalyzer()
    with patch.object(a._ak, "get_dragon_tiger_list", return_value=[]), \
         patch.object(a._ak, "get_institutional_research", return_value=[]):
        act = a._collect_cn_activity("002371", "cn")
    assert act == {"dragon_tiger_count": 0, "institution_research_count": 0}
