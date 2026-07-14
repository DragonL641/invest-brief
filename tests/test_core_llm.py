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
    """[1m] 等 context 标记被 strip 后用底下的干净模型名（与 run.py bootstrap 的 re.sub 一致，非整体回退）。

    Regression: holdings/brief.py 等曾直读 env 绕过过滤，把 glm-5.2[1m] 原样发给 GLM 被
    'model not found' 拒。default_model() 现在 strip 所有 [..] 标记后用干净名（run.py
    bootstrap 已清洗 env，此处作防御深度）。
    """
    monkeypatch.setenv("ANTHROPIC_DEFAULT_SONNET_MODEL", "glm-5.2[1m]")
    assert default_model() == "glm-5.2"


def test_default_model_falls_back_when_only_marker(monkeypatch):
    """env 仅含标记（strip 后为空）→ 回退 fallback。"""
    monkeypatch.setenv("ANTHROPIC_DEFAULT_SONNET_MODEL", "[1m]")
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


# --- missing API key diagnosis tests ---
def test_call_claude_missing_key_returns_none(monkeypatch, caplog):
    """When neither ANTHROPIC_API_KEY nor ANTHROPIC_AUTH_TOKEN is set, call_claude
    must log a clear diagnosis and return None (not silently build a None-key client)."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    with caplog.at_level("ERROR", logger="investbrief.core.llm"):
        result = call_claude([{"role": "user", "content": "hi"}], max_tokens=100)
    assert result is None
    # get_client must not even be touched when the key is missing
    assert any("ANTHROPIC_API_KEY" in rec.message for rec in caplog.records)
