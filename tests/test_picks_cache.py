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
