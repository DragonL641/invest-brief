"""关键信号 tag 选取规则。"""
from investbrief.holdings.analyzer import HoldingResult
from investbrief.holdings.renderer import _pick_key_signals


def test_insider_sell_signal():
    r = HoldingResult(symbol="002371", market="cn", type="stock",
                      insider={"direction": "sell", "net_amount": -800000})
    sigs = _pick_key_signals(r)
    labels = [s["label"] for s in sigs]
    assert any("减持" in l for l in labels)
    assert sigs[0]["cls"] == "down"


def test_rsi_overbought_signal():
    r = HoldingResult(symbol="600519", market="cn", type="stock",
                      technicals={"rsi": 75})
    sigs = _pick_key_signals(r)
    assert any("超买" in s["label"] for s in sigs)
    assert sigs[0]["cls"] == "down"


def test_signals_capped_at_three():
    r = HoldingResult(symbol="600519", market="cn", type="stock",
                      technicals={"rsi": 75, "macd_cross": "golden"},
                      insider={"direction": "buy", "net_amount": 100},
                      events={"days_to_next": 3, "next_earnings": "2026-07-10"})
    sigs = _pick_key_signals(r)
    assert len(sigs) <= 3


def test_priority_insider_over_rsi():
    """减持 (priority 1) 排在 RSI超买 (priority 3) 之前。"""
    r = HoldingResult(symbol="002371", market="cn", type="stock",
                      insider={"direction": "sell", "net_amount": -100},
                      technicals={"rsi": 75})
    sigs = _pick_key_signals(r)
    assert "减持" in sigs[0]["label"]


def test_empty_when_no_signals():
    r = HoldingResult(symbol="600519", market="cn", type="stock")
    assert _pick_key_signals(r) == []


def test_dragon_tiger_signal_cn():
    r = HoldingResult(symbol="002371", market="cn", type="stock",
                      cn_activity={"dragon_tiger_count": 2})
    sigs = _pick_key_signals(r)
    assert any("龙虎榜" in s["label"] for s in sigs)


def test_cn_rating_action_signal():
    """CN rating action：研报评级文本含「买入」→ up 信号。"""
    r = HoldingResult(symbol="600519", market="cn", type="stock",
                      rating={"actions": [{"institution": "中信", "rating": "买入", "date": "2026-07-01"}]})
    sigs = _pick_key_signals(r)
    assert any("评级" in s["label"] for s in sigs)
    assert sigs[0]["cls"] == "up"
