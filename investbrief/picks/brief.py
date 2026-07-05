# investbrief/picks/brief.py
"""6 只 Top1 的 Claude 综合研判(1 次调用)。失败/空 → 占位。"""
from __future__ import annotations
import json
import logging

from investbrief.core.llm import call_claude
from investbrief.core.llm_json import extract_json

logger = logging.getLogger(__name__)

PICKS_BRIEF_PROMPT = """你是宏观+量化视角的投资分析师。下面是今日量化选股引擎选出的 6 只 Top1
(每个持仓周期 × 每个市场各 1 只)。请基于这些标的给出一段综合研判:
1) 整体市场偏好(引擎在这天偏向什么风格/行业/市值)
2) 6 只的共性逻辑(若有)
3) 主要风险提示
严格只输出 JSON: {"brief": "<p>...一段 html...</p>"}
"""


def serialize_picks_context(picks: list[dict]) -> str:
    compact = [{
        "profile": p.get("profile"), "market": p.get("market"),
        "symbol": p.get("symbol"), "name": p.get("name"),
        "composite": p.get("composite"),
        "top_factors": sorted(p.get("factor_scores", {}).items(),
                              key=lambda kv: (kv[1].get("weighted") or 0), reverse=True)[:2],
        "industry": p.get("industry"),
    } for p in picks]
    return json.dumps(compact, ensure_ascii=False, default=str)


def generate_picks_brief(picks: list[dict]) -> str:
    if not picks:
        return ""
    try:
        user = f"{PICKS_BRIEF_PROMPT}\n\n标的列表(JSON):\n{serialize_picks_context(picks)}"
        text = call_claude(messages=[{"role": "user", "content": user}],
                           max_tokens=768, temperature=0.3)
        if not text:
            return "<p>本期暂无综合研判。</p>"
        try:
            obj = extract_json(text)
            return obj.get("brief") or "<p>本期暂无综合研判。</p>"
        except ValueError:
            return f"<p>{text}</p>"   # 容错:模型未按 JSON 返回,直接用原文
    except Exception as e:
        logger.warning(f"generate_picks_brief failed: {e}")
        return "<p>本期暂无综合研判。</p>"
