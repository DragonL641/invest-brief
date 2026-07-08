"""宏观研判：Claude 生成 ①核心观点 + ⑥风险（一次调用，JSON 输出）。"""
import logging

logger = logging.getLogger(__name__)

MACRO_BRIEF_PROMPT = """你是资深宏观经济分析师，为投资者撰写每日中美宏观市场简报。

基于提供的中美宏观数据，输出纯 JSON（不要 markdown 代码块标记），包含两个字段：
- "summary"：核心观点，纯 HTML（可用 <p>、<strong>、<ul><li>、<br>；不要 markdown/代码块标记），**按市场分 4 个小节**，每节以 <strong>小节标题</strong> 起头：
  1. <strong>🌐 整体宏观</strong>：中美利差/全球资金流/风险偏好/跨市场联动主题
  2. <strong>🇺🇸 美国市场</strong>：美股走势 + 美联储/美债收益率 + 美国经济（CPI/GDP/PMI/就业）+ 该市场风险与机会
  3. <strong>🇨🇳 中国市场</strong>：A股走势 + 中国央行/LPR/M2/社融 + 中国经济（CPI/GDP）+ 该市场风险与机会
  4. <strong>🥇 黄金</strong>：金价 + 实际利率/避险需求 + 该资产风险与机会
  每节先用 <strong>1 句方向性结论</strong>开门（偏多/偏空/中性），再用 <ul><li> 列 2-4 个分点论据，关键数字用 <strong>。
  必须分点陈列、可读性优先；禁止把一节写成一大段连续文字墙。总字数 400-600。
  某市场数据缺失或极少（如黄金数据少）则该节简短或省略，不要硬凑。
- "risk"：未来一周风险事件与关注点，纯 HTML，用 <ul><li> 列 3-5 条，每条关键事件/日期用 <strong>，120 字以内。

只用提供的数据，不编造数字。严格按 JSON 输出，形如 {"summary": "...", "risk": "..."}。

此外,上下文会提供"宏观环境四象限(规则判定)"。如规则判定有明显偏差(如数据已显示滞胀但规则判繁荣),可在对应市场小节(🇺🇸/🇨🇳)中修正并说明依据;无明显偏差则直接采纳。"""


def serialize_macro_context(us_data: dict, cn_data: dict, news: list,
                            risk_scores: dict | None = None,
                            regime_data: dict | None = None,
                            max_chars: int = 8000) -> str:
    """Build compact text context from US+CN macro data for Claude.

    max_chars budget: US/CN core market data is always emitted; the optional
    news / risk_scores / regime_data sections are gated by remaining budget
    (priority: news > risk_scores > regime_data). GLM's 128k window means 8000
    is rarely hit — the value is keeping Claude focused on signal-rich context.
    """
    lines: list[str] = []

    def _used() -> int:
        return sum(len(l) + 1 for l in lines)

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

    # Priority 2: news (downgrade to top-3 if budget tight)
    if news:
        news = news[:5]
        approx_news_chars = sum(len(n.get("title", "")) + len(n.get("source", "")) + 6 for n in news)
        if _used() + 50 + approx_news_chars > max_chars:
            news = news[:3]
        if _used() + 50 < max_chars:
            lines.append("\n## 重要新闻")
            for n in news:
                lines.append(f"- {n.get('title', '')} ({n.get('source', '')})")

    # Priority 3: risk_scores (skip if budget tight)
    if risk_scores and _used() + 250 < max_chars:
        lines.append("\n## 市场周期风险分（模型跟踪信号；跟踪≠预测，不可作为单独买卖依据）")
        for market, name in (("us", "美股"), ("cn", "A股"), ("gold", "黄金")):
            r = risk_scores.get(market) or {}
            if r.get("total_score") is not None:
                level = r.get("risk_level", "?")
                lines.append(
                    f"- {name}: 风险分 {r['total_score']}（{r['state']} / {level}），{r['action']}"
                )
                # 高分 indicator 摘要：让 Claude 写"风险与机会"能点出具体极端子指标
                inds = r.get("indicators") or {}
                hot = []
                for k, v in inds.items():
                    if not isinstance(v, dict):
                        continue
                    score = v.get("score")
                    if isinstance(score, (int, float)) and score >= 8:
                        hot.append((v.get("name") or k, float(score)))
                if hot:
                    hot.sort(key=lambda x: x[1], reverse=True)
                    hot_str = "；".join(f"{n}({s:.1f})" for n, s in hot[:3])
                    lines.append(f"  极端指标: {hot_str}")

    # Priority 4: regime_data (skip if budget tight)
    if regime_data and _used() + 250 < max_chars:
        lines.append("\n## 宏观环境四象限（规则判定，参考用）")
        for market, name in (("us", "美国"), ("cn", "中国")):
            r = regime_data.get(market) or {}
            if r.get("quadrant"):
                # CN 多一轴:信用(M2+社融作 growth 领先指标);US 无
                credit = r.get("credit_axis")
                credit_str = f"/信用{credit}" if credit else ""
                lines.append(
                    f"- {name}: {r['quadrant']}（置信度{r.get('confidence', '?')}%，"
                    f"增长{r.get('growth_axis', '?')}/通胀{r.get('inflation_axis', '?')}"
                    f"{credit_str}）"
                )
                # 关键数值：让 Claude 看到具体 GDP 同比 / CPI / M2 / 社融 而非只看象限标签
                inds = r.get("indicators") or {}
                kv = ", ".join(f"{k}={v}" for k, v in inds.items()
                               if isinstance(v, (int, float)))
                if kv:
                    lines.append(f"  关键值: {kv}")

    result = "\n".join(lines)
    if len(result) > max_chars:
        # Hard fallback: US/CN core itself exceeded budget (rare). Truncate + flag.
        result = result[:max_chars] + "\n...(上下文因长度截断)"
        logger.warning(f"serialize_macro_context hard-truncated to {max_chars} chars")
    return result


def generate_macro_brief(us_data: dict, cn_data: dict, news: list,
                         risk_scores: dict | None = None,
                         regime_data: dict | None = None) -> tuple[str, str]:
    """Generate ① core view + ⑥ risk in one Claude call (JSON output).

    call_claude retries network-class errors internally; extract_json tolerates
    JSON drift (fence/trailing/Python-style). On any failure, returns the
    fallback placeholder pair (pipeline never crashes).
    """
    from investbrief.core.llm import call_claude
    from investbrief.core.llm_json import extract_json

    context = serialize_macro_context(us_data, cn_data, news,
                                      risk_scores=risk_scores,
                                      regime_data=regime_data)
    fallback_summary = "<p>宏观研判生成失败，请查看下方数据。</p>"
    fallback_risk = "<p>风险研判生成失败。</p>"

    text = call_claude(
        [{"role": "user", "content": context}],
        system=MACRO_BRIEF_PROMPT,
        max_tokens=2560,
        temperature=0.3,
    )
    if text is None:
        return fallback_summary, fallback_risk
    try:
        data = extract_json(text)
    except ValueError as e:
        logger.warning(f"Macro brief JSON extract failed: {e}")
        return fallback_summary, fallback_risk
    summary = (data.get("summary") or "").strip() or fallback_summary
    risk = (data.get("risk") or "").strip() or fallback_risk
    return summary, risk
