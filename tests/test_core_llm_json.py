"""LLM JSON output extraction — triple-fallback tolerance."""
import pytest

from investbrief.core.llm_json import extract_json


def test_extract_json_plain():
    assert extract_json('{"summary": "x", "risk": "y"}') == {"summary": "x", "risk": "y"}


def test_extract_json_fenced():
    text = '```json\n{"summary": "x", "risk": "y"}\n```'
    assert extract_json(text) == {"summary": "x", "risk": "y"}


def test_extract_json_fenced_no_lang():
    text = '```\n{"summary": "x"}\n```'
    assert extract_json(text) == {"summary": "x"}


def test_extract_json_trailing_text():
    # LLM sometimes appends prose after the JSON object
    text = '{"summary": "x", "risk": "y"}\n以上是今日宏观分析。'
    assert extract_json(text) == {"summary": "x", "risk": "y"}


def test_extract_json_python_style_bool():
    # json_repair fixes True/False (Python) → true/false. (Note: bare None is NOT
    # fixed by json_repair — it becomes the string "None" — so we don't test it
    # here. macro_brief's actual output is string fields, so None never appears.)
    text = '{"summary": "x", "flag": True, "other": False}'
    result = extract_json(text)
    assert result["summary"] == "x"
    assert result["flag"] is True
    assert result["other"] is False


def test_extract_json_empty_raises():
    with pytest.raises(ValueError):
        extract_json("")
    with pytest.raises(ValueError):
        extract_json("   ")


def test_extract_json_non_json_raises():
    with pytest.raises(ValueError):
        extract_json("not json at all, just prose")
