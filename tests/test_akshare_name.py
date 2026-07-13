"""_lookup_name 回归测试。

根因：em 限流时 stock_zh_a_spot_em 返回**部分 df**(非空但缺某些 symbol)，
_get_all_stocks_df 不验证行数就缓存，导致 _lookup_name 对缺失 symbol 返回 None，
holdings 邮件里显示代码(601138)而非名字(工业富联)。

修复：_lookup_name 优先用静态 name_map(stock_info_a_code_name, 1d 缓存, 独立于
实时行情)，fallback spot_em df。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from investbrief.datasources.akshare import AKShareClient


def test_lookup_name_uses_name_map_when_spot_partial(monkeypatch):
    """em 限流 → spot_em 部分返回(缺 601138)；_lookup_name 应从静态 name_map 取到 name。"""
    c = AKShareClient()
    # spot_em 部分缺 601138(模拟 em 限流部分返回被缓存)
    monkeypatch.setattr(c, "_get_all_stocks_df", lambda: pd.DataFrame(
        {"代码": ["002230"], "名称": ["科大讯飞"]}))
    # name_map 完整(静态源, 独立于实时行情)
    monkeypatch.setattr(c, "_get_name_map_df", lambda: pd.DataFrame(
        {"code": ["002230", "601138"], "name": ["科大讯飞", "工业富联"]}))
    assert c._lookup_name("601138") == "工业富联"  # spot 没有 → 来自 name_map
    assert c._lookup_name("002230") == "科大讯飞"


def test_lookup_name_fallback_spot_when_name_map_missing(monkeypatch):
    """name_map 拉取失败时, _lookup_name fallback spot_em df。"""
    c = AKShareClient()
    monkeypatch.setattr(c, "_get_name_map_df", lambda: None)
    monkeypatch.setattr(c, "_get_all_stocks_df", lambda: pd.DataFrame(
        {"代码": ["601138"], "名称": ["工业富联"]}))
    assert c._lookup_name("601138") == "工业富联"


def test_lookup_name_returns_none_when_both_fail(monkeypatch):
    """name_map + spot 都失败 → None(调用方用 symbol 兜底)。"""
    c = AKShareClient()
    monkeypatch.setattr(c, "_get_name_map_df", lambda: None)
    monkeypatch.setattr(c, "_get_all_stocks_df", lambda: None)
    assert c._lookup_name("601138") is None


def test_get_name_map_df_cached_and_not_refetch(monkeypatch):
    """name_map 1d 缓存命中时不重新请求(轻量静态源, 减 em 依赖)。"""
    c = AKShareClient()
    cached = pd.DataFrame({"code": ["601138"], "name": ["工业富联"]})
    called = {"n": 0}

    def _fake_get(key, ttl):
        return cached if key == "a_code_name" else None

    def _fake_retry(fn, **kw):
        called["n"] += 1
        return None  # 即使调用也不该走到(缓存命中)

    from investbrief.datasources import akshare as ak_mod
    monkeypatch.setattr(ak_mod._df_cache, "get", _fake_get)
    monkeypatch.setattr(ak_mod, "_with_retry", _fake_retry)
    assert c._get_name_map_df() is cached
    assert called["n"] == 0  # 缓存命中, 未触网
