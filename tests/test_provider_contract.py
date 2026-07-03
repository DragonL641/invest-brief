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


def test_us_provider_resilient_to_refresh_failure(us_provider, caplog):
    """refresh() 失败时不抛异常，get_* 仍返回库内已存值（韧性降级契约）。"""
    def _boom(*a, **k):
        raise RuntimeError("network down")
    us_provider.data.update_incremental = _boom
    with caplog.at_level("WARNING"):
        us_provider.refresh()  # 必须吞掉异常，不得上抛
    assert any("falling back to stored values" in r.message for r in caplog.records)
    # refresh 失败后，get_indices 仍读出预灌的库存值
    items = us_provider.get_indices()
    spx = next(i for i in items if i["name"] == "S&P 500")
    assert abs(spx["point"] - 101.0) < 1e-6


@pytest.fixture
def cn_provider():
    with tempfile.TemporaryDirectory() as d:
        db_path = str(Path(d) / "t.db")
        data = CNData(db_path=db_path)
        idx = pd.DataFrame([
            {"code": "sh000001", "date": "2026-06-30", "open": 1, "high": 1, "low": 1, "close": 3000.0, "volume": 1, "amount": None},
            {"code": "sh000001", "date": "2026-07-01", "open": 1, "high": 1, "low": 1, "close": 3030.0, "volume": 2, "amount": None},
        ])
        data.upsert_df("cn_index_daily", idx)
        macro = pd.DataFrame([
            {"indicator": "LPR1Y", "country": "cn", "date": "2026-07-20", "value": 3.1},
            {"indicator": "LPR5Y", "country": "cn", "date": "2026-07-20", "value": 3.6},
            {"indicator": "M2_YOY", "country": "cn", "date": "2026-06-01", "value": 8.5},
            {"indicator": "M1_YOY", "country": "cn", "date": "2026-06-01", "value": 5.0},
            {"indicator": "SOCIAL_FIN", "country": "cn", "date": "2026-06", "value": 50000.0},
            {"indicator": "10Y_TREASURY", "country": "cn", "date": "2026-07-01", "value": 2.3},
            {"indicator": "USDCNY", "country": "global", "date": "2026-06-30", "value": 7.20},
            {"indicator": "USDCNY", "country": "global", "date": "2026-07-01", "value": 7.25},
        ])
        data.upsert_df("macro_data", macro)
        p = CNMarketProvider(data=data)
        yield p
        data.close()


def test_cn_indices_contract_keys(cn_provider):
    items = cn_provider.get_indices()
    assert items
    expected = {"name", "symbol", "point", "change", "change_amt", "amount"}
    for it in items:
        assert expected <= set(it.keys())
    sh = next(i for i in items if i["symbol"] == "000001")
    assert abs(sh["point"] - 3030.0) < 1e-6
    assert abs(sh["change"] - 1.0) < 1e-3  # 3030 vs 3000 → 1%


def test_cn_monetary_contract_keys(cn_provider):
    mp = cn_provider.get_monetary_policy()
    assert set(mp.keys()) == {"lpr_1y", "lpr_5y", "m2_yoy", "m1_yoy",
                              "social_financing", "cn_10y_yield"}
    assert mp["lpr_1y"] == 3.1
    assert mp["cn_10y_yield"] == 2.3


def test_cn_asset_performance_includes_usdcny(cn_provider):
    ap = cn_provider.get_asset_performance()
    names = [a["name"] for a in ap]
    assert "人民币汇率(USDCNY)" in names
    fx = next(a for a in ap if a["name"] == "人民币汇率(USDCNY)")
    assert abs(fx["point"] - 7.25) < 1e-6
    assert abs(fx["change"] - round((7.25 - 7.20) / 7.20 * 100, 2)) < 1e-3


def test_us_render_section_embeds_risk_html(us_provider):
    data = {
        "asset_performance": [{"name": "S&P 500", "point": 100.0, "change": 0.0, "volume": "-"}],
    }
    html = us_provider.render_section(data, {"color_up": "#e74c3c", "color_down": "#27ae60"},
                                      risk_html="<!--RISK-MARKER-->")
    assert "<!--RISK-MARKER-->" in html
    # risk marker appears before the final closing section div (inside the section)
    last_close = html.rfind("</div>")
    marker = html.find("<!--RISK-MARKER-->")
    assert marker < last_close, "risk_html should be embedded inside the section, before its final </div>"


def test_us_render_section_no_risk_html_unchanged(us_provider):
    """Without risk_html, render_section output has no empty artifact."""
    data = {"asset_performance": [{"name": "S&P 500", "point": 100.0, "change": 0.0, "volume": "-"}]}
    html_default = us_provider.render_section(data, {"color_up": "#e74c3c", "color_down": "#27ae60"})
    assert "<!--RISK-MARKER-->" not in html_default


def test_cn_render_section_embeds_risk_html(cn_provider):
    data = {"asset_performance": [{"name": "上证指数", "symbol": "000001", "point": 3000.0,
                                    "change": 0.0, "change_amt": 0.0, "amount": None}]}
    html = cn_provider.render_section(data, {"color_up": "#e74c3c", "color_down": "#27ae60"},
                                      risk_html="<!--RISK-MARKER-->")
    assert "<!--RISK-MARKER-->" in html
    last_close = html.rfind("</div>")
    assert html.find("<!--RISK-MARKER-->") < last_close
