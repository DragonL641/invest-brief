from unittest.mock import MagicMock

from investbrief.market.overseas import compute_erp_valuation, render_overseas_card


def _ds(erp: float | None = -1.07, pe: float | None = 32.0, pct: float | None = 35.0):
    ds = MagicMock()
    ds.latest_macro.side_effect = lambda ind, c: {
        ("ERP", "us"): erp, ("SHILLER_PE", "us"): pe,
    }.get((ind, c))
    ds.latest_percentile.return_value = pct
    return ds


def test_compute_erp_valuation_signal_buckets():
    # ERP -1.07 → 偏贵（>−3）
    v = compute_erp_valuation(_ds(erp=-1.07))
    assert v is not None
    assert v["erp"] == -1.07
    assert v["shiller_pe"] == 32.0
    assert v["pct_10y"] == 35.0
    assert v["signal"] == "偏贵"
    assert compute_erp_valuation(_ds(erp=5.0))["signal"] == "便宜"
    assert compute_erp_valuation(_ds(erp=1.0))["signal"] == "中性"
    assert compute_erp_valuation(_ds(erp=-4.0))["signal"] == "极贵"


def test_compute_erp_valuation_none_when_missing():
    assert compute_erp_valuation(_ds(erp=None, pe=None, pct=None)) is None


def test_render_overseas_card_with_erp():
    data = {"fed_rate": 5.25, "erp": compute_erp_valuation(_ds())}
    html = render_overseas_card(data)
    assert "股权风险溢价" in html
    assert "偏贵" in html
    assert "CAPE" in html
    assert "近10年" in html


def test_render_overseas_card_without_erp_degrades():
    data = {"fed_rate": 5.25}  # 无 erp
    html = render_overseas_card(data)
    assert "股权风险溢价" not in html
    assert "美联储利率" in html  # 其它 cell 照常


def test_compute_erp_valuation_threshold_boundaries():
    # 严格 > 边界：4.0 不 >4 → 中性；0.0 不 >0 → 偏贵；-3.0 不 >-3 → 极贵
    v = compute_erp_valuation(_ds(erp=4.0))
    assert v is not None and v["signal"] == "中性"
    v = compute_erp_valuation(_ds(erp=0.0))
    assert v is not None and v["signal"] == "偏贵"
    v = compute_erp_valuation(_ds(erp=-3.0))
    assert v is not None and v["signal"] == "极贵"


def test_render_overseas_card_erp_pct_none():
    # pct=None → sub 只显 CAPE，无"近10年"
    data = {"fed_rate": 5.25, "erp": compute_erp_valuation(_ds(pct=None))}
    html = render_overseas_card(data)
    assert "股权风险溢价" in html
    assert "近10年" not in html
    assert "CAPE" in html
