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
