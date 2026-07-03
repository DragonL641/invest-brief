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
