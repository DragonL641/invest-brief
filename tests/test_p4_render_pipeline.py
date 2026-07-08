"""P4 渲染管线：真实 DB → 三市场风险卡 → market_section_html 含全部卡片。"""
import os
from investbrief.core.config import DB_PATH
import pytest
from investbrief.data.us_data import USData
from investbrief.data.cn_data import CNData
from investbrief.data.gold_data import GoldData
from investbrief.market.us.provider import USMarketProvider
from investbrief.market.cn.provider import CNMarketProvider
from investbrief.risk.models import RiskModel
from investbrief.risk.config import load_indicators
from investbrief.risk.render import render_risk_card, render_gold_section, _fmt_num
from investbrief.pipelines.macro import _build_indicators


def _db_ready():
    if not os.path.exists(DB_PATH):
        return False
    try:
        ds = USData()
        n = ds.query("SELECT COUNT(*) AS n FROM us_index_daily").iloc[0]["n"]
        ds.close()
        return n > 100
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_ready(), reason="needs P1-P3-populated DB")


def _build_model(market_code, data_source):
    """按市场装配 indicators 并注入 RiskModel —— 复用 pipeline 生产路径。"""
    config = load_indicators(market_code)
    indicators = _build_indicators(market_code, data_source, config)
    return RiskModel(data_source, indicators=indicators)


def test_three_market_risk_cards_render():
    rc = {"color_up": "#e74c3c", "color_down": "#27ae60"}
    us = USMarketProvider(data=USData())
    cn = CNMarketProvider(data=CNData())
    gold_data = GoldData()
    risk = {}
    for m, data_source in (("us", us.data), ("cn", cn.data), ("gold", gold_data)):
        model = _build_model(m, data_source)
        risk[m] = model.calculate_score(m)

    us_html = us.render_section(us.fetch_all(), rc, risk_html=render_risk_card(risk["us"]))
    cn_html = cn.render_section(cn.fetch_all(), rc, risk_html=render_risk_card(risk["cn"]))
    gold_html = render_gold_section(risk["gold"])
    combined = us_html + cn_html + gold_html

    # Each market's score + state appears
    # 用 render 的 _fmt_num 格式化(整数浮点 46.0 → "46", 与卡片显示一致),
    # 避免 str(46.0)="46.0" 与渲染 "46" 不匹配的边界问题。
    for m in ("us", "cn", "gold"):
        assert _fmt_num(risk[m]["total_score"]) in combined
        assert risk[m]["state"] in combined
    # Gold section header present
    assert "黄金" in gold_html
    # Each of the three cards renders its risk-card headline
    assert combined.count("📈 周期风险") >= 3

    us.data.close()
    cn.data.close()
    gold_data.close()
