"""数据层单测：建表/upsert 去重/query/merge_sentiment/latest 辅助。

用临时 SQLite 文件，无网络。
"""
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from investbrief.data.base import BaseData


@pytest.fixture
def db():
    with tempfile.TemporaryDirectory() as d:
        db_path = str(Path(d) / "t.db")

        class _Concrete(BaseData):
            def update_all(self): pass
            def update_incremental(self): pass

        c = _Concrete(db_path=db_path)
        yield c
        c.close()


def test_tables_created(db):
    names = set(db.query("SELECT name FROM sqlite_master WHERE type='table'")["name"])
    assert {"cn_index_daily", "us_index_daily", "macro_data",
            "sentiment_data", "update_log"} <= names


def test_upsert_df_dedups_by_pk(db):
    df = pd.DataFrame([{"code": "^GSPC", "date": "2026-07-01", "open": 1, "high": 2,
                        "low": 0.5, "close": 1.5, "volume": 100}])
    assert db.upsert_df("us_index_daily", df) == 1
    assert db.upsert_df("us_index_daily", df) == 0  # 同 PK 去重


def test_upsert_rejects_unknown_table(db):
    with pytest.raises(ValueError):
        db.upsert_df("evil; DROP TABLE", pd.DataFrame([{"a": 1}]))


def test_merge_sentiment_row_preserves_existing(db):
    db.merge_sentiment_row("us", "2026-07-01", vix=15.0)
    db.merge_sentiment_row("us", "2026-07-01", credit_spread=0.01)  # 不覆盖已有 vix
    row = db.query("SELECT vix, credit_spread FROM sentiment_data WHERE market='us' AND date='2026-07-01'")
    assert float(row.iloc[0]["vix"]) == 15.0
    assert float(row.iloc[0]["credit_spread"]) == 0.01


def test_latest_bars_returns_most_recent_first(db):
    df = pd.DataFrame([
        {"code": "^GSPC", "date": "2026-06-29", "open": 1, "high": 1, "low": 1, "close": 10.0, "volume": 1},
        {"code": "^GSPC", "date": "2026-06-30", "open": 1, "high": 1, "low": 1, "close": 11.0, "volume": 2},
        {"code": "^GSPC", "date": "2026-07-01", "open": 1, "high": 1, "low": 1, "close": 12.0, "volume": 3},
    ])
    db.upsert_df("us_index_daily", df)
    bars = db.latest_bars("us_index_daily", "^GSPC", n=2)
    assert len(bars) == 2
    assert bars.iloc[0]["date"] == "2026-07-01"   # 最新在前
    assert bars.iloc[1]["date"] == "2026-06-30"


def test_latest_macro_returns_latest_value(db):
    df = pd.DataFrame([
        {"indicator": "LPR1Y", "country": "cn", "date": "2026-06-20", "value": 3.1},
        {"indicator": "LPR1Y", "country": "cn", "date": "2026-07-20", "value": 3.0},
    ])
    db.upsert_df("macro_data", df)
    assert db.latest_macro("LPR1Y", "cn") == 3.0


def test_latest_macro_missing_returns_none(db):
    assert db.latest_macro("NOPE", "cn") is None
