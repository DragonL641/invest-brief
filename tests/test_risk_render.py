from investbrief.risk.config import US_ALL_INDICATORS
from investbrief.risk.render import (
    _fmt_value,
    _fmt_num,
    _risk_color,
    render_risk_card,
    render_gold_section,
)


def _score(total, dims, indicators=None):
    return {
        "total_score": total, "state": "测试状态", "crash_prob": "N/A",
        "expected_return": "N/A", "action": "测试操作",
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
        {"index_pe": {"score": 9.5, "value": 28.0}},
    )
    html = render_risk_card(s)
    assert "62.4" in html  # total score rendered (no trailing zero)
    assert "测试状态" in html and "测试操作" in html
    assert "估值风险" in html and "技术面风险" in html
    # readable name shown instead of cryptic key
    assert US_ALL_INDICATORS["index_pe"]["name"] in html
    # value rendered with 2 decimals (scale=1, unit="")
    assert "28.00" in html
    # value→score relationship markers
    assert "→" in html
    assert "/10" in html
    # key no longer leaks to card surface
    assert "index_pe " not in html


def test_render_risk_card_indicator_value_and_score_shown():
    s = _score(
        50.0,
        {"估值风险": 5.0},
        {
            "index_pe": {
                "score": 9.5,
                "value": 28.0,
                "scoring": "全历史分位(180点)",
            },
            "ma50_deviation": {
                "score": 6.0,
                "value": 0.05,
                "scoring": "近10年分位(200点)",
            },
        },
    )
    html = render_risk_card(s)
    # readable names
    assert US_ALL_INDICATORS["index_pe"]["name"] in html
    assert "50日均线偏离度" in html
    # value with unit (index_pe scale=1 unit="" → 28.00; ma50 scale=100 unit=% → 5.00%)
    assert "28.00" in html
    assert "5.00%" in html
    # score
    assert "9.5/10" in html
    assert "6/10" in html
    # scoring basis
    assert "全历史分位(180点)" in html
    assert "近10年分位(200点)" in html
    # relationship arrow
    assert "→" in html


def test_render_risk_card_skips_empty_dimensions():
    # gold-like: only 估值/技术 present, others absent
    s = _score(69.0, {"估值风险": 9.7, "技术面风险": 0.0})
    html = render_risk_card(s)
    assert "估值风险" in html
    assert "流动性风险" not in html  # absent dim not rendered
    assert "情绪面风险" not in html


def test_render_risk_card_empty_returns_blank():
    assert render_risk_card({}) == ""
    assert render_risk_card(None) == ""


def test_render_risk_card_skips_indicators_without_value():
    # has_val is not a registered indicator → falls back to name=key, scale=1, unit=""
    s = _score(50.0, {"估值风险": 5.0}, {
        "has_val": {"score": 5.0, "value": 12.0},
        "no_val": {"score": 5.0, "value": None},
    })
    html = render_risk_card(s)
    assert "has_val" in html  # fallback name = key
    assert "12.00" in html  # fallback scale=1 unit="" still formats value
    assert "no_val" not in html


def test_render_gold_section_wraps_with_header():
    s = _score(69.0, {"估值风险": 9.7})
    html = render_gold_section(s)
    assert "黄金" in html
    assert "69" in html  # card inside
    assert "<div" in html and "</div>" in html


def test_render_gold_section_empty_returns_blank():
    assert render_gold_section({}) == ""
