from unittest.mock import patch
import pandas as pd
import pytest

from investbrief.data.valuation_data import ValuationData


@pytest.fixture
def tmp_db(tmp_path):
    return str(tmp_path / "t.db")


def _multpl_pe():
    return pd.DataFrame({
        "date": pd.to_datetime(["2024-01-01", "2024-02-01", "2024-03-01"]),
        "value": [30.0, 31.0, 32.0],
    })


def _multpl_bond():
    return pd.DataFrame({
        "date": pd.to_datetime(["2024-01-01", "2024-02-01", "2024-03-01"]),
        "value": [4.0, 4.1, 4.2],
    })


def test_update_erp_computes_and_stores(tmp_db):
    vd = ValuationData(db_path=tmp_db)
    with patch("investbrief.data.valuation_data.multpl.fetch_multpl_series",
               side_effect=[_multpl_pe(), _multpl_bond()]):
        ok = vd.update_erp()
    assert ok is True
    # ERP = 1/CAPE*100 - bond: 1/32*100 - 4.2 = 3.125 - 4.2 = -1.075
    erp = vd.latest_macro("ERP", "us")
    assert erp == pytest.approx(-1.075, abs=0.01)
    assert vd.latest_macro("SHILLER_PE", "us") == pytest.approx(32.0)
    assert vd.latest_macro("US_10Y_BOND", "us") == pytest.approx(4.2)


def test_update_erp_returns_false_on_multpl_failure(tmp_db):
    vd = ValuationData(db_path=tmp_db)
    with patch("investbrief.data.valuation_data.multpl.fetch_multpl_series",
               side_effect=Exception("network")):
        ok = vd.update_erp()
    assert ok is False
    assert vd.latest_macro("ERP", "us") is None


def test_update_erp_skips_when_already_run_today(tmp_db):
    vd = ValuationData(db_path=tmp_db)
    with patch("investbrief.data.valuation_data.multpl.fetch_multpl_series",
               side_effect=[_multpl_pe(), _multpl_bond()]):
        vd.update_erp()
    call_count = {"n": 0}

    def _boom(path):
        call_count["n"] += 1
        raise Exception("should not be called")
    with patch("investbrief.data.valuation_data.multpl.fetch_multpl_series", side_effect=_boom):
        ok = vd.update_erp()
    assert ok is True
    assert call_count["n"] == 0


def test_latest_percentile(tmp_db):
    vd = ValuationData(db_path=tmp_db)
    rows = pd.DataFrame([
        {"indicator": "X", "country": "us", "date": f"2020-0{i}-01", "value": float(i * 10)}
        for i in range(1, 6)
    ])
    vd.upsert_df("macro_data", rows)
    pct = vd.latest_percentile("X", "us", years=10)
    # 当前值 50（最大），5 个值里小于它的有 4 个 → 80%
    assert pct == 80.0
