"""持仓组合 Claude 综合研判。

输入某收件人的多标的分析结果（HoldingResult list），输出组合层面研判：
整体偏多/偏空、最值得关注的标的、矛盾信号与倾向。LLM 不可用时 fallback 到结构化摘要。

复用 core.llm.get_client（不内联构造 anthropic 客户端，遵循项目约定）。
"""

from investbrief.core.textfmt import md_inline
from investbrief.holdings.analyzer import HoldingResult


def generate_holdings_brief(results: list[HoldingResult]) -> str:
    """生成持仓组合研判（HTML 片段）。失败返回 fallback 摘要，不抛异常。"""
    if not any(not r.error for r in results):
        return "<p>（本期持仓无可用分析数据）</p>"
    from investbrief.core.llm import call_claude

    prompt = _build_prompt(results)
    text = call_claude(
        [{"role": "user", "content": prompt}],
        max_tokens=800,
    )
    return md_inline(text) if text else _fallback(results)


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
        fund_parts = [f"PE={f.get('pe')}", f"ROE={f.get('roe')}", f"营收增长={f.get('revenue_growth')}"]
        if f.get("gross_margin") is not None:
            fund_parts.append(f"毛利率={f.get('gross_margin')}")
        if f.get("net_margin") is not None:
            fund_parts.append(f"净利率={f.get('net_margin')}")
        if f.get("debt_ratio") is not None:
            fund_parts.append(f"负债率={f.get('debt_ratio')}")
        lines.append(f"  基本面: {' '.join(fund_parts)}")
    if r.technicals:
        t = r.technicals
        lines.append(
            f"  技术面: 均线={t.get('ma_alignment')} RSI={t.get('rsi')} "
            f"MACD={t.get('macd_cross')} 量比={t.get('volume_ratio')} "
            f"5日={t.get('return_5d')}% 10日={t.get('return_10d')}% 20日={t.get('return_20d')}% "
            f"60日={t.get('return_60d')}% 区间位置={t.get('position_60d')} "
            f"布林位置={t.get('boll_position')} 60日新高={t.get('new_high_60d')}"
        )
    cps = (r.technicals or {}).get("candle_patterns") or []
    if cps:
        p0 = cps[0]
        vol_txt = "放量" if p0.get("volume_confirmed") else "缩量"
        status_cn = {"confirmed": "已确认", "unconfirmed": "未确认",
                     "pending": "待确认"}.get(p0.get("status"), "")
        lines.append(f"  K线信号: {p0['name_cn']} · {vol_txt} · {status_cn} — 辅助择时,非买卖指令")
    if r.insider and r.insider.get("direction") and r.insider.get("direction") != "flat":
        verb = "增持" if r.insider["direction"] == "buy" else "减持"
        lines.append(f"  高管/大股东{verb}: 净增减持股数 {r.insider.get('net_shares')} ({r.insider.get('count')} 笔)")
    if r.events and r.events.get("next_earnings"):
        lines.append(f"  下次财报: {r.events['next_earnings']} (距 {r.events.get('days_to_next')} 天)")
    if r.cn_activity and (r.cn_activity.get("dragon_tiger_count") or r.cn_activity.get("institution_research_count")):
        lines.append(f"  龙虎榜×{r.cn_activity.get('dragon_tiger_count', 0)} 机构调研×{r.cn_activity.get('institution_research_count', 0)}")
    if r.forecast and r.forecast.get("eps_next") is not None:
        lines.append(f"  盈利预估: 下季EPS {r.forecast['eps_next']} (同比 {r.forecast.get('yoy_pct')}%)")
    if r.news:
        lines.append(f"  近期新闻: {r.news[0].get('title', '')}（共{len(r.news)}条）")
    return "\n".join(lines)


def _fallback_stock_conclusion(r: HoldingResult) -> str:
    """LLM 不可用时的规则兜底（rating 分布 + technicals 趋势）。

    distribution schema: CN buy/outperform/neutral/underperform/sell
    （strong_buy/strong_sell 兼容性保留，合计入多/空。）
    """
    rt = r.rating or {}
    tech = r.technicals or {}
    dist = rt.get("distribution", {}) or {}
    bull = sum(dist.get(k, 0) or 0 for k in ("strong_buy", "buy", "outperform"))
    bear = sum(dist.get(k, 0) or 0 for k in ("strong_sell", "sell", "underperform"))
    ma = tech.get("ma_alignment", "")
    if not dist and not tech:
        return "数据不足，无法生成结论。"
    if ma == "bullish" and bull > bear:
        return f"偏多。均线多头排列，评级偏多（{bull}买 vs {bear}卖），趋势向上。"
    if ma == "bearish" and bear > bull:
        return f"偏空。均线空头排列，评级偏空（{bear}卖 vs {bull}买），注意风险。"
    if bull > bear:
        return f"偏多。评级偏多（{bull}买 vs {bear}卖），但技术面待确认。"
    if bear > bull:
        return f"偏空。评级偏空（{bear}卖 vs {bull}买），谨慎。"
    return f"中性。多空均衡（{bull}买 vs {bear}卖），建议观望。"


def generate_stock_conclusion(r: HoldingResult) -> str:
    """单标的 Claude 综合研判。失败 fallback，不抛异常。

    对标 etf/analyzer.py:_ai_synthesize。r.error 非空直接返回空（不调 Claude）。
    """
    if r.error:
        return ""
    from investbrief.core.llm import call_claude
    from investbrief.holdings.regime_prompts import regime_hint

    market_label = "A股"
    regime = (r.technicals or {}).get("regime")
    hint = regime_hint(regime)
    regime_line = f"\n【当前市场状态：{regime}】{hint}" if hint else ""

    prompt = f"""你是一位{market_label}投资顾问。基于以下信息给出该标的的综合研判。
{regime_line}

{_format_holding(r)}

要求：
1. 第一句直接给整体结论（偏多/偏空/中性）
2. 如有矛盾信号（如评级偏多但资金流出），指出并给出倾向
3. 给出具体操作建议（买入/持有/观望/减仓）
4. 150 字以内，中文，不要铺垫套话"""

    text = call_claude(
        [{"role": "user", "content": prompt}],
        max_tokens=400,
    )
    return text if text else _fallback_stock_conclusion(r)


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
