"""HoldingResult 字段扩展契约。"""
from investbrief.holdings.analyzer import HoldingResult


def test_holding_result_has_new_fields():
    r = HoldingResult(symbol="600519", market="cn", type="stock")
    for field in ("events", "insider", "cn_activity", "forecast", "fund_meta"):
        assert hasattr(r, field), f"missing field: {field}"
        assert getattr(r, field) == {}


def test_to_dict_includes_new_fields():
    r = HoldingResult(symbol="600519", market="cn", type="stock",
                      events={"next_earnings": "2026-08-31"})
    d = r.to_dict()
    assert "events" in d
    assert d["events"]["next_earnings"] == "2026-08-31"
    for field in ("insider", "cn_activity", "forecast", "fund_meta"):
        assert field in d
