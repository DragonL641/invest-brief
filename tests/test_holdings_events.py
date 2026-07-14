"""events 采集：6 源合并，按距今天数排序取最近 5。hermetic（mock get_stock_events，无网络）。"""
from datetime import date, timedelta
from unittest.mock import patch

from investbrief.holdings.analyzer import HoldingsAnalyzer


def _make_events(offsets):
    """构造固定 events：offsets 为相对今天的天数列表。返回 list[{type, date, desc}]。"""
    today = date.today()
    return [
        {"type": "earnings", "date": (today + timedelta(days=d)).isoformat(), "desc": f"ev_{d}"}
        for d in offsets
    ]


def test_collect_events_sorts_by_proximity_and_caps_at_5():
    """返回 {events, count}，按 |date-today| 升序，取最近 5。"""
    a = HoldingsAnalyzer()
    fake = _make_events([-100, -10, 3, 0, 200, 30])
    with patch.object(a._ak, "get_stock_events", return_value=fake):
        ev = a._collect_events("002371", "cn")
    assert set(ev.keys()) == {"events", "count"}
    assert ev["count"] == 5  # 6 条取最近 5，offset=200 被裁掉
    # 最近 5 条按 |offset| 升序：|0|, |3|, |-10|, |30|, |-100|（符号随原 event 透传）
    offsets = [int(e["desc"].split("_")[1]) for e in ev["events"]]
    assert offsets == [0, 3, -10, 30, -100]


def test_collect_events_empty_when_no_data():
    """无事件返回 {}。"""
    a = HoldingsAnalyzer()
    with patch.object(a._ak, "get_stock_events", return_value=[]):
        ev = a._collect_events("002371", "cn")
    assert ev == {}


def test_collect_events_skips_unparseable_dates():
    """无法解析的 date 被过滤；合法的保留。"""
    a = HoldingsAnalyzer()
    today = date.today()
    fake = [
        {"type": "earnings", "date": "not-a-date", "desc": "bad"},
        {"type": "earnings", "date": (today + timedelta(days=5)).isoformat(), "desc": "good"},
    ]
    with patch.object(a._ak, "get_stock_events", return_value=fake):
        ev = a._collect_events("002371", "cn")
    assert ev["count"] == 1
    assert ev["events"][0]["desc"] == "good"
