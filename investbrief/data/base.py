"""Base data layer with SQLite operations."""

import sqlite3
from abc import ABC, abstractmethod
from datetime import datetime

import pandas as pd

from investbrief.core.config import DB_PATH
import logging
logger = logging.getLogger(__name__)


class BaseData(ABC):
    """Abstract base class for market data operations."""

    VALID_TABLES = {"cn_index_daily", "us_index_daily", "macro_data", "sentiment_data", "update_log"}

    # —— 市场声明（子类覆盖）——
    market_code: str = ""
    primary_index: str = ""          # 主指数 code, 如 "sh000001"/"^GSPC"; gold 留空
    primary_table: str = ""          # 主指数表, 如 "cn_index_daily"/"us_index_daily"
    primary_indicator: tuple[str, str] | None = None  # (indicator, country), 用于 macro_data 存储的市场(gold)

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._conn = None
        self._ensure_tables()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            import os
            parent = os.path.dirname(self.db_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            # check_same_thread=False：macro pipeline 并行 refresh 时连接在子线程使用。
            # WAL + busy_timeout + 应用层"refresh 完再串行 get_*"保证无并发写同一连接。
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            # WAL 提升并发读写（多个 BaseData 实例共享同一 db 文件）；
            # NORMAL 同步 + 5s busy_timeout 避免"database is locked"。
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
        return self._conn

    def _validate_table(self, table_name: str):
        if table_name not in self.VALID_TABLES:
            raise ValueError(f"Invalid table name: {table_name}")

    def _ensure_tables(self):
        """Create all tables if they don't exist."""
        cursor = self.conn.cursor()
        cursor.executescript("""
            CREATE TABLE IF NOT EXISTS cn_index_daily (
                code TEXT, date TEXT, open REAL, high REAL, low REAL,
                close REAL, volume REAL, amount REAL,
                PRIMARY KEY (code, date)
            );
            CREATE TABLE IF NOT EXISTS us_index_daily (
                code TEXT, date TEXT, open REAL, high REAL, low REAL,
                close REAL, volume REAL,
                PRIMARY KEY (code, date)
            );
            CREATE TABLE IF NOT EXISTS macro_data (
                indicator TEXT, country TEXT, date TEXT, value REAL,
                PRIMARY KEY (indicator, country, date)
            );
            CREATE TABLE IF NOT EXISTS sentiment_data (
                market TEXT, date TEXT,
                margin_balance REAL, north_flow REAL,  -- deprecated: 沪深交易所 2024-08-19 起停发, 不再写入/读取; 列保留避免迁移
                new_accounts REAL,
                total_market_cap REAL, pe_ratio REAL, pledge_ratio REAL,
                vix REAL, credit_spread REAL, put_call_ratio REAL,
                market_breadth REAL,
                PRIMARY KEY (market, date)
            );
            CREATE TABLE IF NOT EXISTS update_log (
                table_name TEXT PRIMARY KEY,
                last_update_date TEXT,
                update_time TEXT
            );
        """)
        self.conn.commit()

    def upsert_df(self, table_name: str, df: pd.DataFrame) -> int:
        """Insert DataFrame rows, skip duplicates based on composite PK.

        Returns count of newly inserted rows.
        """
        self._validate_table(table_name)
        if df.empty:
            return 0

        cols = list(df.columns)
        placeholders = ", ".join(["?"] * len(cols))
        col_str = ", ".join(cols)
        sql = f"INSERT OR IGNORE INTO {table_name} ({col_str}) VALUES ({placeholders})"

        rows = df[cols].where(df[cols].notna(), None).values.tolist()
        cursor = self.conn.cursor()
        with self.conn:  # 异常自动 rollback，正常自动 commit
            cursor.executemany(sql, rows)
        inserted = cursor.rowcount
        logger.info(f"Upserted {inserted} rows into {table_name}")
        return inserted

    def merge_sentiment_row(self, market: str, date: str, **fields):
        """Insert or merge a single sentiment_data row. Existing non-NULL values
        are preserved; new non-NULL values overwrite NULL columns."""
        cursor = self.conn.cursor()

        # Build column updates for non-None fields
        updates = {k: v for k, v in fields.items() if v is not None}
        if not updates:
            return

        # Check if row exists
        cursor.execute(
            "SELECT * FROM sentiment_data WHERE market = ? AND date = ?",
            (market, date),
        )
        existing = cursor.fetchone()

        if existing is None:
            # Insert new row
            cols = ["market", "date"] + list(updates.keys())
            vals = [market, date] + list(updates.values())
            placeholders = ", ".join(["?"] * len(cols))
            col_str = ", ".join(cols)
            cursor.execute(
                f"INSERT INTO sentiment_data ({col_str}) VALUES ({placeholders})", vals
            )
        else:
            # Update only NULL columns with new non-None values
            col_names = [desc[0] for desc in cursor.description]
            set_parts = []
            set_vals = []
            for col, val in updates.items():
                if col not in ("market", "date"):
                    idx = col_names.index(col) if col in col_names else -1
                    if idx >= 0 and existing[idx] is None:
                        set_parts.append(f"{col} = ?")
                        set_vals.append(val)
            if set_parts:
                sql = f"UPDATE sentiment_data SET {', '.join(set_parts)} WHERE market = ? AND date = ?"
                cursor.execute(sql, set_vals + [market, date])

        self.conn.commit()

    def get_update_date(self, table_name: str) -> str | None:
        """Get last update date for a table."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT last_update_date FROM update_log WHERE table_name = ?",
            (table_name,),
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def get_update_time(self, table_name: str) -> str | None:
        """Get the actual fetch timestamp (update_time) for a table.

        Unlike get_update_date (which holds the data's own date — can be old for
        lagging series like Shiller PE), this returns when we last RAN the fetch.
        Use for recency gates.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT update_time FROM update_log WHERE table_name = ?",
            (table_name,),
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def set_update_date(self, table_name: str, date: str):
        """Record last update date for a table."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO update_log (table_name, last_update_date, update_time) "
                "VALUES (?, ?, ?)",
                (table_name, date, now),
            )

    def query(self, sql: str, params: tuple = ()) -> pd.DataFrame:
        """Execute a SELECT query and return DataFrame."""
        return pd.read_sql_query(sql, self.conn, params=params)

    def latest_bars(self, table_name: str, code: str, n: int = 2) -> pd.DataFrame:
        """返回某 (表, code) 的最近 n 根日 bar，最新在前。无数据返回空 DataFrame。"""
        self._validate_table(table_name)
        sql = f"SELECT * FROM {table_name} WHERE code = ? ORDER BY date DESC LIMIT ?"
        return pd.read_sql_query(sql, self.conn, params=(code, n))

    def latest_macro(self, indicator: str, country: str) -> float | None:
        """返回 macro_data 中某 (indicator, country) 的最新 value，无则 None。"""
        sql = ("SELECT value FROM macro_data WHERE indicator = ? AND country = ? "
               "ORDER BY date DESC LIMIT 1")
        df = pd.read_sql_query(sql, self.conn, params=(indicator, country))
        if df.empty or pd.isna(df.iloc[0]["value"]):
            return None
        return float(df.iloc[0]["value"])

    def latest_macro_yoy(self, indicator: str, country: str, period: int) -> float | None:
        """绝对值宏观序列 → 同比(%)。period=一年期数(月频 12 / 季频 4)。

        取最近 period+1 期，latest vs 一年前同期。用于 GDP/M2 这类存绝对值的指标；
        CPI/LPR 等已同比的指标直接用 latest_macro。数据不足/除零 → None。
        """
        sql = ("SELECT value FROM macro_data WHERE indicator = ? AND country = ? "
               "ORDER BY date DESC LIMIT ?")
        df = pd.read_sql_query(sql, self.conn, params=(indicator, country, period + 1))
        if len(df) <= period:
            return None
        latest = df.iloc[0]["value"]
        year_ago = df.iloc[period]["value"]
        if pd.isna(latest) or pd.isna(year_ago) or year_ago == 0:
            return None
        return round((float(latest) / float(year_ago) - 1) * 100, 3)

    def _latest_data_date(self, table_name: str) -> str | None:
        """Max date string (YYYY-MM-DD) in table, or None if empty."""
        self._validate_table(table_name)
        sql = f"SELECT MAX(date) as max_date FROM {table_name}"
        df = pd.read_sql_query(sql, self.conn)
        if df.empty or pd.isna(df.iloc[0]["max_date"]):
            return None
        return str(df.iloc[0]["max_date"])[:10]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    @abstractmethod
    def update_all(self):
        """Full download from inception to present."""

    @abstractmethod
    def update_incremental(self):
        """Incremental update since last recorded date."""

    def is_fresh(self) -> bool:
        """当日数据是否已更新(DB-First 快路径)。子类(CNData/USData)覆盖; GoldData 用默认。"""
        return True

    def _retry_api(self, fn):
        """Call API function with retries on failure."""
        import time
        from investbrief.core.config import API_RETRY_COUNT, API_RETRY_DELAY

        for attempt in range(API_RETRY_COUNT):
            try:
                return fn()
            except Exception as e:
                logger.warning(f"API call attempt {attempt + 1} failed: {e}")
                if attempt < API_RETRY_COUNT - 1:
                    time.sleep(API_RETRY_DELAY)
                else:
                    logger.error(f"API call failed after {API_RETRY_COUNT} attempts: {e}")
                    raise
