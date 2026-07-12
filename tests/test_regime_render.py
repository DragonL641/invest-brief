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
    # 当前象限带 ★(regime-star span),高亮用 regime-cell-current class(色在 styles.css)
    assert "滞胀" in html
    assert "regime-star" in html
    assert "regime-cell-current" in html


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
    # 配色不使用涨跌红绿,避免和 P4 风险色冲突(全 class 化,HTML 无涨跌色 inline)
    html = render_regime_card(_data())
    assert "regime-cell-current" in html   # 当前格高亮 class(强调色在 styles.css)
    for c in ("#e74c3c", "#27ae60", "#c0392b", "#2d8659"):
        assert c not in html


def test_cn_credit_axis_shown_when_present():
    """CN 卡片显示信用轴(M2 + 社融);US 不显示。"""
    cn_data = _data(market="cn")
    cn_data["credit_axis"] = "扩张"
    cn_data["indicators"]["M2_YOY"] = 8.6
    html = render_regime_card(cn_data)
    assert "信用扩张" in html
    assert "M2同比" in html


def test_us_credit_axis_omitted():
    """US 卡片不显示信用轴(credit_axis=None)。"""
    html = render_regime_card(_data(market="us"))
    assert "信用" not in html
    assert "M2同比" not in html
