from unittest.mock import MagicMock

from investbrief.market.gold.valuation import fetch_gold_valuation, render_gold_valuation_card


def _ds(tips: float | None = 2.35, tips_pct: float | None = 30.0,
        aisc: float | None = 1706.23, aisc_pct: float | None = 100.0,
        gold: float | None = 3500.0):
    ds = MagicMock()
    ds.latest_macro.side_effect = lambda ind, c: {
        ("REAL_YIELD_10Y", "us"): tips,
        ("GOLD_AISC", "global"): aisc,
        ("GOLD_PRICE", "global"): gold,
    }.get((ind, c))
    ds.latest_percentile.side_effect = lambda ind, c, y: {
        ("REAL_YIELD_10Y", "us"): tips_pct,
        ("GOLD_AISC", "global"): aisc_pct,
    }.get((ind, c))
    return ds


def test_fetch_gold_valuation_full():
    v = fetch_gold_valuation(_ds(), {})
    assert v["tips_yield"] == 2.35
    assert v["tips_pct_10y"] == 30.0
    assert v["aisc"] == 1706.23
    assert v["aisc_pct_14y"] == 100.0
    assert v["gold_price"] == 3500.0
    # 3500/1706.23 - 1 = 1.051 → 105.1%
    assert v["premium_pct"] == 105.1


def test_fetch_gold_valuation_aisc_none():
    v = fetch_gold_valuation(_ds(aisc=None, aisc_pct=None), {})
    assert v["aisc"] is None
    assert v["premium_pct"] is None
    assert v["tips_yield"] == 2.35  # TIPS 独立


def test_render_card_full():
    v = fetch_gold_valuation(_ds(), {})
    html = render_gold_valuation_card(v)
    assert "黄金估值信号" in html
    assert "2.35" in html
    assert "30.0" in html  # TIPS 分位
    assert "1,706" in html   # AISC 千分位
    assert "105.1" in html  # 溢价


def test_render_card_aisc_missing_skips_premium_row():
    v = fetch_gold_valuation(_ds(aisc=None, aisc_pct=None), {})
    html = render_gold_valuation_card(v)
    assert "2.35" in html          # TIPS 行在
    assert "开采成本" not in html   # AISC 行不渲染
    assert "溢价" not in html


def test_render_card_all_missing_returns_empty():
    v = fetch_gold_valuation(_ds(tips=None, tips_pct=None, aisc=None, aisc_pct=None, gold=None), {})
    assert render_gold_valuation_card(v) == ""


def test_fetch_gold_valuation_aisc_zero_no_premium():
    # aisc=0 防除零 → premium None（aisc 本身仍读出为 0.0）
    v = fetch_gold_valuation(_ds(aisc=0.0, aisc_pct=50.0), {})
    assert v["aisc"] == 0.0
    assert v["premium_pct"] is None  # 除零守卫


def test_render_card_tips_pct_none():
    # tips 有值但 tips_pct=None → TIPS 行渲染，explain 空
    v = fetch_gold_valuation(_ds(tips_pct=None), {})
    html = render_gold_valuation_card(v)
    assert "2.35" in html
    assert "近10年" not in html  # pct None → explain 空


def test_render_card_gold_none_skips_aisc_row():
    # aisc 有但 gold=None → has_aisc False（需 gold+aisc 都有），AISC 行不渲染
    v = fetch_gold_valuation(_ds(gold=None), {})
    html = render_gold_valuation_card(v)
    assert "2.35" in html          # TIPS 行在
    assert "开采成本" not in html   # AISC 行不渲染（gold 缺）
