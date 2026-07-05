"""Anthropic / GLM-style endpoint error classification.

The anthropic SDK ships exception classes (RateLimitError / APITimeoutError /
APIConnectionError / BadRequestError / AuthenticationError / InternalServerError ...)
but GLM-style compatible endpoints may emit error bodies that do not map to these
classes. classify_anthropic_error therefore uses BOTH the SDK class name AND the
error message text to decide retryability.
"""
from dataclasses import dataclass


@dataclass
class ClassifiedError:
    code: str       # network/timeout/rate_limit/server_error/context_window/auth/bad_request/unknown
    retryable: bool


def classify_anthropic_error(exc: Exception) -> ClassifiedError:
    """Classify a Claude-call exception. Retryable = network/timeout/rate-limit/5xx.
    Not retryable = auth/4xx/context_window/unknown (retrying won't help).

    Unknown defaults to NOT retryable — avoids wasteful retries on errors we
    don't recognize (caller still gets None and falls back).
    """
    name = type(exc).__name__.lower()
    msg = str(exc).lower()

    # --- SDK class-name branch (most reliable when SDK wraps the error) ---
    if "ratelimit" in name:
        return ClassifiedError("rate_limit", retryable=True)
    if "timeout" in name:
        return ClassifiedError("timeout", retryable=True)
    if "connection" in name:
        return ClassifiedError("network", retryable=True)
    if "internalserver" in name:
        return ClassifiedError("server_error", retryable=True)
    if "authentication" in name or "permissiondenied" in name:
        return ClassifiedError("auth", retryable=False)
    if "badrequest" in name or "unprocessable" in name:
        if "context" in msg or "too long" in msg or "too many tokens" in msg or "maximum" in msg:
            return ClassifiedError("context_window", retryable=False)
        return ClassifiedError("bad_request", retryable=False)
    if "notfound" in name or "conflict" in name:
        return ClassifiedError("bad_request", retryable=False)

    # --- Text-sniff branch (GLM endpoint bodies may not map to SDK classes) ---
    if "429" in msg or "rate limit" in msg or "too many requests" in msg or "quota" in msg:
        return ClassifiedError("rate_limit", retryable=True)
    if "timeout" in msg or "timed out" in msg:
        return ClassifiedError("timeout", retryable=True)
    if "connection" in msg and any(k in msg for k in ("refused", "reset", "unreachable", "broken pipe")):
        return ClassifiedError("network", retryable=True)
    if "context length" in msg or "context window" in msg or "maximum context" in msg or "too many input tokens" in msg:
        return ClassifiedError("context_window", retryable=False)
    if "401" in msg or "403" in msg or "unauthorized" in msg or "invalid api key" in msg or "permission denied" in msg:
        return ClassifiedError("auth", retryable=False)
    if any(c in msg for c in ("500 ", "502 ", "503 ", "529 ", "internal server error", "overloaded")):
        return ClassifiedError("server_error", retryable=True)
    if "400 " in msg or "bad request" in msg:
        return ClassifiedError("bad_request", retryable=False)

    return ClassifiedError("unknown", retryable=False)
