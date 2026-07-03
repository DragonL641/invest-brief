"""P4 渲染管线：真实 DB → 三市场风险卡 → market_section_html 含全部卡片。"""
import os
from investbrief.core.config import DB_PATH
import pytest
from investbrief.data.us_data import USData
from investbrief.data.cn_data import CNData
from investbrief.market.us.provider import USMarketProvider
from investbrief.market.cn.provider import CNMarketProvider
from investbrief.risk.models import RiskModel
from investbrief.risk.render import render_risk_card, render_gold_section


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


def test_three_market_risk_cards_render():
    rc = {"color_up": "#e74c3c", "color_down": "#27ae60"}
    us = USMarketProvider(data=USData())
    cn = CNMarketProvider(data=CNData())
    model = RiskModel(us.data)
    risk = {m: model.calculate_score(m) for m in ("us", "cn", "gold")}

    us_html = us.render_section(us.fetch_all(), rc, risk_html=render_risk_card(risk["us"]))
    cn_html = cn.render_section(cn.fetch_all(), rc, risk_html=render_risk_card(risk["cn"]))
    gold_html = render_gold_section(risk["gold"])
    combined = us_html + cn_html + gold_html

    # Each market's score + state appears
    for m in ("us", "cn", "gold"):
        assert str(risk[m]["total_score"]) in combined
        assert risk[m]["state"] in combined
    # Gold section header present
    assert "黄金" in gold_html
    # Each of the three cards renders its risk-card headline
    assert combined.count("📈 周期风险") >= 3

    us.data.close()
    cn.data.close()
