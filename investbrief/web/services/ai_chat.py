import json
import os
import anthropic


def _get_client():
    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    base_url = os.environ.get("ANTHROPIC_BASE_URL")
    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return anthropic.Anthropic(**kwargs)


def stream_chat(message: str, market: str, market_data: dict, history: list[dict]):
    client = _get_client()
    model = os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL", "claude-sonnet-4-6")

    system_prompt = f"""你是一位专业的投资顾问。根据以下{market.upper()}市场数据回答用户问题。
数据时间：{market_data.get('updated_at', 'unknown')}
市场数据摘要：
{json.dumps(market_data, ensure_ascii=False, default=str)[:15000]}

回答要求：
- 基于提供的数据进行分析
- 给出具体数据和依据
- 用中文回答
- 不要给出确定性的投资建议"""

    messages = history + [{"role": "user", "content": message}]

    with client.messages.stream(
        model=model,
        max_tokens=2048,
        system=system_prompt,
        messages=messages,
    ) as stream:
        for text in stream.text_stream:
            yield text


def analyze_section(section: str, market: str, section_data: dict) -> str:
    client = _get_client()
    model = os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL", "claude-sonnet-4-6")

    prompt = f"""分析以下{market.upper()}市场的「{section}」板块数据，给出投资建议。
数据：
{json.dumps(section_data, ensure_ascii=False, default=str)[:10000]}

要求：用中文回答，200-400字，分析当前状态、趋势、风险点，不给确定性建议"""

    response = client.messages.create(
        model=model,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text
