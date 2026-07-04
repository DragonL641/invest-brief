"""brief prompt 包含新维度字段。"""
from investbrief.holdings.analyzer import HoldingResult
from investbrief.holdings.brief import _build_prompt


def test_prompt_includes_insider():
    r = HoldingResult(symbol="002371", market="cn", type="stock", name="北方华创",
                      insider={"direction": "sell", "net_amount": -800000})
    prompt = _build_prompt([r])
    assert "高管" in prompt or "增减持" in prompt or "减持" in prompt


def test_prompt_includes_events():
    r = HoldingResult(symbol="AAPL", market="us", type="stock", name="Apple",
                      events={"next_earnings": "2026-08-01", "days_to_next": 20})
    prompt = _build_prompt([r])
    assert "财报" in prompt or "2026-08-01" in prompt


def test_prompt_includes_cn_activity():
    r = HoldingResult(symbol="002371", market="cn", type="stock", name="北方华创",
                      cn_activity={"dragon_tiger_count": 2, "institution_research_count": 3})
    prompt = _build_prompt([r])
    assert "龙虎榜" in prompt or "机构调研" in prompt


def test_prompt_includes_forecast():
    r = HoldingResult(symbol="AAPL", market="us", type="stock", name="Apple",
                      forecast={"eps_next": 2.1, "yoy_pct": 18.0})
    prompt = _build_prompt([r])
    assert "EPS" in prompt or "盈利" in prompt or "2.1" in prompt
