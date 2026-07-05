"""LLM JSON output extraction with triple-fallback tolerance.

macro_brief asks Claude for {"summary": ..., "risk": ...} as pure JSON, but
GLM-style Anthropic-compatible endpoints occasionally produce:
  - markdown fence wrapping (```json ... ```, even when the prompt says not to)
  - trailing prose after the JSON object
  - Python-style booleans/None (True/False/None instead of true/false/null)
  - single quotes, trailing commas

extract_json handles these via: fence strip → json.loads → raw_decode → json_repair.
"""
import json
import re

try:
    from json_repair import repair_json
    _HAS_JSON_REPAIR = True
except ImportError:
    _HAS_JSON_REPAIR = False


def extract_json(text: str) -> dict:
    """Extract a JSON dict from a tolerant LLM text output.

    Pipeline: strip fence → json.loads → raw_decode (tolerate trailing text)
    → json_repair (tolerate Python-style / single-quote / trailing-comma).
    Returns a dict. Raises ValueError if all stages fail.
    """
    if not text or not text.strip():
        raise ValueError("empty text")
    s = text.strip()

    # 1. Strip markdown fence (```json ... ``` or ``` ... ```)
    m = re.search(r"```(?:json)?\s*\n?(.*?)```", s, re.DOTALL)
    if m:
        s = m.group(1).strip()

    # 2. Direct parse (common path)
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    # 3. raw_decode tolerates trailing prose
    try:
        obj, _ = json.JSONDecoder().raw_decode(s)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    # 4. json_repair handles Python-style / single-quote / trailing-comma drift
    if _HAS_JSON_REPAIR:
        repaired = repair_json(s, return_objects=True)
        if isinstance(repaired, dict):
            return repaired

    raise ValueError(
        f"Could not extract JSON from LLM output (first 120 chars): {s[:120]!r}"
    )
