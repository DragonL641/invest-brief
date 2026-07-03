"""持仓卡片 HTML 生成。

复用 email_base.html 的 CSS class（stock-up/down, analyst-section, fundamental-section,
rating-bar, upgrade-item, summary-box, metrics-row），保证与宏观邮件视觉一致。
按 type 动态渲染可用维度，缺失维度优雅降级（返回空片段）。
"""
from investbrief.holdings.analyzer import HoldingResult

_RATING_CN = {
    "strong_buy": "强烈买入", "buy": "买入", "outperform": "增持",
    "neutral": "中性", "underperform": "减持", "sell": "卖出",
    "strong_sell": "强烈卖出",
}
_TYPE_CN = {"stock": "股票", "etf": "ETF", "fund": "基金"}


def render_holdings_section(results: list[HoldingResult]) -> str:
    """拼接所有持仓标的卡片。"""
    if not results:
        return '<div class="no-data">暂无持仓数据</div>'
    return "\n".join(_render_card(r) for r in results)


# ==================== 单标的卡片 ====================

def _render_card(r: HoldingResult) -> str:
    name = r.name or r.symbol
    trend_cls = _trend_class(r.price.get("change_pct"))
    change_txt = _fmt_pct(r.price.get("change_pct"))
    badge = f'{_market_flag(r.market)} {name} <span style="float:right;font-weight:400;font-size:12px;color:#7f8c8d;">{r.symbol} · {_TYPE_CN.get(r.type, r.type)} · <span class="{trend_cls}">{change_txt}</span></span>'
    if r.error:
        return f'<div class="card"><div class="card-header">{badge}</div><div class="card-body"><div class="no-data">{r.symbol} 分析失败 — {r.error}</div></div></div>'
    body = "".join(filter(None, [
        _render_price(r), _render_rating(r), _render_fundamentals(r),
        _render_technicals(r), _render_flow(r), _render_signals(r),
        _render_news(r), _render_ai(r),
    ]))
    return f'<div class="card"><div class="card-header">{badge}</div><div class="card-body">{body}</div></div>'


# ==================== 维度片段 ====================

def _render_price(r: HoldingResult) -> str:
    p = r.price
    if not p or p.get("current") is None:
        return ""
    extras = []
    for label, key, digits in [("前收", "previous_close", 2), ("高", "high", 2),
                               ("低", "low", 2), ("成交量", "volume", 0),
                               ("市值", "market_cap", 0), ("成交额", "amount", 0),
                               ("累计净值", "acc_nav", 4)]:
        v = p.get(key)
        if v is not None:
            extras.append(f'<span class="metric"><span class="label">{label}</span> {_fmt_num(v, digits)}</span>')
    if p.get("iopv") is not None:
        extras.append(f'<span class="metric"><span class="label">IOPV</span> {_fmt_num(p["iopv"])}</span>')
    if p.get("premium_rate") is not None:
        extras.append(f'<span class="metric"><span class="label">溢价率</span> {_fmt_pct(p["premium_rate"])}</span>')
    extra_html = f'<div class="metrics-row">{"".join(extras)}</div>' if extras else ""
    return (f'<div class="stock-detail"><div class="stock-detail-header">'
            f'<span class="stock-name">现价</span><span class="stock-price">{_fmt_num(p["current"])}</span>'
            f'</div>{extra_html}</div>')


def _render_rating(r: HoldingResult) -> str:
    rt = r.rating
    if not rt:
        return ""
    parts = []
    dist = rt.get("distribution") or {}
    if dist:
        total = rt.get("total") or sum(dist.values()) or 1
        bar = "".join(
            f'<span class="{_bucket_class(k)}" style="width:{v / total * 100:.0f}%"></span>'
            for k, v in dist.items() if v
        )
        labels = " · ".join(f"{_RATING_CN.get(k, k)} {v}" for k, v in dist.items())
        parts.append(
            f'<div class="analyst-section"><div class="analyst-label">评级分布（共 {total} 票）</div>'
            f'<div class="rating-bar">{bar}</div><div class="rating-labels">{labels}</div></div>'
        )
    trend = rt.get("trend") or {}
    if trend:
        significant = sorted([(k, v) for k, v in trend.items() if abs(v) >= 3],
                             key=lambda x: -abs(x[1]))
        if significant:
            note = "vs 上月" if r.market == "us" else f"vs 上 {rt.get('days') or ''} 天"
            items = " · ".join(f"{_RATING_CN.get(k, k)} {v:+.1f}pp" for k, v in significant)
            parts.append(
                f'<div class="analyst-section"><div class="analyst-label">评级变化（{note}）</div>'
                f'<div class="analyst-row">{items}</div></div>'
            )
    pt = rt.get("price_target") or {}
    if pt.get("mean") is not None:
        bits = [f"目标均 {_fmt_num(pt['mean'])}"]
        if pt.get("upside_pct") is not None:
            bits.append(f"空间 <strong>{_fmt_pct(pt['upside_pct'])}</strong>")
        if pt.get("high") is not None and pt.get("low") is not None:
            bits.append(f"区间 {_fmt_num(pt['low'])}–{_fmt_num(pt['high'])}")
        if pt.get("num_analysts"):
            bits.append(f"{pt['num_analysts']} 位分析师")
        parts.append(f'<div class="analyst-section"><div class="analyst-row">{ " · ".join(bits)}</div></div>')
    actions = rt.get("actions") or []
    if actions:
        items = []
        for a in actions[:3]:
            if r.market == "us":
                grade = a.get("to_grade") or ""
                if a.get("from_grade"):
                    grade = f"{a['from_grade']}→{a.get('to_grade', '')}"
                core = f'{a.get("firm", "")} <span class="upgrade-grade">{grade}</span>'
            else:
                core = f'{a.get("institution", "")} <span class="upgrade-grade">{a.get("rating", "")}</span>'
            items.append(f'<div class="upgrade-item"><span class="upgrade-firm">{core}</span><span class="upgrade-date">{a.get("date", "")}</span></div>')
        parts.append(f'<div class="analyst-section"><div class="analyst-label">近期机构动作</div>{"".join(items)}</div>')
    return "".join(parts)


def _render_fundamentals(r: HoldingResult) -> str:
    f = r.fundamentals
    if not f:
        return ""
    bits = []
    for label, key, digits in [("PE", "pe", 1), ("ROE%", "roe", 1), ("营收增长%", "revenue_growth", 1),
                               ("净利增长%", "profit_growth", 1), ("毛利率%", "gross_margin", 1),
                               ("净利率%", "net_margin", 1), ("EPS", "eps", 2),
                               ("周收益%", "return_1w", 2), ("月收益%", "return_1m", 2),
                               ("季收益%", "return_3m", 2)]:
        v = f.get(key)
        if v is not None:
            bits.append(f'<span class="metric"><span class="label">{label}</span> {_fmt_num(v, digits)}</span>')
    if not bits:
        return ""
    return f'<div class="fundamental-section"><div class="metrics-row">{"".join(bits)}</div></div>'


def _render_technicals(r: HoldingResult) -> str:
    """技术面：均线排列/RSI/MACD 交叉/近期收益/60 日区间位置。"""
    t = r.technicals
    if not t:
        return ""
    align_cn = {"bullish": "多头排列", "bearish": "空头排列", "mixed": "纠缠"}
    bits = []
    if t.get("ma_alignment"):
        bits.append(f'<span class="metric"><span class="label">均线</span> {align_cn.get(t["ma_alignment"], t["ma_alignment"])}</span>')
    if t.get("rsi") is not None:
        bits.append(f'<span class="metric"><span class="label">RSI</span> {t["rsi"]}</span>')
    if t.get("macd_cross") and t["macd_cross"] != "none":
        is_gold = t["macd_cross"] == "golden"
        cls = "stock-up" if is_gold else "stock-down"
        bits.append(f'<span class="metric"><span class="label">MACD</span> <span class="{cls}">{"金叉" if is_gold else "死叉"}</span></span>')
    for label, key in [("20日", "return_20d"), ("60日", "return_60d")]:
        v = t.get(key)
        if v is not None:
            bits.append(f'<span class="metric"><span class="label">{label}</span> <span class="{_trend_class(v)}">{v:+}%</span></span>')
    if t.get("position_60d") is not None:
        bits.append(f'<span class="metric"><span class="label">60日位置</span> {t["position_60d"]}%</span>')
    if not bits:
        return ""
    return f'<div class="fundamental-section"><div class="metrics-row">{"".join(bits)}</div></div>'


def _render_news(r: HoldingResult) -> str:
    """标的级新闻（top 3，紧凑展示）。"""
    if not r.news:
        return ""
    items = []
    for n in r.news[:3]:
        title = (n.get("title") or "")[:60]
        date = str(n.get("date", ""))[:10]
        items.append(
            f'<div style="font-size:12px;padding:3px 0;border-bottom:1px solid #f0f0f0;">'
            f'<span style="color:#2c3e50;">{title}</span> '
            f'<span style="color:#999;font-size:11px;">{date}</span></div>'
        )
    return f'<div style="margin-top:8px;">{"".join(items)}</div>'


def _render_flow(r: HoldingResult) -> str:
    fl = r.flow
    if not fl:
        return ""
    bits = []
    main = fl.get("main_net")
    if main is None:
        main = fl.get("main_net_flow")
    if main is not None:
        cls = "stock-up" if main > 0 else "stock-down"
        bits.append(f'<span class="metric"><span class="label">主力净流入</span> <span class="{cls}">{_fmt_num(main, 0)}</span></span>')
    if fl.get("main_pct") is not None:
        bits.append(f'<span class="metric"><span class="label">占比</span> {_fmt_pct(fl["main_pct"])}</span>')
    if not bits:
        return ""
    return f'<div class="institution-section"><div class="metrics-row">{"".join(bits)}</div></div>'


def _render_signals(r: HoldingResult) -> str:
    if not r.signals:
        return ""
    items = []
    for s in r.signals[:4]:
        sig = s.get("signal", "")
        cls = "stock-up" if sig == "bullish" else ("stock-down" if sig == "bearish" else "stock-neutral")
        items.append(f'<span class="metric"><span class="{cls}">{s.get("dimension", "")}/{s.get("name", "")}: {sig}</span></span>')
    return f'<div class="metrics-row" style="margin-top:8px;">{"".join(items)}</div>' if items else ""


def _render_ai(r: HoldingResult) -> str:
    if not r.ai_conclusion:
        return ""
    return f'<div class="summary-box" style="margin-top:8px;padding:10px;font-size:13px;">{r.ai_conclusion}</div>'


# ==================== 工具 ====================

def _market_flag(market: str) -> str:
    return "🇺🇸" if market == "us" else "🇨🇳"


def _bucket_class(k: str) -> str:
    """评级桶名 → rating-bar CSS class（buy/hold/sell，绑定红涨绿跌色）。"""
    if k in ("buy", "strong_buy", "outperform"):
        return "buy"
    if k in ("sell", "strong_sell", "underperform"):
        return "sell"
    return "hold"


def _trend_class(pct) -> str:
    if pct is None:
        return "stock-neutral"
    return "stock-up" if pct > 0 else ("stock-down" if pct < 0 else "stock-neutral")


def _fmt_pct(v) -> str:
    return f"{v:+.2f}%" if v is not None else "—"


def _fmt_num(v, digits: int = 2) -> str:
    return f"{v:,.{digits}f}" if v is not None else "—"
