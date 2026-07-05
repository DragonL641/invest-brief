# tests/test_picks_brief.py
"""picks.brief: 6 只 Top1 的 Claude 综合研判(mock call_claude)。"""
from investbrief.picks import brief


def _pick(profile, market, symbol):
    return {"symbol": symbol, "name": symbol, "market": market, "profile": profile,
            "composite": 80.0, "rank": 1, "factor_scores": {}, "triggers": [],
            "price": 10.0, "key_mas": {}, "stop_level": 9.0, "data_time": "t"}


def test_generate_picks_brief_returns_html(monkeypatch):
    monkeypatch.setattr(brief, "call_claude", lambda *a, **k: "综合研判正文")
    html = brief.generate_picks_brief([_pick("swing", "cn", "s1"),
                                        _pick("swing", "us", "s2")])
    assert "综合研判正文" in html


def test_generate_picks_brief_fallback_on_none(monkeypatch):
    monkeypatch.setattr(brief, "call_claude", lambda *a, **k: None)
    html = brief.generate_picks_brief([_pick("swing", "cn", "s1")])
    assert "暂无" in html or "研判" in html


def test_generate_picks_brief_empty_picks():
    assert brief.generate_picks_brief([]) == ""


def test_serialize_picks_context_compact():
    s = brief.serialize_picks_context([_pick("swing", "cn", "s1")])
    assert "s1" in s and "swing" in s
