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
    """Regression: markdown-fence stripping (re.sub) must not NameError.

    Module imports 're' at module level but the move from run.py left '_re.sub'
    call sites, raising NameError inside the broad except — Claude synthesis
    silently fell back to the placeholder every run.
    """
    from investbrief.market import macro_brief

    fenced = (
        "```json\n"
        '{"summary": "<p>test summary</p>", "risk": "<p>test risk</p>"}\n'
        "```"
    )

    class _Block:
        def __init__(self, text):
            self.text = text

    class _Resp:
        def __init__(self, text):
            self.content = [_Block(text)]

    class _Messages:
        @staticmethod
        def create(**kwargs):
            return _Resp(fenced)

    class _Client:
        def __init__(self):
            self.messages = _Messages()

    monkeypatch.setattr(macro_brief, "get_client", lambda: _Client())

    summary, risk = macro_brief.generate_macro_brief({}, {}, [])
    assert "test summary" in summary
    assert "test risk" in risk
