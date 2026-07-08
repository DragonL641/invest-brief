"""Provider 返回 shape 契约回归：P1 重构前后 key 集合必须一致。

用预灌的临时 DB 构造 provider，不触网。
"""
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from investbrief.data.us_data import USData
from investbrief.data.cn_data import CNData
from investbrief.market.us.provider import USMarketProvider
from investbrief.market.cn.provider import CNMarketProvider


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
    assert set(mp.keys()) == {"us_10y_yield", "us_5y_yield", "us_13w_yield", "fed_funds_rate",
                              "cpi_yoy", "gdp_yoy", "m2_yoy", "pmi"}
    assert mp["us_10y_yield"] == 4.3
    # 宏观指标 key 存在（fixture 无 macro_data → 值为 None，key 必须在）
    for k in ("cpi_yoy", "gdp_yoy", "m2_yoy", "pmi"):
        assert k in mp


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
                              "social_financing", "cn_10y_yield",
                              "cpi_yoy", "gdp_yoy"}
    assert mp["lpr_1y"] == 3.1
    assert mp["cn_10y_yield"] == 2.3
    # 宏观指标 key 存在（fixture 无 CPI/GDP → 值为 None，key 必须在）
    for k in ("cpi_yoy", "gdp_yoy"):
        assert k in mp


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


def _asset_card_open_tag(html: str) -> str:
    """提取首个 asset-card 的开标签（含 style 属性），用于断言内联样式。"""
    start = html.find('class="asset-card"')
    assert start != -1, "render_section 未产出 asset-card"
    return html[start:html.find(">", start) + 1]


def test_us_asset_card_has_inline_margin_spacing(us_provider):
    """回归：大类资产卡片间距必须由每个 card 的 inline margin 提供，不能只靠
    flex gap —— 多数邮件客户端（Gmail 移动端/Outlook/网易QQ邮箱）忽略 flex gap，
    导致灰底卡片贴合粘成一团（见 issue: 大类资产卡片粘在一起）。"""
    data = {"asset_performance": [{"name": "S&P 500", "point": 100.0, "change": 0.0, "volume": "-"}]}
    html = us_provider.render_section(data, {"color_up": "#e74c3c", "color_down": "#27ae60"})
    tag = _asset_card_open_tag(html)
    assert "margin" in tag, "asset-card 缺少 inline margin，间距会因 gap 被忽略而消失"
    grid_start = html.find('class="asset-grid"')
    grid_tag = html[grid_start:html.find(">", grid_start) + 1]
    assert "gap" not in grid_tag, "asset-grid 不应再依赖 gap（改用 card margin）"


def test_cn_asset_card_has_inline_margin_spacing(cn_provider):
    """同 test_us_asset_card_has_inline_margin_spacing，CN 侧回归。"""
    data = {"asset_performance": [{"name": "上证指数", "symbol": "000001", "point": 3000.0,
                                    "change": 0.0, "change_amt": 0.0, "amount": None}]}
    html = cn_provider.render_section(data, {"color_up": "#e74c3c", "color_down": "#27ae60"})
    tag = _asset_card_open_tag(html)
    assert "margin" in tag, "asset-card 缺少 inline margin，间距会因 gap 被忽略而消失"
    grid_start = html.find('class="asset-grid"')
    grid_tag = html[grid_start:html.find(">", grid_start) + 1]
    assert "gap" not in grid_tag, "asset-grid 不应再依赖 gap（改用 card margin）"


def test_us_monetary_render_formats_yield_to_2dp(us_provider):
    """问题1回归：收益率渲染统一 ≤2 位小数；联邦基金目标(字符串)原样保留。"""
    html = us_provider._render_monetary_policy(
        {"us_10y_yield": 4.327, "us_5y_yield": 4.1, "us_13w_yield": 4.2567,
         "fed_funds_rate": "5.25% - 5.50%"},
        {"color_up": "#e74c3c", "color_down": "#27ae60"},
    )
    assert "4.33%" in html    # 4.327 → 2 位
    assert "4.10%" in html    # 4.1 → 2 位
    assert "4.26%" in html    # 4.2567 → 2 位
    assert "5.25% - 5.50%" in html   # 字符串原样
    assert "4.327" not in html and "4.2567" not in html


def test_cn_monetary_render_formats_to_2dp(cn_provider):
    """问题1回归：CN 货币指标渲染统一 ≤2 位小数。"""
    html = cn_provider._render_monetary_policy(
        {"lpr_1y": 3.12345, "m2_yoy": 8.5, "social_financing": 50000.0, "cn_10y_yield": 2.3},
        {"color_up": "#e74c3c", "color_down": "#27ae60"},
    )
    assert "3.12%" in html       # 3.12345 → 2 位
    assert "8.50%" in html
    assert "2.30%" in html
    assert "50000.00亿元" in html
    assert "3.12345" not in html


# ==================== B2-1: 宏观指标 CPI/GDP/M2/PMI 渲染契约 ====================

def _us_macro_rows():
    """生成 US macro_data：CPI(同比%)/PMI(绝对值) 单行 + GDP/M2 月频绝对值 13 期(够算 YoY)。"""
    rows = [
        {"indicator": "CPI", "country": "us", "date": "2026-06-01", "value": 3.2},
        {"indicator": "PMI", "country": "us", "date": "2026-06-01", "value": 52.0},
    ]
    # GDP 月频绝对值(万亿USD)：2025-07=30.0 → 2026-07=30.9，YoY=3.0%
    for i, ym in enumerate([
        "2025-07", "2025-08", "2025-09", "2025-10", "2025-11", "2025-12",
        "2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07",
    ]):
        rows.append({"indicator": "GDP", "country": "us", "date": f"{ym}-01",
                     "value": round(30.0 + i * 0.075, 3)})
    # M2 月频绝对值(万亿USD)：2025-07=21.0 → 2026-07=22.05，YoY=5.0%
    for i, ym in enumerate([
        "2025-07", "2025-08", "2025-09", "2025-10", "2025-11", "2025-12",
        "2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07",
    ]):
        rows.append({"indicator": "M2", "country": "us", "date": f"{ym}-01",
                     "value": round(21.0 + i * 0.0875, 3)})
    return rows


def test_us_monetary_reads_macro_indicators():
    """B2-1 回归：us provider get_monetary_policy 从 macro_data 取 CPI/GDP/M2/PMI（原仅入库不消费）。"""
    with tempfile.TemporaryDirectory() as d:
        db_path = str(Path(d) / "t.db")
        data = USData(db_path=db_path)
        data.upsert_df("macro_data", pd.DataFrame(_us_macro_rows()))
        p = USMarketProvider(data=data)
        mp = p.get_monetary_policy()
        assert mp["cpi_yoy"] == 3.2          # 源即同比
        assert mp["pmi"] == 52.0
        # GDP YoY: (30.9 / 30.0 - 1) * 100 ≈ 3.0
        assert mp["gdp_yoy"] is not None and abs(mp["gdp_yoy"] - 3.0) < 0.2
        # M2 YoY: (22.05 / 21.0 - 1) * 100 ≈ 5.0
        assert mp["m2_yoy"] is not None and abs(mp["m2_yoy"] - 5.0) < 0.2
        data.close()


def test_us_monetary_renders_macro_indicators():
    """B2-1 回归：_render_monetary_policy 输出含 CPI/GDP/M2/PMI 数值行。"""
    with tempfile.TemporaryDirectory() as d:
        db_path = str(Path(d) / "t.db")
        data = USData(db_path=db_path)
        data.upsert_df("macro_data", pd.DataFrame(_us_macro_rows()))
        p = USMarketProvider(data=data)
        html = p._render_monetary_policy(p.get_monetary_policy(),
                                         {"color_up": "#e74c3c", "color_down": "#27ae60"})
        assert "CPI同比" in html and "3.20%" in html
        assert "GDP同比" in html
        assert "M2同比" in html
        assert "制造业PMI" in html and "52.00" in html
        data.close()


def _cn_macro_rows():
    """生成 CN macro_data：CPI(同比%) 单行 + GDP 季频绝对值 5 期(够算 YoY, period=4)。"""
    rows = [{"indicator": "CPI", "country": "cn", "date": "2026-06-01", "value": 0.3}]
    # GDP 季频绝对值：2025-Q2=30.0 → 2026-Q2=31.5，YoY=5.0%
    for q, val in [("2025-03-31", 29.0), ("2025-06-30", 30.0), ("2025-09-30", 30.5),
                   ("2025-12-31", 31.0), ("2026-03-31", 31.2), ("2026-06-30", 31.5)]:
        rows.append({"indicator": "GDP", "country": "cn", "date": q, "value": val})
    return rows


def test_cn_monetary_reads_cpi_gdp():
    """B2-1 回归：cn provider get_monetary_policy 从 macro_data 取 CPI/GDP（原仅入库不消费）。"""
    with tempfile.TemporaryDirectory() as d:
        db_path = str(Path(d) / "t.db")
        data = CNData(db_path=db_path)
        data.upsert_df("macro_data", pd.DataFrame(_cn_macro_rows()))
        p = CNMarketProvider(data=data)
        mp = p.get_monetary_policy()
        assert mp["cpi_yoy"] == 0.3
        # GDP YoY: 2026-06 vs 2025-06 = 31.5/30.0 - 1 = 5.0%
        assert mp["gdp_yoy"] is not None and abs(mp["gdp_yoy"] - 5.0) < 0.2
        data.close()


def test_cn_monetary_renders_cpi_gdp():
    """B2-1 回归：_render_monetary_policy 输出含 CPI/GDP 数值行。"""
    with tempfile.TemporaryDirectory() as d:
        db_path = str(Path(d) / "t.db")
        data = CNData(db_path=db_path)
        data.upsert_df("macro_data", pd.DataFrame(_cn_macro_rows()))
        p = CNMarketProvider(data=data)
        html = p._render_monetary_policy(p.get_monetary_policy(),
                                         {"color_up": "#e74c3c", "color_down": "#27ae60"})
        assert "CPI同比" in html and "0.30%" in html
        assert "GDP同比" in html
        data.close()
