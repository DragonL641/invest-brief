"""数据层单测：建表/upsert 去重/query/merge_sentiment/latest 辅助。

用临时 SQLite 文件，无网络。
"""
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from investbrief.data import cn_data as cn_mod
from investbrief.data.base import BaseData
from investbrief.data.cn_data import CNData
from investbrief.data.us_data import USData


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


def test_cn_index_codes_cover_five_indices():
    """CNData 必须覆盖 invest-brief 的 5 个 A 股指数。"""
    assert set(CNData.INDEX_CODES) == {
        "sh000001", "sz399001", "sz399006", "sh000300", "sh000688",
    }


def test_cn_monetary_writes_lpr_m2_social_financing(monkeypatch, db):
    """LPR/M2/M1/社融 必须落 macro_data 且保留全历史。"""
    def fake_lpr():
        return pd.DataFrame([
            {"TRADE_DATE": "2026-06-20", "LPR1Y": 3.1, "LPR5Y": 3.6},
            {"TRADE_DATE": "2026-07-20", "LPR1Y": 3.1, "LPR5Y": 3.6},
        ])

    def fake_money():
        return pd.DataFrame([
            {"月份": "2026年05月份", "货币和准货币(M2)-同比增长": 8.4, "货币(M1)-同比增长": 4.8},
            {"月份": "2026年06月份", "货币和准货币(M2)-同比增长": 8.5, "货币(M1)-同比增长": 5.0},
        ])

    def fake_shrzgm():
        # 实测 akshare macro_china_shrzgm 月份为 "YYYYMM"（非 "YYYY年MM月份"）
        return pd.DataFrame([
            {"月份": "202605", "社会融资规模增量": 48000.0},
            {"月份": "202606", "社会融资规模增量": 50000.0},
        ])

    monkeypatch.setattr(cn_mod.ak, "macro_china_lpr", fake_lpr)
    monkeypatch.setattr(cn_mod.ak, "macro_china_money_supply", fake_money)
    monkeypatch.setattr(cn_mod.ak, "macro_china_shrzgm", fake_shrzgm)

    class _CN(CNData):
        def update_all(self): pass
        def update_incremental(self): pass
        def _update_gdp(self): pass
        def _update_cpi(self): pass
        def _update_treasury_yield(self): pass
        def _update_usdcny(self): pass

    c = _CN(db_path=db.db_path)
    c.update_macro()
    c.close()

    # latest values
    assert db.latest_macro("LPR1Y", "cn") == 3.1
    assert db.latest_macro("LPR5Y", "cn") == 3.6
    assert db.latest_macro("M2_YOY", "cn") == 8.5
    assert db.latest_macro("M1_YOY", "cn") == 5.0
    assert db.latest_macro("SOCIAL_FIN", "cn") == 50000.0
    # 社融日期必须为 ISO 格式（回归：shrzgm 月份为 "YYYYMM"，曾误产 "202606-01"）
    social_date = db.query(
        "SELECT date FROM macro_data WHERE indicator='SOCIAL_FIN' AND country='cn' "
        "ORDER BY date DESC LIMIT 1"
    ).iloc[0]["date"]
    assert social_date == "2026-06-01"
    # full history persisted (2 rows for LPR1Y and M2_YOY)
    n_lpr = db.query("SELECT COUNT(*) AS n FROM macro_data WHERE indicator='LPR1Y' AND country='cn'").iloc[0]["n"]
    n_m2 = db.query("SELECT COUNT(*) AS n FROM macro_data WHERE indicator='M2_YOY' AND country='cn'").iloc[0]["n"]
    assert n_lpr == 2
    assert n_m2 == 2


def test_us_index_symbols_cover_investbrief_surface():
    """USData 必须覆盖 invest-brief 渲染的全部美股符号。"""
    assert set(USData.INDEX_SYMBOLS) == {
        "^GSPC", "^IXIC", "^DJI", "^VIX", "^TNX", "^FVX", "^IRX",
        "HYG", "CL=F", "DX-Y.NYB", "GC=F",
    }


def test_us_update_index_daily_uses_start_when_has_last_date(monkeypatch, db):
    """有 last_date 时走增量 (history(start=...))，无则 period=max。"""
    from investbrief.data import us_data as us_mod
    calls = []

    class _FakeTicker:
        def __init__(self, sym): self._sym = sym
        def history(self, **kw):
            calls.append(kw)
            return pd.DataFrame({"Date": [pd.Timestamp("2026-07-03")],
                                 "Open":[1],"High":[1],"Low":[1],"Close":[1],"Volume":[1]})

    monkeypatch.setattr(us_mod.yf, "Ticker", lambda s: _FakeTicker(s))

    class _US(us_mod.USData):
        def update_all(self): pass
        def update_incremental(self): pass

    # First run: no last_date → period="max"
    c1 = _US(db_path=db.db_path)
    c1.update_index_daily()
    c1.close()
    assert any("period" in k for k in calls), "first run should use period=max"
    assert calls and "max" in calls[0].get("period", "")

    calls.clear()
    # Second run: last_date now set → start= used
    c2 = _US(db_path=db.db_path)
    c2.update_index_daily()
    c2.close()
    assert any("start" in k for k in calls), "incremental run should use start="


def test_gold_update_fred_series_uses_last_date_as_cosd(monkeypatch, db):
    """update_fred_series 默认 cosd 取 last_update_date（增量）。"""
    from investbrief.data import gold_data as gd_mod
    captured = {}

    class _FakeResp:
        status_code = 200
        text = "date,M2SL\n2026-07-01,21000\n"

    def fake_get(url, timeout=None):
        captured["url"] = url
        return _FakeResp()

    monkeypatch.setattr(gd_mod.requests, "get", fake_get)

    class _Gold(gd_mod.GoldData):
        def update_all(self): pass
        def update_incremental(self): pass

    g = _Gold(db_path=db.db_path)
    # Pre-seed a last_update_date for M2/us
    g.set_update_date("macro_data_m2_us", "2026-06-01")
    g.update_fred_series("M2SL", "M2", "us")
    g.close()
    assert "cosd=2026-06-01" in captured["url"], f"incremental cosd not applied: {captured['url']}"


def test_cn_margin_incremental_uses_last_date_for_chunk_start(monkeypatch, db):
    """有 last_date 时，margin 分块从 last_date 附近起（不再从 2010）。"""
    fetched_ranges = []

    def fake_margin(start_date, end_date):
        fetched_ranges.append((start_date, end_date))
        return pd.DataFrame([
            {"信用交易日期": "20260701", "融资融券余额": 15000.0},
        ])

    monkeypatch.setattr(cn_mod.ak, "stock_margin_sse", fake_margin)

    class _CN(cn_mod.CNData):
        def update_all(self): pass
        def update_incremental(self): pass

    c = _CN(db_path=db.db_path)
    c.set_update_date("sentiment_margin_cn", "2026-06-15")
    c._update_margin()
    c.close()
    # Chunks should start around 2026-06 (not 2010)
    assert fetched_ranges, "no chunks fetched"
    first_start = fetched_ranges[0][0]
    assert first_start.startswith("2026"), f"incremental chunk should start near last_date, got {first_start}"


def test_cn_margin_first_run_starts_from_2010(monkeypatch, db):
    fetched = {"called": False, "first_start": None}

    def fake_margin(start_date, end_date):
        if not fetched["called"]:
            fetched["first_start"] = start_date
        fetched["called"] = True
        # return empty to short-circuit the loop's row processing
        return pd.DataFrame()

    monkeypatch.setattr(cn_mod.ak, "stock_margin_sse", fake_margin)

    class _CN(cn_mod.CNData):
        def update_all(self): pass
        def update_incremental(self): pass

    c = _CN(db_path=db.db_path)
    # No last_date set → first run
    c._update_margin()
    c.close()
    assert fetched["called"]
    assert fetched["first_start"].startswith("2010"), f"first run should start from 2010, got {fetched['first_start']}"


def test_us_shiller_pe_skipped_when_recent(monkeypatch, db):
    """Shiller PE 在 7 天内已取过 → 跳过 xls 下载。"""
    from investbrief.data import us_data as us_mod
    from datetime import datetime, timedelta
    called = {"get": False}

    def fake_get(url, timeout=None):
        called["get"] = True
        raise AssertionError("should not download when recent")

    monkeypatch.setattr(us_mod.urllib.request, "urlopen", fake_get)

    class _US(us_mod.USData):
        def update_all(self): pass
        def update_incremental(self): pass

    c = _US(db_path=db.db_path)
    recent = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
    c.set_update_date("sentiment_pe_us_shiller", recent)
    c._update_shiller_pe()
    c.close()
    assert not called["get"], "xls should not be downloaded when last fetch < 7 days ago"
