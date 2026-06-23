import json
import logging
import os

import anthropic

logger = logging.getLogger(__name__)


_client_instance = None


def _get_client():
    global _client_instance
    if _client_instance is not None:
        return _client_instance
    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    base_url = os.environ.get("ANTHROPIC_BASE_URL")
    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    _client_instance = anthropic.Anthropic(**kwargs)
    return _client_instance


def stream_chat(message: str, market: str, market_data: dict, history: list[dict]):
    client = _get_client()
    model = os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL", "claude-sonnet-4-6")

    system_prompt = f"""你是一位简洁专业的投资顾问。根据以下{market.upper()}市场数据回答用户问题。
数据时间：{market_data.get('updated_at', 'unknown')}
市场数据摘要：
{json.dumps(market_data, ensure_ascii=False, default=str)[:15000]}

回答规则：
1. 第一句话直接给出结论/判断，不要铺垫
2. 用分点列表展开分析，每点一行，不要写大段文字
3. 每个要点控制在30字以内，只说关键数据和结论
4. 用Markdown格式（加粗、列表）
5. 回答总长度控制在300字以内
6. 用中文回答，不要给出确定性的投资建议
7. 不要写免责声明，不要说"请注意""基于以上分析"等套话"""

    messages = history + [{"role": "user", "content": message}]

    try:
        with client.messages.stream(
            model=model,
            max_tokens=1024,
            system=system_prompt,
            messages=messages,
        ) as stream:
            for text in stream.text_stream:
                yield text
    except anthropic.AuthenticationError:
        logger.error("Anthropic API authentication failed")
        raise
    except anthropic.RateLimitError:
        logger.error("Anthropic API rate limit exceeded")
        raise
    except anthropic.APIError as e:
        logger.error(f"Anthropic API error: {e}")
        raise


_LANGUAGE_INSTRUCTION = {
    "zh-CN": "用中文回答",
    "ko-KR": "한국어로 답변하세요",
    "en": "Answer in English",
}


def analyze_section(section: str, market: str, section_data: dict, language: str = "zh-CN") -> str:
    client = _get_client()
    model = os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL", "claude-sonnet-4-6")

    lang_instruction = _LANGUAGE_INSTRUCTION.get(language, "用中文回答")

    prompt = f"""分析以下{market.upper()}市场的「{section}」板块数据，给出投资建议。
数据：
{json.dumps(section_data, ensure_ascii=False, default=str)[:10000]}

要求：{lang_instruction}，200-400字，分析当前状态、趋势、风险点，不给确定性建议"""

    try:
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
    except anthropic.APIError as e:
        logger.error(f"Section analysis API error: {e}")
        raise
