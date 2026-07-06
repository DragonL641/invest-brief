# tests/test_picks_renderer.py
"""picks.renderer: 卡片/段落 HTML。"""
from investbrief.picks import renderer


def _pick(symbol="000001", composite=85.0):
    return {
        "symbol": symbol, "name": "测试股", "market": "cn", "profile": "swing",
        "composite": composite, "rank": 1,
        "factor_scores": {"trend_strength": {"raw": 0.12, "pct": 90.0, "weighted": 27.0}},
        "triggers": ["trend_strength 处于池内前 10%"],
        "price": 10.5, "key_mas": {"ma20": 10.0, "ma60": 9.5, "ma120": 9.0},
        "stop_level": 9.2, "industry": "银行", "data_time": "2026-07-06 18:00",
    }


def test_render_pick_card_contains_symbol_and_composite():
    html = renderer.render_pick_card(_pick())
    assert "000001" in html
    assert "85.0" in html or "85" in html
    assert "趋势强度" in html          # 中文因子名
    assert "现价" in html and "10.50" in html   # 现价块 + 值


def test_render_pick_card_handles_none_pick():
    """无候选(pick=None)→ 占位卡片。"""
    html = renderer.render_pick_card(None, profile="swing", market="cn")
    assert "无符合条件" in html or "暂无" in html


def test_render_pick_section_wraps_two_cards():
    section = renderer.render_pick_section("swing", _pick("cn1"), _pick("us1", 80.0))
    assert "cn1" in section and "us1" in section
    assert "波段" in section            # 段落标题
