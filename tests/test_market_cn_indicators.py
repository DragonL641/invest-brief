"""CN indicator 工厂: 产出 valuation/technical/liquidity, 不 import risk。"""
import ast
from pathlib import Path


def test_cn_indicators_factory_returns_list():
    from investbrief.market.cn.indicators import cn_indicators
    from investbrief.data.cn_data import CNData
    data = CNData()
    try:
        inds = cn_indicators(data, config={
            "broad_erp": {}, "structural_divergence": {}, "index_pe": {},
            "ma50_deviation": {"thresholds": {"cn": 20}, "low_thresholds": {"cn": 0}},
            "volume_shrinkage": {"thresholds": {"cn": 0.7}},
            "margin_growth": {}, "margin_level": {},
        })
        assert isinstance(inds, list) and len(inds) >= 3
        from investbrief.market.cn.indicators import CnMacroIndicator
        assert any(isinstance(i, CnMacroIndicator) for i in inds), "应含 CnMacroIndicator(宏观基本面维度)"
    finally:
        data.close()


def test_cn_indicators_does_not_import_risk():
    """域边界: market/cn/indicators.py 不得 import investbrief.risk。"""
    src = Path("investbrief/market/cn/indicators.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                assert not n.name.startswith("investbrief.risk"), f"禁止 import {n.name}"
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("investbrief.risk"), f"禁止 from {node.module}"
