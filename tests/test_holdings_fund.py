"""fund 扩展：fund_meta（scale/manager/rating）。

源限制：investbrief.datasources.akshare.AKShareClient.get_open_fund_nav 当前只返回
nav/acc_nav/date/daily_change/return_1w/1m/3m，不提供 scale/manager/rating。
因此 fund_meta 在源未扩展前固定为 {scale: None, manager: None, rating: None}
（键必须存在以供 renderer 优雅降级）。
"""
from unittest.mock import patch
from investbrief.holdings.analyzer import HoldingsAnalyzer


def test_fund_meta_keys_present_even_if_none():
    """源不提供 scale/manager/rating → fund_meta 三个键存在但值为 None。"""
    a = HoldingsAnalyzer()
    fake_nav = {
        "nav": 1.5,
        "acc_nav": 2.0,
        "daily_change": 0.5,
        "name": "测试基金",
        "date": "2026-07-04",
        "return_1w": 0.3,
        "return_1m": 1.2,
        "return_3m": 3.5,
    }
    with patch.object(a._ak, "get_open_fund_nav", return_value=fake_nav):
        r = a._analyze_cn_fund("000001")
    assert r.type == "fund"
    assert r.fund_meta == {"scale": None, "manager": None, "rating": None}


def test_fund_meta_keys_present_when_source_lacks_fields():
    """即使 fake_nav 完全不含 scale/manager/rating 键，fund_meta 三键仍存在。"""
    a = HoldingsAnalyzer()
    fake_nav = {"nav": 1.5, "name": "测试基金"}  # 极简 nav
    with patch.object(a._ak, "get_open_fund_nav", return_value=fake_nav):
        r = a._analyze_cn_fund("000001")
    assert r.type == "fund"
    assert "scale" in r.fund_meta
    assert "manager" in r.fund_meta
    assert "rating" in r.fund_meta
    assert r.fund_meta["scale"] is None
    assert r.fund_meta["manager"] is None
    assert r.fund_meta["rating"] is None
