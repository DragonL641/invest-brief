"""Anthropic / GLM-style error classification."""
from investbrief.core.llm_errors import classify_anthropic_error


# Custom exception classes that mimic anthropic SDK class names (without needing
# SDK constructors which require response objects). type(exc).__name__ drives
# the SDK-class-name branch of classify.
class RateLimitError(Exception): pass
class APITimeoutError(Exception): pass
class APIConnectionError(Exception): pass
class AuthenticationError(Exception): pass
class BadRequestError(Exception): pass
class InternalServerError(Exception): pass


# --- SDK class-name branch ---
def test_classify_rate_limit_class():
    err = classify_anthropic_error(RateLimitError("x"))
    assert err.code == "rate_limit" and err.retryable

def test_classify_timeout_class():
    err = classify_anthropic_error(APITimeoutError("x"))
    assert err.code == "timeout" and err.retryable

def test_classify_connection_class():
    err = classify_anthropic_error(APIConnectionError("x"))
    assert err.code == "network" and err.retryable

def test_classify_auth_class():
    err = classify_anthropic_error(AuthenticationError("x"))
    assert err.code == "auth" and not err.retryable

def test_classify_badrequest_class():
    err = classify_anthropic_error(BadRequestError("x"))
    assert err.code == "bad_request" and not err.retryable

def test_classify_internal_server_class():
    err = classify_anthropic_error(InternalServerError("x"))
    assert err.code == "server_error" and err.retryable


# --- GLM text-sniff branch (response body may not map to SDK classes) ---
def test_classify_rate_limit_by_text():
    err = classify_anthropic_error(Exception("429 Too Many Requests"))
    assert err.code == "rate_limit" and err.retryable

def test_classify_timeout_by_text():
    err = classify_anthropic_error(Exception("Request timed out"))
    assert err.code == "timeout" and err.retryable

def test_classify_context_window_by_text():
    err = classify_anthropic_error(Exception("context length exceeded, too many input tokens"))
    assert err.code == "context_window" and not err.retryable

def test_classify_auth_by_text():
    err = classify_anthropic_error(Exception("401 Unauthorized: invalid api key"))
    assert err.code == "auth" and not err.retryable

def test_classify_server_error_by_text():
    err = classify_anthropic_error(Exception("503 Service Unavailable"))
    assert err.code == "server_error" and err.retryable

def test_classify_unknown_not_retryable():
    err = classify_anthropic_error(RuntimeError("something completely weird"))
    assert err.code == "unknown" and not err.retryable
