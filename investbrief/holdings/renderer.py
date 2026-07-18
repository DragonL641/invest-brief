"""持仓卡片 HTML 生成（重构版）。

新版结构（Task 10+11）：
- 场内外分组渲染（场内 = stock/etf，场外 = fund）
- 卡片头部：名称 + symbol/type/现价 + 涨跌幅
- 关键信号 tag 行（_pick_key_signals，最多 3 个）
- 维度表格行（_render_dimensions：基本面/技术/资金筹码/机构态度/事件/预估/新闻）
- CSS bar（中性灰条 + 包裹值的 span 控红绿）
- 场外基金卡片（_render_fund_card：净值/收益/规模/经理/评级）
- AI 结论 box

CSS class（signal-tag-* / bar-* / dim-* / cell / cl / ai-box / group-title）由
mail/styles.py 统一定义（编辑研报风）。
"""
from investbrief.core.textfmt import md_inline
from investbrief.holdings.analyzer import HoldingResult

_TYPE_CN = {"stock": "股票", "etf": "ETF", "fund": "基金"}


def render_holdings_section(results: list[HoldingResult]) -> str:
    """三层层级渲染：个股 / 场内基金 / 场外基金。无该类型则整组省略。"""
    if not results:
        return '<div class="no-data">暂无持仓数据</div>'
    stocks = [r for r in results if r.type == "stock"]
    etfs = [r for r in results if r.type == "etf"]
    funds = [r for r in results if r.type == "fund"]

    def _sort_key(r):
        chg = (r.price or {}).get("change_pct") or 0
        return -chg

    parts = []
    if stocks:
        parts.append(f'<h3 class="group-title">个股 · {len(stocks)} 只</h3>')
        parts += [_render_card(r) for r in sorted(stocks, key=_sort_key)]
    if etfs:
        parts.append(f'<h3 class="group-title">场内基金 · {len(etfs)} 只</h3>')
        parts += [_render_card(r) for r in sorted(etfs, key=_sort_key)]
    if funds:
        parts.append(f'<h3 class="group-title">场外基金 · {len(funds)} 只</h3>')
        parts += [_render_fund_card(r) for r in sorted(funds, key=_sort_key)]
    if not (stocks or etfs or funds):
        parts.append('<div class="no-data">暂无持仓数据</div>')
    return "\n".join(parts)


# ==================== 场内标的卡片 ====================

def _render_card(r: HoldingResult) -> str:
    """场内标的卡片：头部 + 关键信号 + 维度表格行 + AI。"""
    name = r.name or r.symbol
    chg = (r.price or {}).get("change_pct")
    p = r.price or {}
    cur = p.get("current")
    cur_txt = f'<strong>{_fmt_num(cur)}</strong>' if cur is not None else ""
    head = (f'<div class="card-head"><span class="card-name">{name}</span>'
            f'<span class="card-meta">{r.symbol} · {_TYPE_CN.get(r.type, r.type)} · {cur_txt} '
            f'<span class="{_trend_class(chg)}">{_fmt_pct(chg)}</span></span></div>')
    if r.error:
        return f'<div class="card">{head}<div class="card-body no-data">{r.symbol} 分析失败 — {r.error}</div></div>'
    sigs = _pick_key_signals(r)
    sig_html = '<div class="signal-row">' + "".join(
        f'<span class="signal-tag signal-tag-{s["cls"]}">{s["label"]}</span>' for s in sigs) + '</div>' if sigs else ""
    dims = _render_dimensions(r)
    ai = f'<div class="ai-box"><span class="ai-label">AI 研判</span>{md_inline(r.ai_conclusion)}</div>' if r.ai_conclusion else ""
    # degraded: em 封禁等致关键数据源不可用 → 顶部横幅提示, dims 继续渲染(轻量降级, inline style 免新 CSS)
    degraded_html = (
        '<div style="margin:6px 0;padding:6px 8px;background:#fff4e5;color:#8a6d3b;'
        'font-size:12px;border-radius:4px;">⚠ 部分数据源暂不可用(em 限流)，仅显示有限信息</div>'
    ) if r.degraded else ""
    return f'<div class="card">{head}<div class="card-body">{sig_html}{degraded_html}{dims}{ai}</div></div>'


# ==================== 维度表格行 ====================

def _render_dimensions(r: HoldingResult) -> str:
    """维度表格行：每个维度一行 name+对齐数据。缺数据维度省略。"""
    rows = []

    # 估值基本面
    f = r.fundamentals
    if f:
        cells = _cells([("PE", f.get("pe"), 1), ("ROE%", f.get("roe"), 1),
                        ("营收%", f.get("revenue_growth"), 1),
                        ("毛利%", f.get("gross_margin"), 1),
                        ("净利%", f.get("net_margin"), 1), ("EPS", f.get("eps"), 2)])
        # 兼容旧字段名 profit_growth
        if not any(c for c in [f.get("revenue_growth")]):
            pg = f.get("profit_growth")
            if pg is not None:
                cells = (cells + _cells([("净利%", pg, 1)])) if "净利%" not in cells else cells
        if cells:
            rows.append(_dim_row("估值基本面", cells))

    # 技术面
    t = r.technicals
    if t:
        cells = []
        if t.get("rsi") is not None:
            over = "超买" if t["rsi"] > 70 else ("超卖" if t["rsi"] < 30 else "")
            cells.append(f'<span class="cell"><span class="cl">RSI</span> {t["rsi"]}{("(" + over + ")") if over else ""}</span>')
        if t.get("ma_alignment"):
            align_cn = {"bullish": "多头", "bearish": "空头", "mixed": "纠缠"}
            cells.append(f'<span class="cell"><span class="cl">均线</span> {align_cn.get(t["ma_alignment"], t["ma_alignment"])}</span>')
        if t.get("macd_cross") and t["macd_cross"] != "none":
            cells.append(f'<span class="cell"><span class="cl">MACD</span> {"金叉" if t["macd_cross"] == "golden" else "死叉"}</span>')
        if t.get("volume_ratio") is not None:
            cells.append(f'<span class="cell"><span class="cl">量比</span> {t["volume_ratio"]:.2f}</span>')
        if t.get("boll_position") is not None:
            cells.append(f'<span class="cell"><span class="cl">布林</span> {t["boll_position"]:.1f}</span>')
        if cells:
            rows.append(_dim_row("技术面", "".join(cells)))

    # ETF 估值溢价 + 命中信号(ETF 无 fundamentals/technicals,单独维度)
    if r.type == "etf":
        etf_cells = []
        pr = (r.price or {}).get("premium_rate")
        if pr is not None:
            cls = "stock-up" if pr > 0 else "stock-down"
            etf_cells.append(f'<span class="cell"><span class="cl">溢价率</span> <span class="{cls}">{pr:+.2f}%</span></span>')
        for s in (r.signals or [])[:4]:
            name = getattr(s, "name", None) or (s.get("name") if isinstance(s, dict) else "")
            sig = getattr(s, "signal", None) or (s.get("signal") if isinstance(s, dict) else "")
            sig_cn = {"bullish": "多", "bearish": "空", "warning": "警惕", "neutral": "中"}.get(sig, sig or "")
            if name:
                etf_cells.append(f'<span class="cell"><span class="cl">{name}</span> {sig_cn}</span>')
        if etf_cells:
            rows.append(_dim_row("溢价与信号", "".join(etf_cells)))

    # 资金筹码
    fl = r.flow
    cn_act = r.cn_activity
    if fl or cn_act:
        cells = []
        main = (fl or {}).get("main_net")
        if main is None:
            main = (fl or {}).get("main_net_flow")
        if main is not None:
            cls = "stock-up" if main > 0 else "stock-down"
            bar = _bar_html(abs(main), 5e8)
            cells.append(f'<span class="cell"><span class="cl">主力</span> <span class="{cls}">{_fmt_short_money(main)}</span>{bar}</span>')
        dt = (cn_act or {}).get("dragon_tiger_count", 0)
        if dt:
            cells.append(f'<span class="cell"><span class="cl">龙虎榜</span>×{dt}</span>')
        rc = (cn_act or {}).get("institution_research_count", 0)
        if rc:
            cells.append(f'<span class="cell"><span class="cl">机构调研</span>×{rc}</span>')
        if cells:
            rows.append(_dim_row("资金筹码", "".join(cells)))

    # 机构态度
    rt = r.rating
    if rt and (rt.get("distribution") or rt.get("price_target")):
        cells = []
        dist = rt.get("distribution") or {}
        if dist:
            total = rt.get("total") or sum(dist.values()) or 1
            buy_pct = (dist.get("buy", 0) + dist.get("strong_buy", 0) + dist.get("outperform", 0)) / total * 100
            cells.append(f'<span class="cell"><span class="cl">买入共识</span> {buy_pct:.0f}% {_bar_html(buy_pct, 100)}</span>')
        pt = rt.get("price_target") or {}
        if pt.get("upside_pct") is not None:
            cls = "stock-up" if pt["upside_pct"] > 0 else "stock-down"
            cells.append(f'<span class="cell"><span class="cl">目标空间</span> <span class="{cls}">{pt["upside_pct"]:+.0f}%</span></span>')
        if cells:
            rows.append(_dim_row("机构态度", "".join(cells)))

    # 事件（6 源合并最近 5 + 高管增减持）
    ev = r.events
    ins = r.insider
    ev_list = ev.get("events") if ev else None
    has_insider = ins.get("direction") and ins.get("direction") != "flat"
    if ev_list or has_insider:
        cells = []
        for e in (ev_list or [])[:5]:
            cells.append(f'<span class="cell"><span class="cl">{e["type"]}</span> {e["date"]} {e.get("desc","")[:20]}</span>')
        if has_insider:
            cls = "stock-up" if ins["direction"] == "buy" else "stock-down"
            verb = "增持" if ins["direction"] == "buy" else "减持"
            cells.append(f'<span class="cell"><span class="cl">高管{verb}</span> <span class="{cls}">{_fmt_short_money(ins.get("net_shares", 0))}股</span></span>')
        if cells:
            rows.append(_dim_row("事件", "".join(cells)))

    # 盈利预估
    fc = r.forecast
    if fc and fc.get("eps_next") is not None:
        cells = [f'<span class="cell"><span class="cl">下季EPS</span> {fc["eps_next"]:.2f}</span>']
        if fc.get("yoy_pct") is not None:
            cls = "stock-up" if fc["yoy_pct"] > 0 else "stock-down"
            cells.append(f'<span class="cell"><span class="cl">同比</span> <span class="{cls}">{fc["yoy_pct"]:+.0f}%</span></span>')
        rows.append(_dim_row("盈利预估", "".join(cells)))

    # 新闻
    if r.news:
        items = "".join(
            f'<div class="news-item">• {(n.get("title", ""))[:50]} <span class="news-date">{str(n.get("date", ""))[:10]}</span></div>'
            for n in r.news[:3])
        rows.append(_dim_row("新闻", items))

    return f'<div class="dims">{"".join(rows)}</div>' if rows else ""


# ==================== 场外基金卡片 ====================

def _render_fund_card(r: HoldingResult) -> str:
    """场外基金卡片：净值/收益/规模/经理/评级/AI。"""
    name = r.name or r.symbol
    p = r.price or {}
    chg = p.get("change_pct")
    head = (f'<div class="card-head"><span class="card-name">{name}</span>'
            f'<span class="card-meta">{r.symbol} · 基金 · 单位净值 <strong>{_fmt_num(p.get("current"))}</strong> '
            f'<span class="{_trend_class(chg)}">{_fmt_pct(chg)}</span></span></div>')
    if r.error:
        return f'<div class="card">{head}<div class="card-body no-data">{r.error}</div></div>'
    cells = []
    if p.get("acc_nav") is not None:
        cells.append(f'<span class="cell"><span class="cl">累计净值</span> {_fmt_num(p["acc_nav"], 4)}</span>')
    f = r.fundamentals
    for label, key in [("近1周%", "return_1w"), ("近1月%", "return_1m"), ("近3月%", "return_3m")]:
        v = (f or {}).get(key)
        if v is not None:
            cells.append(f'<span class="cell"><span class="cl">{label}</span> <span class="{_trend_class(v)}">{v:+.2f}%</span></span>')
    fm = r.fund_meta
    for label, key in [("规模(亿)", "scale"), ("经理", "manager"), ("评级", "rating")]:
        v = (fm or {}).get(key)
        if v is not None:
            cells.append(f'<span class="cell"><span class="cl">{label}</span> {v}</span>')
    dims = f'<div class="dims"><div class="dim-row"><span class="dim-name">概况</span><div class="dim-cells">{"".join(cells)}</div></div></div>' if cells else ""
    ai = f'<div class="ai-box"><span class="ai-label">AI 研判</span>{md_inline(r.ai_conclusion)}</div>' if r.ai_conclusion else ""
    return f'<div class="card">{head}<div class="card-body">{dims}{ai}</div></div>'


# ==================== 行/单元格/条 工具 ====================

def _dim_row(name: str, cells_html: str) -> str:
    return (
        f'<table class="dim-row" width="100%" cellpadding="0" cellspacing="0" border="0">'
        f'<tr><td class="dim-name" valign="top">{name}</td>'
        f'<td class="dim-cells" valign="top">{cells_html}</td></tr></table>'
    )


def _cells(specs) -> str:
    """[(label, value, digits), ...] → cells html，跳过 None。"""
    out = []
    for label, v, d in specs:
        if v is not None:
            out.append(f'<span class="cell"><span class="cl">{label}</span> {v:.{d}f}</span>')
    return "".join(out)


def _bar_html(value: float, max_val: float, width_px: int = 60) -> str:
    """水平 CSS 条（中性灰；红绿由调用方 span class 包裹值）。"""
    if max_val <= 0 or value is None:
        return ""
    pct = min(100, max(0, abs(value) / max_val * 100))
    return f'<span class="bar-track" style="width:{width_px}px;"><span class="bar-fill" style="width:{pct:.0f}%;"></span></span>'


# ==================== 工具 ====================

def _market_flag(market: str) -> str:
    """保留兼容（编辑研报风不用国旗 emoji，恒返回空串）。"""
    return ""


def _trend_class(pct) -> str:
    if pct is None:
        return "stock-neutral"
    return "stock-up" if pct > 0 else ("stock-down" if pct < 0 else "stock-neutral")


def _fmt_pct(v) -> str:
    return f"{v:+.2f}%" if v is not None else "—"


def _fmt_num(v, digits: int = 2) -> str:
    return f"{v:,.{digits}f}" if v is not None else "—"


def _pick_key_signals(r: HoldingResult) -> list[dict]:
    """从各维度挑最强 1-3 个信号，按优先级排序，cap 3。

    Priority (spec §3.3):
      1. insider sell/buy (when direction != flat and net_shares present)
      2. latest rating action (up/down based on grade)
      3. RSI > 70 (down 超买) / < 30 (up 超卖)
      4. MACD golden (up) / dead (down)
      5. dragon-tiger count > 0 (up, CN only)
      6. days_to_next ≤ 7 (warn)
      7. price_target upside_pct > 20 (up)
    """
    sigs: list[dict] = []
    # 1. insider sell/buy
    ins = r.insider or {}
    if ins.get("direction") == "sell" and ins.get("net_shares"):
        sigs.append({"label": f"高管减持 {_fmt_short_money(ins['net_shares'])}股", "cls": "down"})
    elif ins.get("direction") == "buy" and ins.get("net_shares"):
        sigs.append({"label": f"高管增持 {_fmt_short_money(ins['net_shares'])}股", "cls": "up"})
    # 2. latest rating action
    for a in (r.rating.get("actions") or [])[:1]:
        rating_txt = a.get("rating", "") or ""
        cls = "up" if ("买" in rating_txt or "增" in rating_txt) else (
            "down" if ("减" in rating_txt or "卖" in rating_txt) else "up")
        sigs.append({"label": f"评级{rating_txt}", "cls": cls})
    # 3. RSI overbought/oversold
    rsi = (r.technicals or {}).get("rsi")
    if rsi is not None and rsi > 70:
        sigs.append({"label": "RSI超买", "cls": "down"})
    elif rsi is not None and rsi < 30:
        sigs.append({"label": "RSI超卖", "cls": "up"})
    # 4. MACD cross
    macd = (r.technicals or {}).get("macd_cross")
    if macd == "golden":
        sigs.append({"label": "MACD金叉", "cls": "up"})
    elif macd == "dead":
        sigs.append({"label": "MACD死叉", "cls": "down"})
    # 5. dragon-tiger (CN)
    dt = (r.cn_activity or {}).get("dragon_tiger_count", 0)
    if dt:
        sigs.append({"label": f"龙虎榜×{dt}", "cls": "up"})
    # 6. earnings near
    days = (r.events or {}).get("days_to_next")
    if days is not None and days <= 7:
        sigs.append({"label": f"{days}天后财报", "cls": "warn"})
    # 7. price-target upside
    pt = (r.rating.get("price_target") or {}).get("upside_pct")
    if pt is not None and pt > 20:
        sigs.append({"label": f"目标空间{pt:+.0f}%", "cls": "up"})
    return sigs[:3]


def _fmt_short_money(v: float) -> str:
    """数字 → 万/亿 简写。"""
    if v is None:
        return ""
    if abs(v) >= 1e8:
        return f"{v/1e8:.1f}亿"
    if abs(v) >= 1e4:
        return f"{v/1e4:.0f}万"
    return f"{v:.0f}"
