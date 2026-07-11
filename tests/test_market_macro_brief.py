"""Smoke for market.macro_brief public API."""
from investbrief.market.macro_brief import (
    generate_macro_brief, serialize_macro_context, MACRO_BRIEF_PROMPT,
)


def test_public_api_present():
    assert callable(generate_macro_brief)
    assert callable(serialize_macro_context)
    assert "你是资深宏观经济分析师" in MACRO_BRIEF_PROMPT


def test_serialize_handles_empty():
    out = serialize_macro_context({}, {}, [])
    assert isinstance(out, str)


def test_generate_macro_brief_parses_fenced_json(monkeypatch):
    """Regression: markdown-fenced JSON must still parse after the call_claude migration.

    Previously macro_brief called get_client + json.loads directly; now it goes
    through call_claude (mocked here to return fenced JSON) + extract_json.
    """
    from investbrief.core import llm as llm_mod
    from investbrief.market import macro_brief

    fenced = (
        "```json\n"
        '{"summary": "<p>test summary</p>", "risk": "<p>test risk</p>"}\n'
        "```"
    )
    monkeypatch.setattr(llm_mod, "call_claude", lambda *a, **kw: fenced)

    summary, risk = macro_brief.generate_macro_brief({}, {}, [])
    assert "test summary" in summary
    assert "test risk" in risk


def test_serialize_macro_context_budget_truncates_low_priority():
    """Tight max_chars drops regime/risk (priority 4/3) before news (priority 2)."""
    news = [{"title": f"headline {i}", "source": "src"} for i in range(5)]
    risk = {"cn": {"total_score": 50, "state": "温和常态", "action": "持有"}}
    regime = {"cn": {"quadrant": "复苏", "confidence": 70, "growth_axis": "上行", "inflation_axis": "温和"}}
    out = serialize_macro_context({"美联储利率": 5.25, "美债10Y": 4.56},
                                  {"monetary_policy": {"rate": "3%"}},
                                  news, risk_scores=risk, regime_data=regime,
                                  max_chars=400)
    assert "外围环境" in out  # core always present
    assert "宏观环境四象限" not in out  # priority 4 dropped first


def test_serialize_macro_context_large_budget_keeps_everything():
    news = [{"title": "h", "source": "s"}]
    risk = {"cn": {"total_score": 50, "state": "温和常态", "action": "持有"}}
    regime = {"cn": {"quadrant": "复苏", "confidence": 70, "growth_axis": "上行", "inflation_axis": "温和"}}
    out = serialize_macro_context({}, {}, news, risk_scores=risk, regime_data=regime,
                                  max_chars=8000)
    assert "重要新闻" in out
    assert "市场周期风险分" in out
    assert "宏观环境四象限" in out
