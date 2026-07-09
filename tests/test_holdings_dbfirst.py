"""holdings history DB-First：stock_daily 有 today bar → 不触发实时拉取。"""
import pandas as pd
from datetime import date
from pathlib import Path
import tempfile

from investbrief.data.base import BaseData
from investbrief.holdings import analyzer as az


def _tmp_db():
    d = tempfile.TemporaryDirectory()
    db_path = str(Path(d.name) / "t.db")
    class _C(BaseData):
        def update_all(self): pass
        def update_incremental(self): pass
    return d, _C(db_path=db_path)


def test_history_db_first_hits_cache_when_today_bar_present():
    d, db = _tmp_db()
    try:
        today = date.today().isoformat()
        db.upsert_stock_df(pd.DataFrame([{
            "market": "cn", "symbol": "002371", "date": today,
            "open": 100, "high": 110, "low": 99, "close": 105, "volume": 1000, "amount": None}]))
        live_called = {"n": 0}
        def fake_live(symbol, days=180):
            live_called["n"] += 1
            return pd.DataFrame()
        out = az._history_db_first("cn", "002371", days=180, db=db, live_fetch=fake_live)
        assert live_called["n"] == 0, "有 today bar 仍触发实时拉取"
        assert out is not None and len(out) == 1 and out.iloc[0]["close"] == 105
    finally:
        d.cleanup()


def test_history_db_first_falls_back_to_live_and_writes_back():
    d, db = _tmp_db()
    try:
        today = date.today().isoformat()
        live = pd.DataFrame([{
            "market": "cn", "symbol": "002371", "date": today,
            "open": 1, "high": 2, "low": 1, "close": 1.5, "volume": 1, "amount": None}])
        out = az._history_db_first("cn", "002371", days=180, db=db,
                                   live_fetch=lambda s, days=180: live)
        assert out is not None and len(out) >= 1
        # 回写验证：DB 现在有 today bar
        assert db.has_today_bar("cn", "002371") is True
    finally:
        d.cleanup()


def test_history_db_first_normalizes_datetimeindex_and_writes_back():
    """真实数据源（akshare/yfinance）返回 DatetimeIndex —— 锁住索引分支 + strftime 归一化。

    两个源都把 date 作为 index（非列），走 `rows["date"] = df.index` 分支。
    若有人改回 astype(str)，会写出 "YYYY-MM-DD 00:00:00"，has_today_bar 不命中 → 此测试失败。
    """
    d, db = _tmp_db()
    try:
        today = date.today().isoformat()
        idx = pd.DatetimeIndex([today])  # 模拟 akshare set_index("date") / yfinance .history() 默认索引
        live = pd.DataFrame({"open": [1], "high": [2], "low": [1], "close": [1.5], "volume": [1]}, index=idx)
        out = az._history_db_first("cn", "002371", days=180, db=db,
                                   live_fetch=lambda s, days=180: live)
        assert out is not None and len(out) >= 1
        assert db.has_today_bar("cn", "002371") is True   # strftime → "YYYY-MM-DD" 匹配
    finally:
        d.cleanup()


def test_history_db_first_dbhit_returns_datetimeindex_aligned_with_live():
    """DB-hit 返回 shape 须与 live（DatetimeIndex + ohlcv）对齐，防 compute_indicators 契约破坏。

    query_stock_daily 原始返回 date 为列 + market/symbol 多余列；归一化后须变 DatetimeIndex + 无 market/symbol。
    """
    d, db = _tmp_db()
    try:
        today = date.today().isoformat()
        db.upsert_stock_df(pd.DataFrame([{
            "market": "us", "symbol": "AMD", "date": today,
            "open": 1, "high": 2, "low": 1, "close": 1.5, "volume": 100, "amount": None}]))
        out = az._history_db_first("us", "AMD", days=180, db=db,
                                   live_fetch=lambda s, days=180: pd.DataFrame())  # live 不应被调
        assert isinstance(out.index, pd.DatetimeIndex), "DB-hit 须返回 DatetimeIndex 对齐 live 契约"
        assert "close" in out.columns and "volume" in out.columns
        assert "market" not in out.columns and "symbol" not in out.columns  # 多余列已 drop
    finally:
        d.cleanup()
