"""宏观研判：Claude 生成 ①核心观点 + ⑥风险（一次调用，JSON 输出）。"""
import json
import logging
import re

from investbrief.core.llm import get_client, default_model

logger = logging.getLogger(__name__)

MACRO_BRIEF_PROMPT = """你是资深宏观经济分析师，为投资者撰写每日中美宏观市场简报。

基于提供的中美宏观数据，输出纯 JSON（不要 markdown 代码块标记），包含两个字段：
- "summary"：核心观点，纯 HTML（可用 <p>、<strong>、<ul><li>、<br>；不要 markdown/代码块标记），分 4 个小节，每节以 <strong>小节标题</strong> 起头：
  1. <strong>宏观环境</strong>：中美经济数据信号（CPI/PMI/就业等）、增长与通胀走向
  2. <strong>货币政策</strong>：美联储 vs 中国央行立场、美债收益率、中美利差含义
  3. <strong>大类资产</strong>：美股/A股/债市/汇率/商品走势逻辑与轮动
  4. <strong>风险与机会</strong>：最需关注的事件、潜在拐点
  每节先用 <strong>1 句方向性结论</strong>开门（偏多/偏空/中性），再用 <ul><li> 列 2-4 个分点论据，关键数字用 <strong>。
  必须分点陈列、可读性优先；禁止把一节写成一大段连续文字墙。总字数 400-600。
- "risk"：未来一周风险事件与关注点，纯 HTML，用 <ul><li> 列 3-5 条，每条关键事件/日期用 <strong>，120 字以内。

只用提供的数据，不编造数字。严格按 JSON 输出，形如 {"summary": "...", "risk": "..."}。"""


def serialize_macro_context(us_data: dict, cn_data: dict, news: list, risk_scores: dict | None = None) -> str:
    """Build compact text context from US+CN macro data for Claude."""
    lines = []

    def _emit_market(label: str, md: dict):
        lines.append(f"## {label}")
        mp = md.get("monetary_policy") or {}
        if mp:
            for k, v in mp.items():
                lines.append(f"- {k}: {v}")
        ap = md.get("asset_performance") or []
        if ap:
            lines.append("### 大类资产表现")
            for a in ap[:8]:
                name = a.get("name", "")
                change = a.get("change")
                try:
                    change_str = f"{change:+.2f}%" if change is not None else "-"
                except (TypeError, ValueError):
                    change_str = str(change) if change is not None else "-"
                lines.append(f"- {name}: {change_str}")
        ec = md.get("economic_calendar") or []
        if ec:
            lines.append("### 经济日历")
            for e in ec[:8]:
                ev = e.get("event") or e.get("name", "")
                dt = e.get("date", "")
                forecast = e.get("forecast", "")
                previous = e.get("previous", "")
                lines.append(f"- {dt} {ev} (预期:{forecast or 'N/A'}, 前值:{previous or 'N/A'})")

    _emit_market("美国宏观", us_data)
    _emit_market("中国宏观", cn_data)

    if news:
        lines.append("\n## 重要新闻")
        for n in news[:5]:
            lines.append(f"- {n.get('title', '')} ({n.get('source', '')})")

    if risk_scores:
        lines.append("\n## 市场周期风险分（模型跟踪信号；跟踪≠预测，不可作为单独买卖依据）")
        for market, name in (("us", "美股"), ("cn", "A股"), ("gold", "黄金")):
            r = risk_scores.get(market) or {}
            if r.get("total_score") is not None:
                lines.append(f"- {name}: 风险分 {r['total_score']}（{r['state']}），{r['action']}")

    return "\n".join(lines)


def generate_macro_brief(us_data: dict, cn_data: dict, news: list, risk_scores: dict | None = None, max_retries: int = 2) -> tuple[str, str]:
    """一次 Claude 调用同时生成 ①核心观点 + ⑥风险（JSON 输出），带重试。

    失败重试 max_retries 次；最终仍失败则返回兜底占位（pipeline 不崩）。
    """
    client = get_client()
    context = serialize_macro_context(us_data, cn_data, news, risk_scores=risk_scores)
    fallback_summary = "<p>宏观研判生成失败，请查看下方数据。</p>"
    fallback_risk = "<p>风险研判生成失败。</p>"

    for attempt in range(max_retries + 1):
        try:
            response = client.messages.create(
                model=default_model(),
                max_tokens=2560,
                temperature=0.3,
                system=MACRO_BRIEF_PROMPT,
                messages=[{"role": "user", "content": context}],
            )
            text = response.content[0].text.strip()
            text = re.sub(r"^\s*```(?:json)?\s*\n?", "", text)
            text = re.sub(r"\n?\s*```\s*$", "", text)
            data = json.loads(text)
            summary = (data.get("summary") or "").strip() or fallback_summary
            risk = (data.get("risk") or "").strip() or fallback_risk
            logger.info(f"Generated macro brief (attempt {attempt + 1})")
            return summary, risk
        except Exception as e:
            if attempt < max_retries:
                logger.warning(f"Macro brief attempt {attempt + 1} failed, retrying: {e}")
            else:
                logger.warning(f"Macro brief failed after {max_retries + 1} attempts: {e}")
    return fallback_summary, fallback_risk
