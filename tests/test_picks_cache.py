# tests/test_picks_cache.py
"""picks.cache: sqlite TTL KV; miss=fetch, 可随时清空。"""
from investbrief.picks.cache import FactorCache


def test_set_get_roundtrip(tmp_path):
    c = FactorCache(str(tmp_path / "c.db"))
    c.set("k", {"a": 1}, ttl_days=1)
    assert c.get("k") == {"a": 1}


def test_miss_returns_none(tmp_path):
    c = FactorCache(str(tmp_path / "c.db"))
    assert c.get("absent") is None


def test_fresh_checks_ttl(tmp_path):
    """fresh() is the TTL gate; get() ignores TTL."""
    c = FactorCache(str(tmp_path / "c.db"))
    c.set("k", "v", ttl_days=1)
    assert c.fresh("k", ttl_days=1) is True
    # backdate the timestamp by 3 days
    c._conn.execute("UPDATE cache SET ts = ts - 3*86400 WHERE key = 'k'")
    c._conn.commit()
    assert c.fresh("k", ttl_days=1) is False   # expired
    assert c.get("k") == "v"                    # get still returns the stale value


def test_corrupt_db_tolerated(tmp_path):
    """A non-database file at the cache path must not raise; cache degrades to disabled."""
    p = tmp_path / "c.db"
    p.write_text("not a db", encoding="utf-8")
    c = FactorCache(str(p))   # must not raise
    assert c.get("k") is None
    assert c.fresh("k", ttl_days=1) is False


def test_disabled_cache_noops(tmp_path):
    """If init failed (conn is None), all ops are safe no-ops."""
    c = FactorCache(str(tmp_path / "c.db"))
    c._conn = None   # simulate disabled
    assert c.get("k") is None
    assert c.fresh("k", ttl_days=1) is False
    c.set("k", "v")  # must not raise


# ---- 日K 历史(CSV 编码,跨日缓存) ----

def test_history_set_get_roundtrip(tmp_path):
    """DataFrame CSV 编码 round-trip:列、值、datetime index 全保留。"""
    import pandas as pd
    c = FactorCache(str(tmp_path / "c.db"))
    df = pd.DataFrame(
        {"close": [10.0, 11.0, 12.0], "volume": [1e6, 2e6, 3e6]},
        index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
    )
    c.set_history("hist:cn:X", df, ttl_days=1)
    got = c.get_history("hist:cn:X")
    assert got is not None
    assert list(got["close"]) == [10.0, 11.0, 12.0]
    assert list(got["volume"]) == [1e6, 2e6, 3e6]
    # index 保为 datetime(跨日复用时 factors 按 iloc 读,索引顺序重要)
    assert str(got.index[0]).startswith("2024-01-01")


def test_history_get_absent_returns_none(tmp_path):
    c = FactorCache(str(tmp_path / "c.db"))
    assert c.get_history("hist:cn:absent") is None


def test_history_set_empty_df_noop(tmp_path):
    """空 DataFrame 不写入(避免命中时返回空帧)。"""
    import pandas as pd
    c = FactorCache(str(tmp_path / "c.db"))
    c.set_history("hist:cn:X", pd.DataFrame(), ttl_days=1)   # must not raise
    assert c.get_history("hist:cn:X") is None


def test_history_key_isolated_from_json_get(tmp_path):
    """hist: key(CSV)与 fund: key(JSON)共用 cache 表,前缀隔离不交叉解析。"""
    c = FactorCache(str(tmp_path / "c.db"))
    import pandas as pd
    df = pd.DataFrame({"close": [10.0]}, index=pd.to_datetime(["2024-01-01"]))
    c.set_history("hist:cn:X", df, ttl_days=1)
    c.set("fund:cn:X", {"roe": 0.2}, ttl_days=7)
    # 用对的方法取对的类型
    assert c.get("fund:cn:X") == {"roe": 0.2}
    assert c.get_history("hist:cn:X") is not None
    # 用错的方法(对 hist key 调 get)→ JSON 解析失败 → None(不抛)
    assert c.get("hist:cn:X") is None


def test_history_concurrent_access_thread_safe(tmp_path):
    """ThreadPoolExecutor(max_workers=2) 并发 get/set_history 不损坏 sqlite。"""
    import pandas as pd
    from concurrent.futures import ThreadPoolExecutor
    c = FactorCache(str(tmp_path / "c.db"))
    df = pd.DataFrame({"close": [10.0]}, index=pd.to_datetime(["2024-01-01"]))

    def _op(i):
        key = f"hist:cn:X{i}"
        c.set_history(key, df, ttl_days=1)
        got = c.get_history(key)
        return got is not None and not got.empty

    with ThreadPoolExecutor(max_workers=2) as ex:
        results = list(ex.map(_op, range(10)))
    assert all(results), f"some concurrent ops failed: {results}"

