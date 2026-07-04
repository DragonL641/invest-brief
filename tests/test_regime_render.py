"""render_regime_card 渲染单测(纯函数,无 DB)。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from investbrief.regime.render import render_regime_card


def _data(quadrant="繁荣", confidence=75, growth="扩张", inflation="下行",
          gdp_yoy=4.2, cpi=2.1, market="us"):
    return {
        "quadrant": quadrant,
        "confidence": confidence,
        "growth_axis": growth,
        "inflation_axis": inflation,
        "indicators": {"GDP_YOY": gdp_yoy, "CPI_LATEST": cpi},
        "market": market,
    }


def test_empty_returns_blank():
    assert render_regime_card({}) == ""
    assert render_regime_card(None) == ""


def test_empty_quadrant_returns_blank():
    assert render_regime_card({"quadrant": None}) == ""


def test_card_has_matrix_labels_and_quadrants():
    html = render_regime_card(_data())
    # 列/行标签
    assert "通胀 ↓" in html and "通胀 ↑" in html
    assert "增长 ↑" in html and "增长 ↓" in html
    # 四个象限名都出现
    for q in ("繁荣", "通胀", "通缩", "滞胀"):
        assert q in html
    # 占优资产
    assert "股票" in html and "商品" in html and "债券" in html and "现金" in html


def test_current_quadrant_highlighted_with_star():
    html = render_regime_card(_data(quadrant="滞胀"))
    # 当前象限带 ★,且高亮样式(主题蓝)
    assert "滞胀 ★" in html
    assert "#2980b9" in html  # 当前格边框色


def test_confidence_and_indicators_shown():
    html = render_regime_card(_data(confidence=72, gdp_yoy=4.2, cpi=2.1))
    assert "置信度 72%" in html
    assert "GDP同比" in html and "4.2" in html
    assert "CPI同比" in html and "2.1" in html


def test_neutral_quadrant_no_star_on_others():
    # 中性时,任一非中性象限都不该带 ★
    html = render_regime_card(_data(quadrant="中性"))
    assert "★" not in html


def test_does_not_use_price_colors():
    # 配色不使用涨跌红绿,避免和 P4 风险色冲突
    html = render_regime_card(_data())
    # 当前格用主题蓝(#2980b9),不用红(#e74c3c)/绿(#27ae60)作为高亮
    assert "background:#e8f4f8" in html  # 浅蓝底
