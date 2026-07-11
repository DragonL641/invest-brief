from investbrief.risk.config import CN_ALL_INDICATORS
from investbrief.risk.render import (
    _fmt_value,
    _fmt_num,
    _risk_color,
    render_risk_card,
    render_gold_section,
)


def _score(total, dims, indicators=None, market="cn"):
    return {
        "total_score": total, "state": "测试状态", "crash_prob": "N/A",
        "expected_return": "N/A", "action": "测试操作",
        "market": market,
        "dimensions": dims,
        "indicators": indicators or {},
    }


def test_risk_color_thresholds():
    assert _risk_color(85) == "#c0392b"
    assert _risk_color(60) == "#e74c3c"
    assert _risk_color(80) == "#c0392b"
    assert _risk_color(45) == "#f39c12"
    assert _risk_color(30) == "#27ae60"
    assert _risk_color(10) == "#16a085"


def test_fmt_value_applies_scale_and_unit():
    assert _fmt_value(0.05, 100, "%") == "5.00%"
    assert _fmt_value(28.0, 1, "") == "28.00"
    assert _fmt_value(None, 1, "") == "-"
    assert _fmt_value("N/A", 1, "%") == "-"


def test_fmt_num_strips_trailing_zeros():
    assert _fmt_num(8.0) == "8"
    assert _fmt_num(7.85) == "7.85"
    assert _fmt_num(8.5) == "8.5"
    assert _fmt_num(62.40) == "62.4"
    assert _fmt_num(None) == "-"


def test_render_risk_card_structure():
    s = _score(
        62.4,
        {"估值风险": 7.85, "技术面风险": 1.36},
        {"broad_erp": {"score": 9.5, "value": 1.5}},
    )
    html = render_risk_card(s)
    assert "62.4" in html  # total score rendered (no trailing zero)
    assert "测试状态" in html and "测试操作" in html
    # readable name shown instead of cryptic key
    assert CN_ALL_INDICATORS["broad_erp"]["name"] in html
    # value rendered with 2 decimals (broad_erp scale=1 unit=% → 1.50%)
    assert "1.50" in html
    # value→score relationship markers
    assert "→" in html
    assert "/10" in html
    # key no longer leaks to card surface
    assert "broad_erp " not in html
    # dimension bars removed
    assert "估值风险" not in html
    assert "技术面风险" not in html


def test_render_risk_card_skips_missing_value_indicators():
    # indicators with value=None are not rendered; those with a value are
    s = _score(50.0, {"估值风险": 5.0}, {
        "has_val": {"score": 5.0, "value": 12.0},
        "no_val": {"score": 5.0, "value": None},
    })
    html = render_risk_card(s)
    assert "has_val" in html  # fallback name = key
    assert "12.00" in html  # fallback scale=1 unit="" still formats value
    assert "no_val" not in html


def test_render_risk_card_indicator_shows_explain_algo_warning_pct():
    s = _score(
        70.0,
        {},
        {"broad_erp": {"score": 9.5, "value": 1.5, "percentile": 95.0}},
        market="cn",
    )
    html = render_risk_card(s)
    meta = CN_ALL_INDICATORS["broad_erp"]
    assert meta["explain"] in html            # explain text
    assert meta["description"] in html        # algorithm basis
    assert "算法" in html
    # 警戒: cn threshold = 1.5, scale=1, unit="%" → 1.50%
    assert "警戒" in html
    assert "1.50" in html
    # 历史分位: pct=95 → 高位 + 95%
    assert "历史" in html
    assert "高位" in html
    assert "95%" in html


def test_render_risk_card_sorted_by_score_desc():
    s = _score(
        50.0,
        {},
        {
            "broad_erp": {"score": 9.5, "value": 1.5},        # highest
            "market_breadth": {"score": 2.0, "value": 0.5},   # lowest
            "margin_growth": {"score": 6.0, "value": 0.1},    # middle
        },
        market="cn",
    )
    html = render_risk_card(s)
    name_high = CN_ALL_INDICATORS["broad_erp"]["name"]
    name_mid = CN_ALL_INDICATORS["margin_growth"]["name"]
    name_low = CN_ALL_INDICATORS["market_breadth"]["name"]
    # indices must appear in descending-score order
    assert html.index(name_high) < html.index(name_mid) < html.index(name_low)


def test_render_risk_card_empty_returns_blank():
    assert render_risk_card({}) == ""
    assert render_risk_card(None) == ""


def test_render_gold_section_wraps_with_header():
    s = _score(69.0, {"估值风险": 9.7}, market="gold")
    html = render_gold_section(s)
    assert "黄金" in html
    assert "69" in html  # card inside
    assert "<div" in html and "</div>" in html


def test_render_gold_section_empty_returns_blank():
    assert render_gold_section({}) == ""
