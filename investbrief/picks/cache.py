# investbrief/picks/cache.py
"""picks 因子数据 TTL 缓存(sqlite KV)。

仅用于 affordability(财报/估值/行业映射季频变化)+ 日K历史(TTL=1 天),
引擎正确性不依赖它: miss 即重新拉取。缓存文件 data/picks_cache.db 可随时清空。

线程安全: check_same_thread=False + threading.Lock,允许 picks pipeline 的
ThreadPoolExecutor(max_workers=2) 工作线程并发访问(get/fresh/set/history*)。

两种 value 编码:
- JSON  (get/set):           fund/flow/prof_years/earliest_period/industry 等标量/dict
- CSV   (get_history/set_history): 日K DataFrame(JSON 挤 str 会丢类型,用 CSV 保 OHLCV 数值)
key 前缀(hist: vs fund:)天然隔离两类编码,不会交叉解析。
"""
from __future__ import annotations
import io
import json
import logging
import sqlite3
import threading
import time

import pandas as pd

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
        self._lock = threading.Lock()
        try:
            # check_same_thread=False: 允许 ThreadPoolExecutor 工作线程访问同一连接;
            # 并发安全由 self._lock 串行化所有 DB 操作保证(单写者,串行读者)。
            self._conn = sqlite3.connect(path, check_same_thread=False)
            self._conn.execute(_SCHEMA)
            self._conn.commit()
        except sqlite3.Error as e:
            logger.warning(f"FactorCache init failed ({path}): {e}; cache disabled")
            self._conn = None

    def get(self, key: str):
        """Return stored value (any JSON type) or None if absent. Does NOT check TTL."""
        if self._conn is None:
            return None
        with self._lock:
            try:
                row = self._conn.execute(
                    "SELECT value, ts FROM cache WHERE key = ?", (key,)
                ).fetchone()
            except sqlite3.Error as e:
                logger.warning(f"FactorCache get failed ({key}): {e}")
                return None
        if not row:
            return None
        try:
            return json.loads(row[0])
        except (json.JSONDecodeError, TypeError):
            return None

    def fresh(self, key: str, ttl_days: float) -> bool:
        """True iff key exists and is within ttl_days of its stored timestamp."""
        if self._conn is None:
            return False
        with self._lock:
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
            payload = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError) as e:
            logger.warning(f"FactorCache set JSON failed ({key}): {e}")
            return
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT OR REPLACE INTO cache(key, value, ts) VALUES(?, ?, ?)",
                    (key, payload, time.time()),
                )
                self._conn.commit()
            except sqlite3.Error as e:
                logger.warning(f"FactorCache set failed ({key}): {e}")

    # ---- 日K 历史(CSV 编码,TTL=1 天) ----

    def get_history(self, key: str):
        """Return cached DataFrame (datetime index) or None if absent.

        不校验 TTL —— 调用方先 fresh() 判定。CSV value 列与 JSON 共用同一表,
        靠 hist: 前缀隔离(不会与 fund: 等 JSON key 碰撞)。
        """
        if self._conn is None:
            return None
        with self._lock:
            try:
                row = self._conn.execute(
                    "SELECT value FROM cache WHERE key = ?", (key,)
                ).fetchone()
            except sqlite3.Error as e:
                logger.warning(f"FactorCache get_history failed ({key}): {e}")
                return None
        if not row:
            return None
        try:
            return pd.read_csv(io.StringIO(row[0]), index_col=0, parse_dates=True)
        except Exception as e:
            logger.warning(f"FactorCache get_history parse failed ({key}): {e}")
            return None

    def set_history(self, key: str, df: pd.DataFrame, ttl_days: float = 1.0):
        """缓存日K DataFrame(CSV 编码)。空 df / 失败静默跳过。"""
        if self._conn is None or df is None or df.empty:
            return
        buf = io.StringIO()
        try:
            df.to_csv(buf)
        except Exception as e:
            logger.warning(f"FactorCache set_history encode failed ({key}): {e}")
            return
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT OR REPLACE INTO cache(key, value, ts) VALUES(?, ?, ?)",
                    (key, buf.getvalue(), time.time()),
                )
                self._conn.commit()
            except sqlite3.Error as e:
                logger.warning(f"FactorCache set_history failed ({key}): {e}")

    def close(self):
        with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None
