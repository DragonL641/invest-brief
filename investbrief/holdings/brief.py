"""持仓组合 Claude 综合研判。

输入某收件人的多标的分析结果（HoldingResult list），输出组合层面研判：
整体偏多/偏空、最值得关注的标的、矛盾信号与倾向。LLM 不可用时 fallback 到结构化摘要。

复用 core.llm.get_client（不内联构造 anthropic 客户端，遵循项目约定）。
"""
import logging
import os

from investbrief.holdings.analyzer import HoldingResult

logger = logging.getLogger(__name__)


def generate_holdings_brief(results: list[HoldingResult], max_retries: int = 2) -> str:
    """生成持仓组合研判（HTML 片段）。失败返回 fallback 摘要，不抛异常。"""
    if not any(not r.error for r in results):
        return "<p>（本期持仓无可用分析数据）</p>"
    try:
        from investbrief.core.llm import get_client as _get_client, default_model
        client = _get_client()
        model = default_model()
    except Exception as e:
        logger.warning(f"holdings brief: llm init failed: {e}")
        return _fallback(results)

    prompt = _build_prompt(results)
    for attempt in range(max_retries + 1):
        try:
            resp = client.messages.create(
                model=model, max_tokens=800,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.content[0].text.strip()
        except Exception as e:
            logger.warning(f"holdings brief attempt {attempt + 1} failed: {e}")
    return _fallback(results)


def _format_holding(r: HoldingResult) -> str:
    """格式化单标的各维度为多行文本。组合 brief 与单标的 brief 共用。

    不含 r.ai_conclusion 行（单标的 prompt 不把自身结论作为输入）。
    """
    p, rt = r.price, r.rating
    pt = rt.get("price_target", {}) or {}
    dist = rt.get("distribution", {}) or {}
    lines = [f"【{r.symbol} {r.name}】({r.market}/{r.type})"]
    if p.get("current") is not None:
        lines.append(f"  价格: {p.get('current')} (涨跌 {p.get('change_pct')}%)")
    if dist:
        lines.append(f"  评级分布: {dist} (共 {rt.get('total')} 票)")
    if pt.get("mean") is not None:
        lines.append(f"  目标价: {pt.get('mean')} (空间 {pt.get('upside_pct')}%)")
    if rt.get("actions"):
        lines.append(f"  近期机构动作: {rt['actions'][:3]}")
    if r.flow and r.flow.get("main_net") is not None:
        lines.append(f"  主力资金: {r.flow.get('main_net')}")
    if r.fundamentals:
        f = r.fundamentals
        lines.append(f"  基本面: PE={f.get('pe')} ROE={f.get('roe')} 营收增长={f.get('revenue_growth')}")
    if r.technicals:
        t = r.technicals
        lines.append(f"  技术面: 均线={t.get('ma_alignment')} RSI={t.get('rsi')} MACD={t.get('macd_cross')} 60日涨跌={t.get('return_60d')}%")
    if r.insider and r.insider.get("direction") and r.insider.get("direction") != "flat":
        verb = "增持" if r.insider["direction"] == "buy" else "减持"
        lines.append(f"  高管/大股东{verb}: 净额 {r.insider.get('net_amount')} ({r.insider.get('count')} 笔)")
    if r.events and r.events.get("next_earnings"):
        lines.append(f"  下次财报: {r.events['next_earnings']} (距 {r.events.get('days_to_next')} 天)")
    if r.cn_activity and (r.cn_activity.get("dragon_tiger_count") or r.cn_activity.get("institution_research_count")):
        lines.append(f"  龙虎榜×{r.cn_activity.get('dragon_tiger_count', 0)} 机构调研×{r.cn_activity.get('institution_research_count', 0)}")
    if r.forecast and r.forecast.get("eps_next") is not None:
        lines.append(f"  盈利预估: 下季EPS {r.forecast['eps_next']} (同比 {r.forecast.get('yoy_pct')}%)")
    if r.news:
        lines.append(f"  近期新闻: {r.news[0].get('title', '')}（共{len(r.news)}条）")
    return "\n".join(lines)


def _build_prompt(results: list[HoldingResult]) -> str:
    lines = ["你是投资顾问。基于以下持仓分析，给出组合层面的综合研判。", ""]
    for r in results:
        if r.error:
            lines.append(f"【{r.symbol} {r.name}】分析失败（{r.error}）")
        else:
            lines.append(_format_holding(r))
            if r.ai_conclusion:
                lines.append(f"  单标的研判: {r.ai_conclusion}")
        lines.append("")
    lines += [
        "要求：",
        "1. 第一句直接给整体结论（偏多/偏空/中性）",
        "2. 指出 1-2 个最值得关注的标的（评级变化大/资金流异常/目标价空间大）",
        "3. 如有矛盾信号（评级偏多但资金流出），指出并给出倾向",
        "4. 200 字以内，中文，不要铺垫套话",
    ]
    return "\n".join(lines)


def _fallback(results: list[HoldingResult]) -> str:
    """LLM 不可用时的结构化摘要（HTML 片段）。"""
    lines = ["<strong>持仓概览（自动摘要）</strong><br>"]
    for r in results:
        if r.error:
            lines.append(f"{r.symbol} — 分析失败")
            continue
        p, rt = r.price, r.rating
        pt = rt.get("price_target", {}) or {}
        bits = [f"{r.symbol} {r.name}".strip()]
        if p.get("current") is not None:
            bits.append(f"现价 {p['current']}")
        if p.get("change_pct") is not None:
            bits.append(f"{p['change_pct']}%")
        if pt.get("upside_pct") is not None:
            bits.append(f"目标空间 {pt['upside_pct']}%")
        lines.append(" · ".join(str(b) for b in bits))
    return "<br>".join(lines)
