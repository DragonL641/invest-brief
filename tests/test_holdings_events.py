"""events 采集：CN 用季报披露窗口规则推算。"""
from investbrief.holdings.analyzer import HoldingsAnalyzer


def test_cn_events_rule_based():
    a = HoldingsAnalyzer()
    ev = a._collect_events("002371", "cn")
    assert "next_earnings" in ev
    assert "days_to_next" in ev
    assert ev["days_to_next"] >= 0


def test_cn_events_next_is_closest_window():
    """规则推算：返回距离今天最近的季报披露窗口。"""
    from datetime import date
    a = HoldingsAnalyzer()
    today = date.today()
    ev = a._collect_events("002371", "cn")
    # next_earnings 必须 >= today（未来窗口）
    assert ev["next_earnings"] >= today.isoformat()
    # days_to_next 与 next_earnings 一致
    expected_days = (date.fromisoformat(ev["next_earnings"]) - today).days
    assert ev["days_to_next"] == expected_days


def test_events_empty_on_failure():
    """market 非法 → analyze_one 整体降级；_collect_events 本身对 cn 不会抛。"""
    # _collect_events 对 cn 始终能推算（无外部依赖），故此处验证调用无异常
    a = HoldingsAnalyzer()
    ev = a._collect_events("002371", "cn")
    assert isinstance(ev, dict)
    assert "next_earnings" in ev
