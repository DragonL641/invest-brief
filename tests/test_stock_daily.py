"""stock_daily 持久化层：建表/upsert/has_today_bar/query。临时 SQLite，无网络。"""
import tempfile
from pathlib import Path
from datetime import date

import pandas as pd
import pytest

from investbrief.data.base import BaseData


@pytest.fixture
def db():
    with tempfile.TemporaryDirectory() as d:
        db_path = str(Path(d) / "t.db")
        class _C(BaseData):
            def update_all(self): pass
            def update_incremental(self): pass
        c = _C(db_path=db_path)
        yield c
        c.close()


def test_stock_daily_table_created(db):
    names = set(db.query("SELECT name FROM sqlite_master WHERE type='table'")["name"])
    assert "stock_daily" in names


def test_upsert_and_query_stock_daily(db):
    df = pd.DataFrame([
        {"market": "us", "symbol": "AMD", "date": "2026-07-09",
         "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 100, "amount": None},
    ])
    assert db.upsert_stock_df(df) == 1
    out = db.query_stock_daily("us", "AMD", n=5)
    assert len(out) == 1 and out.iloc[0]["close"] == 1.5


def test_has_today_bar(db):
    assert db.has_today_bar("us", "AMD") is False
    today = date.today().isoformat()
    df = pd.DataFrame([{"market": "us", "symbol": "AMD", "date": today,
                        "open": 1, "high": 2, "low": 1, "close": 1.5, "volume": 1, "amount": None}])
    db.upsert_stock_df(df)
    assert db.has_today_bar("us", "AMD") is True


def test_query_stock_daily_returns_n_most_recent_ascending(db):
    # 多行 → 返回最近 n 根、升序
    rows = [{"market": "cn", "symbol": "002371", "date": f"2026-07-0{i}",
             "open": 1, "high": 2, "low": 1, "close": float(i), "volume": 10, "amount": None}
            for i in range(1, 6)]
    db.upsert_stock_df(pd.DataFrame(rows))
    out = db.query_stock_daily("cn", "002371", n=3)
    assert len(out) == 3
    assert list(out["date"]) == ["2026-07-03", "2026-07-04", "2026-07-05"]  # 升序、最近3根
