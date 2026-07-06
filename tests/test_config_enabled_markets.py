"""enabled_market_codes: 从 config 提取启用的市场列表。"""
from investbrief.core.config import enabled_market_codes


def test_us_cn_enabled_gold_default():
    cfg = {"markets": {"us": {"enabled": True}, "cn": {"enabled": True}}}
    assert set(enabled_market_codes(cfg)) == {"us", "cn", "gold"}


def test_disabled_excluded():
    cfg = {"markets": {"us": {"enabled": True}, "cn": {"enabled": False}}}
    codes = enabled_market_codes(cfg)
    assert "cn" not in codes
    assert "us" in codes


def test_gold_explicit_disabled():
    cfg = {"markets": {"us": {"enabled": True}, "cn": {"enabled": True},
                       "gold": {"enabled": False}}}
    assert "gold" not in enabled_market_codes(cfg)
