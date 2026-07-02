"""Provider 返回 shape 契约回归：P1 重构前后 key 集合必须一致。

用预灌的临时 DB 构造 provider，不触网。
"""
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from investbrief.data.us_data import USData
from investbrief.data.cn_data import CNData
from investbrief.us.provider import USMarketProvider
from investbrief.cn.provider import CNMarketProvider


@pytest.fixture
def us_provider():
    with tempfile.TemporaryDirectory() as d:
        db_path = str(Path(d) / "t.db")
        data = USData(db_path=db_path)
        # 灌入两日 bar 以计算 change
        rows = pd.DataFrame([
            {"code": "^GSPC", "date": "2026-06-30", "open": 1, "high": 1, "low": 1, "close": 100.0, "volume": 10},
            {"code": "^GSPC", "date": "2026-07-01", "open": 1, "high": 1, "low": 1, "close": 101.0, "volume": 11},
            {"code": "^TNX",  "date": "2026-07-01", "open": 1, "high": 1, "low": 1, "close": 4.3, "volume": 0},
            {"code": "^FVX",  "date": "2026-07-01", "open": 1, "high": 1, "low": 1, "close": 4.1, "volume": 0},
            {"code": "^IRX",  "date": "2026-07-01", "open": 1, "high": 1, "low": 1, "close": 4.25, "volume": 0},
            {"code": "GC=F",  "date": "2026-06-30", "open": 1, "high": 1, "low": 1, "close": 2300.0, "volume": 1},
            {"code": "GC=F",  "date": "2026-07-01", "open": 1, "high": 1, "low": 1, "close": 2320.0, "volume": 2},
        ])
        data.upsert_df("us_index_daily", rows)
        p = USMarketProvider(data=data)
        yield p
        data.close()


def test_us_indices_contract_keys(us_provider):
    items = us_provider.get_indices()
    assert items, "indices 不应为空"
    expected_keys = {"name", "point", "change", "volume"}
    for it in items:
        assert expected_keys <= set(it.keys()), f"缺 key: {set(it.keys())}"
    # change 计算正确性：101 vs 100 → 1.0%
    spx = next(i for i in items if i["name"] == "S&P 500")
    assert abs(spx["point"] - 101.0) < 1e-6
    assert abs(spx["change"] - 1.0) < 1e-3


def test_us_monetary_contract_keys(us_provider):
    mp = us_provider.get_monetary_policy()
    assert set(mp.keys()) == {"us_10y_yield", "us_5y_yield", "us_13w_yield", "fed_funds_rate"}
    assert mp["us_10y_yield"] == 4.3


def test_us_asset_performance_includes_gold(us_provider):
    ap = us_provider.get_asset_performance()
    names = [a["name"] for a in ap]
    assert "黄金(COMEX)" in names
    for a in ap:
        assert {"name", "point", "change"} <= set(a.keys())
