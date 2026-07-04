"""ETF→index 映射。"""
from investbrief.datasources.akshare import _ETF_INDEX_MAP, resolve_etf_index


def test_known_etf_maps_to_index():
    assert _ETF_INDEX_MAP.get("510300") == "000300"   # 沪深300ETF → 沪深300
    assert _ETF_INDEX_MAP.get("588200") == "000688"   # 科创50
    assert _ETF_INDEX_MAP.get("512880") == "399975"   # 证券


def test_resolve_returns_none_for_unknown():
    assert resolve_etf_index("999999") is None


def test_resolve_returns_index_for_known():
    assert resolve_etf_index("510300") == "000300"
