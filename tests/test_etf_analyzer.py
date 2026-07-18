"""ETF analyzer 韧性回归:spot(em)失败不再短路, hist(DB-First)支撑分析。

P1 修复回归:etf/analyzer.py 曾把 get_etf_spot 当硬门禁(spot 挂了直接 return 空壳),
导致 em 封禁时 holdings 邮件的 ETF 标的(3/8)全空。修复后 spot 缺失用 hist 末根收盘
兜底 price/change_pct, 仅当 spot+hist 都缺时 degraded=True(renderer 显式标注)。
"""
import pandas as pd
from unittest.mock import MagicMock

from investbrief.holdings.etf.analyzer import ETFAnalyzer
from investbrief.holdings.etf.engine import RuleEngine


def _mock_etf_analyzer():
    """跳过 __init__(避免建真实 AKShareClient 触网), 手动注入 mock client + engine。"""
    an = ETFAnalyzer.__new__(ETFAnalyzer)
    an.client = MagicMock()
    an.engine = RuleEngine()
    an.client.get_etf_name = lambda s: "沪深300ETF"
    an.client.get_index_valuation = lambda s: None
    return an


def _hist():
    return pd.DataFrame(
        {"open": [4.0, 4.1, 4.2], "high": [4.05, 4.15, 4.25],
         "low": [3.95, 4.05, 4.15], "close": [4.0, 4.1, 4.2],
         "volume": [1000, 1100, 1200]},
        index=pd.to_datetime(["2026-07-15", "2026-07-16", "2026-07-17"]),
    )


def test_analyze_survives_spot_failure(monkeypatch):
    """spot(em)失败时, hist 末根收盘兜底 price, 不再 return 空壳(去硬门禁回归)。"""
    an = _mock_etf_analyzer()
    an.client.get_etf_spot = lambda s: None  # em 封禁 → spot 空(原门禁会 return 空壳)
    monkeypatch.setattr("investbrief.holdings.etf.analyzer.history_db_first",
                        lambda *a, **k: _hist())
    monkeypatch.setattr("investbrief.holdings.etf.analyzer.compute_indicators",
                        lambda h: {})

    r = an.analyze("510300", with_ai=False)

    assert r.degraded is False               # hist 有 → 非 degraded
    assert r.price == 4.2                    # hist 末根收盘兜底
    assert r.change_pct == round((4.2 / 4.1 - 1) * 100, 2)


def test_analyze_degraded_when_spot_and_hist_both_empty(monkeypatch):
    """spot + hist 都缺 → degraded=True(数据源全面不可用, renderer 显式标注)。"""
    an = _mock_etf_analyzer()
    an.client.get_etf_spot = lambda s: None
    monkeypatch.setattr("investbrief.holdings.etf.analyzer.history_db_first",
                        lambda *a, **k: None)

    r = an.analyze("510300", with_ai=False)

    assert r.degraded is True
    assert r.price is None
