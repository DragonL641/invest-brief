"""Gold indicator 工厂 + 域边界。"""
import ast
from pathlib import Path


def test_gold_indicators_factory():
    from investbrief.market.gold.indicators import gold_indicators, GoldIndicator
    from investbrief.data.gold_data import GoldData
    data = GoldData()
    try:
        inds = gold_indicators(data, config={})
        assert len(inds) == 1
        assert isinstance(inds[0], GoldIndicator)
    finally:
        data.close()


def test_gold_indicators_does_not_import_risk():
    src = Path("investbrief/market/gold/indicators.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                assert not n.name.startswith("investbrief.risk")
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("investbrief.risk")
