# tests/test_akshare_sina_fallback.py
"""datasources.akshare: _to_sina_symbol (bare code → sina sh/sz/bj prefix)."""
from investbrief.datasources.akshare import _to_sina_symbol


def test_sh_for_6_prefix():
    assert _to_sina_symbol("600519") == "sh600519"   # 上交所
    assert _to_sina_symbol("688981") == "sh688981"   # 科创板


def test_sz_for_0_3_prefix():
    assert _to_sina_symbol("000001") == "sz000001"   # 深主板
    assert _to_sina_symbol("300750") == "sz300750"   # 创业板


def test_bj_for_8_4_prefix():
    assert _to_sina_symbol("830799") == "bj830799"   # 北交所
    assert _to_sina_symbol("430047") == "bj430047"


def test_empty_and_passthrough():
    assert _to_sina_symbol("") == ""
    assert _to_sina_symbol("ABC") == "ABC"   # 无法识别前缀 → 原样
