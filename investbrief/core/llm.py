"""共享的 Anthropic client helper。

供邮件 pipeline 与 ETF 分析包共用，使两者都不再依赖已移除的 web 层。
"""
import os
import random
import time
import logging
from functools import lru_cache

import anthropic

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_client() -> anthropic.Anthropic:
    """返回进程级缓存的 Anthropic client。"""
    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    base_url = os.environ.get("ANTHROPIC_BASE_URL")
    if base_url:
        return anthropic.Anthropic(api_key=api_key, base_url=base_url)
    return anthropic.Anthropic(api_key=api_key)


def default_model() -> str:
    """默认对话模型，可由环境变量覆盖。

    默认 claude-sonnet-4-5-20250929：GLM 等 Anthropic 兼容端点通常支持该代码，
    而 claude-sonnet-4-6 多不被兼容端点识别。env 仍可覆盖，但会过滤掉带 [1m]
    等 context 标记的值（Claude Code 运行时会把自己的模型 ID 泄露进该 env，
    如 glm-5.2[1m]，这类 ID 不被兼容端点识别）。
    """
    env_model = os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL")
    if env_model and "[1m]" not in env_model:
        return env_model
    return "claude-sonnet-4-5-20250929"


def call_claude(
    messages: list[dict],
    *,
    system: str | None = None,
    max_tokens: int = 1024,
    temperature: float = 0.3,
    max_retries: int = 2,
) -> str | None:
    """Unified Claude call wrapper: error classification + exponential backoff.

    Returns stripped text on success; returns None on non-retryable error or
    after retries exhausted. Callers handle the None case with their own
    fallback string.

    Backoff: base 1s × 2^attempt + jitter(0-1s), cap 30s. Only retryable errors
    (network/timeout/rate-limit/5xx) are retried; auth/4xx/context_window return
    None immediately.
    """
    from investbrief.core.llm_errors import classify_anthropic_error
    try:
        client = get_client()
    except Exception as e:
        logger.warning(f"Claude call failed: client init error: {e}")
        return None
    kwargs: dict = {
        "model": default_model(),
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system is not None:
        kwargs["system"] = system
    if temperature is not None:
        kwargs["temperature"] = temperature

    for attempt in range(max_retries + 1):
        try:
            resp = client.messages.create(**kwargs)
            return (resp.content[0].text or "").strip()
        except Exception as e:
            err = classify_anthropic_error(e)
            if not err.retryable or attempt >= max_retries:
                logger.warning(
                    f"Claude call failed [{err.code}] (attempt {attempt+1}/{max_retries+1}): {e}"
                )
                return None
            delay = min(30.0, (2 ** attempt) + random.uniform(0, 1))
            logger.warning(
                f"Claude call [{err.code}] retrying in {delay:.1f}s "
                f"(attempt {attempt+1}/{max_retries+1}): {e}"
            )
            time.sleep(delay)
    return None
