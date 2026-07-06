"""US indicator 工厂: 产出 valuation/technical/liquidity/sentiment/macro, 不 import risk。"""
import ast
from pathlib import Path


def test_us_indicators_factory_returns_list():
    from investbrief.market.us.indicators import us_indicators
    from investbrief.data.us_data import USData
    data = USData()
    try:
        inds = us_indicators(data, config={
            "index_pe": {}, "sp500_erp": {},
            "ma50_deviation": {"thresholds": {"us": 20}, "low_thresholds": {"us": 0}},
            "volume_shrinkage": {"thresholds": {"us": 0.7}},
            "credit_spread": {}, "vix": {}, "yield_curve_inversion": {},
        })
        assert isinstance(inds, list) and len(inds) >= 4
    finally:
        data.close()


def test_us_indicators_does_not_import_risk():
    """域边界: market/us/indicators.py 不得 import investbrief.risk。"""
    src = Path("investbrief/market/us/indicators.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                assert not n.name.startswith("investbrief.risk"), f"禁止 import {n.name}"
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("investbrief.risk"), f"禁止 from {node.module}"
