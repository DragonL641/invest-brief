"""共享的 Anthropic client helper。

供邮件 pipeline 与 ETF 分析包共用，使两者都不再依赖已移除的 web 层。
"""
import os
from functools import lru_cache

import anthropic


@lru_cache(maxsize=1)
def get_client() -> anthropic.Anthropic:
    """返回进程级缓存的 Anthropic client。"""
    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    base_url = os.environ.get("ANTHROPIC_BASE_URL")
    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return anthropic.Anthropic(**kwargs)


def default_model() -> str:
    """默认对话模型，可由环境变量覆盖。"""
    return os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL", "claude-sonnet-4-6")
