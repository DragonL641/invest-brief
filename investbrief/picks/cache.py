# investbrief/picks/cache.py
"""picks 因子数据 TTL 缓存(sqlite KV)。

仅用于 affordability(财报/估值/行业映射季频变化),引擎正确性不依赖它:
miss 即重新拉取。缓存文件 data/picks_cache.db 可随时清空。
"""
from __future__ import annotations
import json
import logging
import sqlite3
import time

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cache (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    ts REAL NOT NULL
)
"""


class FactorCache:
    def __init__(self, path: str):
        self.path = path
        try:
            self._conn = sqlite3.connect(path)
            self._conn.execute(_SCHEMA)
            self._conn.commit()
        except sqlite3.Error as e:
            logger.warning(f"FactorCache init failed ({path}): {e}; cache disabled")
            self._conn = None

    def get(self, key: str):
        """Return stored value (any JSON type) or None if absent. Does NOT check TTL."""
        if self._conn is None:
            return None
        try:
            row = self._conn.execute(
                "SELECT value, ts FROM cache WHERE key = ?", (key,)
            ).fetchone()
        except sqlite3.Error as e:
            logger.warning(f"FactorCache get failed ({key}): {e}")
            return None
        if not row:
            return None
        return json.loads(row[0])

    def fresh(self, key: str, ttl_days: float) -> bool:
        """True iff key exists and is within ttl_days of its stored timestamp."""
        if self._conn is None:
            return False
        try:
            row = self._conn.execute(
                "SELECT ts FROM cache WHERE key = ?", (key,)
            ).fetchone()
        except sqlite3.Error:
            return False
        return bool(row) and (time.time() - row[0]) < ttl_days * 86400

    def set(self, key: str, value, ttl_days: float = 7.0):
        if self._conn is None:
            return
        try:
            self._conn.execute(
                "INSERT OR REPLACE INTO cache(key, value, ts) VALUES(?, ?, ?)",
                (key, json.dumps(value, ensure_ascii=False, default=str), time.time()),
            )
            self._conn.commit()
        except sqlite3.Error as e:
            logger.warning(f"FactorCache set failed ({key}): {e}")

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None
