from investbrief.risk.render import _risk_color, render_risk_card, render_gold_section


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


def test_render_risk_card_structure():
    s = _score(62.4, {"估值风险": 7.85, "技术面风险": 1.36}, {"index_pe": {"score": 9.5, "value": 28.0}})
    html = render_risk_card(s)
    assert "62" in html and "62.4" in html  # score rendered
    assert "测试状态" in html and "测试操作" in html
    assert "估值风险" in html and "技术面风险" in html
    assert "index_pe" in html  # indicator with value shown


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
    s = _score(50.0, {"估值风险": 5.0}, {
        "has_val": {"score": 5.0, "value": 12.0},
        "no_val": {"score": 5.0, "value": None},
    })
    html = render_risk_card(s)
    assert "has_val" in html
    assert "no_val" not in html


def test_render_gold_section_wraps_with_header():
    s = _score(69.0, {"估值风险": 9.7})
    html = render_gold_section(s)
    assert "黄金" in html
    assert "69" in html  # card inside
    assert "<div" in html and "</div>" in html


def test_render_gold_section_empty_returns_blank():
    assert render_gold_section({}) == ""
