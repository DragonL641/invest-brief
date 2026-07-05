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


# --- call_claude wrapper tests ---
from unittest.mock import patch, MagicMock

from investbrief.core import llm as llm_mod
from investbrief.core.llm import call_claude


@patch("investbrief.core.llm.time.sleep")  # skip real backoff sleeps
def test_call_claude_retries_rate_limit_then_succeeds(mock_sleep):
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [
        Exception("429 Too Many Requests"),
        MagicMock(content=[MagicMock(text="ok")]),
    ]
    with patch.object(llm_mod, "get_client", return_value=mock_client):
        result = call_claude([{"role": "user", "content": "hi"}], max_tokens=100)
    assert result == "ok"
    assert mock_client.messages.create.call_count == 2  # 1 fail + 1 success


@patch("investbrief.core.llm.time.sleep")
def test_call_claude_auth_error_not_retried(mock_sleep):
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = Exception("401 Unauthorized")
    with patch.object(llm_mod, "get_client", return_value=mock_client):
        result = call_claude([{"role": "user", "content": "hi"}], max_tokens=100)
    assert result is None
    assert mock_client.messages.create.call_count == 1  # not retried


@patch("investbrief.core.llm.time.sleep")
def test_call_claude_unknown_error_not_retried(mock_sleep):
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = RuntimeError("something weird")
    with patch.object(llm_mod, "get_client", return_value=mock_client):
        result = call_claude([{"role": "user", "content": "hi"}], max_tokens=100)
    assert result is None
    assert mock_client.messages.create.call_count == 1


def test_call_claude_success_returns_stripped_text():
    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(content=[MagicMock(text="  hello  ")])
    with patch.object(llm_mod, "get_client", return_value=mock_client):
        result = call_claude([{"role": "user", "content": "hi"}], max_tokens=100)
    assert result == "hello"
    assert mock_client.messages.create.call_count == 1
