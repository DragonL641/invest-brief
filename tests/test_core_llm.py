"""Tests for core.llm.default_model — the [1m] suffix filter contract.

Regression: holdings/brief.py and holdings/etf/analyzer.py used to read
ANTHROPIC_DEFAULT_SONNET_MODEL directly, bypassing this filter, so a value
like 'glm-5.2[1m]' (leaked by the Claude Code runtime into the env) was
sent verbatim to GLM and rejected as 'model not found'. All Claude call
sites MUST go through default_model() — this test guards the filter.
"""
from investbrief.core.llm import default_model

FALLBACK = "claude-sonnet-4-5-20250929"


def test_default_model_filters_1m_suffix(monkeypatch):
    """A [1m]-suffixed env value must fall back, not pass through."""
    monkeypatch.setenv("ANTHROPIC_DEFAULT_SONNET_MODEL", "glm-5.2[1m]")
    assert default_model() == FALLBACK


def test_default_model_passes_through_clean_env(monkeypatch):
    """A clean (no [1m]) env value is used as-is."""
    monkeypatch.setenv("ANTHROPIC_DEFAULT_SONNET_MODEL", "my-valid-model")
    assert default_model() == "my-valid-model"


def test_default_model_fallback_when_env_unset(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_DEFAULT_SONNET_MODEL", raising=False)
    assert default_model() == FALLBACK
