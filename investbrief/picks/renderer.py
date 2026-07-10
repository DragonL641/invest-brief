# investbrief/picks/renderer.py
"""picks 卡片/段落 HTML(注入 email_picks.j2 的 picks_sections)。

卡片信息密度参考 holdings 邮件:量化因子分项 + 基本面 + 技术面 + 关键信号 + 具体买入逻辑。
买入逻辑用实际指标值解释(不只"前 X%")。段落内两只标的上下堆叠(手机友好)。
"""
from __future__ import annotations

from investbrief.picks.factors import FACTOR_LABELS
from investbrief.core.textfmt import md_inline as _md

_PROFILE_TITLE = {"swing": "波段 · 2周~3个月", "medium": "中长线 · 3个月~1年", "long": "长线 · 1年~5年+"}
_MARKET_BADGE = {"cn": ("A股", "#e74c3c"), "us": ("美股", "#3498db")}


# ---------- 格式化 ----------
def _fmt(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)


def _pct(v) -> str:  # 小数 0.2479 → "+24.8%" / "-5.0%"
    if v is None:
        return "—"
    try:
        return f"{v*100:+.1f}%" if abs(v) < 1.5 else f"{v:+.1f}%"
    except (TypeError, ValueError):
        return "—"


def _num(v, d=2) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):.{d}f}"
    except (TypeError, ValueError):
        return "—"


def _bar(pct) -> str:
    w = pct if isinstance(pct, (int, float)) else 0
    color = "#27ae60" if (isinstance(pct, (int, float)) and pct >= 70) else (
        "#f39c12" if (isinstance(pct, (int, float)) and pct >= 40) else "#d5dbdb")
    return f'<span class="fbar-track"><span class="fbar-fill" style="width:{w:.0f}%;background:{color};"></span></span>'


def _cell(label, value, cls="") -> str:
    return f'<span class="cell {cls}"><span class="cl">{label}</span>{value}</span>'


def _dim(name: str, cells_html: str) -> str:
    return f'<div class="dim-row"><div class="dim-name">{name}</div><div class="dim-cells">{cells_html}</div></div>'


# ---------- 关键信号 tag ----------
def _signals(pick: dict) -> str:
    t = pick.get("technicals") or {}
    tags = []
    ma = t.get("ma_alignment")
    if ma == "bullish":
        tags.append(("均线多头", "up"))
    elif ma == "bearish":
        tags.append(("均线空头", "down"))
    rsi = t.get("rsi")
    if isinstance(rsi, (int, float)):
        if rsi >= 70:
            tags.append(("RSI超买", "warn"))
        elif rsi <= 30:
            tags.append(("RSI超卖", "up"))
    cross = t.get("macd_cross")
    if cross == "golden":
        tags.append(("MACD金叉", "up"))
    elif cross == "death":
        tags.append(("MACD死叉", "down"))
    r20 = t.get("return_20d")
    if isinstance(r20, (int, float)):
        if r20 >= 10:
            tags.append((f"20日+{r20:.0f}%", "up"))
        elif r20 <= -10:
            tags.append((f"20日{r20:.0f}%", "down"))
    if not tags:
        return ""
    return '<div class="signal-row">' + "".join(
        f'<span class="signal-tag tag-{cls}">{txt}</span>' for txt, cls in tags) + '</div>'


# ---------- 量化因子行 ----------
def _factor_dim(pick: dict) -> str:
    fs = pick.get("factor_scores") or {}
    cells = []
    for k, sc in fs.items():
        label = FACTOR_LABELS.get(k, k)
        pct = sc.get("pct")
        pct_disp = f"{pct:.0f}%" if isinstance(pct, (int, float)) else "—"
        cells.append(f'<span class="cell">{label}{_bar(pct)}<span style="color:#95a5a6;font-size:11px;">{pct_disp}</span></span>')
    return _dim("量化因子", "".join(cells)) if cells else ""


# ---------- 基本面 / 技术面 / 价位 维度 ----------
def _fundamentals_dim(pick: dict) -> str:
    f = pick.get("fundamentals") or {}
    cells = [
        _cell("PE", _num(f.get("pe"))),
        _cell("PB", _num(f.get("pb"))),
        _cell("ROE", _pct(f.get("roe"))),
        _cell("毛利率", _pct(f.get("gross_margin"))),
        _cell("营收", _pct(f.get("revenue_yoy"))),
        _cell("净利", _pct(f.get("profit_yoy"))),
    ]
    return _dim("基本面", "".join(cells))


def _technicals_dim(pick: dict) -> str:
    t = pick.get("technicals") or {}
    align = {"bullish": "多头", "bearish": "空头", "mixed": "交织"}.get(t.get("ma_alignment"), "—")
    _mc = t.get("macd_cross")
    _mb = t.get("macd_bar")
    if _mc == "golden":
        cross = "金叉"
    elif _mc == "death":
        cross = "死叉"
    elif isinstance(_mb, (int, float)):
        cross = "红柱" if _mb > 0 else "绿柱"
    else:
        cross = "—"
    cells = [
        _cell("MA20", _num(t.get("ma20"))),
        _cell("MA60", _num(t.get("ma60"))),
        _cell("MA120", _num(t.get("ma120"))),
        _cell("均线", align),
        _cell("RSI", _num(t.get("rsi"))),
        _cell("MACD", cross),
        _cell("5日", _pct((t.get("return_5d") or 0) / 100 if isinstance(t.get("return_5d"), (int, float)) else None)),
        _cell("60日", _pct((t.get("return_60d") or 0) / 100 if isinstance(t.get("return_60d"), (int, float)) else None)),
    ]
    return _dim("技术面", "".join(cells))


# ---------- 机构态度 / 盈利预测(复用 holdings analyzer 数据) ----------
def _rating_dim(pick: dict) -> str:
    rt = pick.get("rating") or {}
    if not rt or not (rt.get("distribution") or rt.get("price_target")):
        return ""
    cells = []
    dist = rt.get("distribution") or {}
    if dist:
        total = rt.get("total") or sum(dist.values()) or 1
        buy_pct = (dist.get("buy", 0) + dist.get("strong_buy", 0) + dist.get("outperform", 0)) / total * 100
        cells.append(_cell("买入共识", f"{buy_pct:.0f}%"))
    pt = rt.get("price_target") or {}
    if pt.get("upside_pct") is not None:
        cls = "pos" if pt["upside_pct"] > 0 else "neg"
        cells.append(_cell("目标空间", f"{pt['upside_pct']:+.0f}%", cls))
    return _dim("机构态度", "".join(cells)) if cells else ""


def _forecast_dim(pick: dict) -> str:
    fc = pick.get("forecast") or {}
    if not fc or fc.get("eps_next") is None:
        return ""
    cells = [_cell("下季EPS", _num(fc.get("eps_next")))]
    if fc.get("yoy_pct") is not None:
        cls = "pos" if fc["yoy_pct"] > 0 else "neg"
        cells.append(_cell("同比", f"{fc['yoy_pct']:+.0f}%", cls))
    return _dim("盈利预测", "".join(cells))


# ---------- 具体买入逻辑(用实际指标值解释,不只"前 X%") ----------
def _explain(pick: dict) -> list[str]:
    """对头部因子(贡献最大的几项)用实际指标值生成具体解释。"""
    t = pick.get("technicals") or {}
    f = pick.get("fundamentals") or {}
    fs = pick.get("factor_scores") or {}
    price = pick.get("price")
    ma60 = t.get("ma60")
    align_cn = {"bullish": "MA20>MA60>MA120 多头排列", "bearish": "MA20<MA60<MA120 空头排列"}.get(t.get("ma_alignment"), "")

    # 按贡献排序,取前 4 个有数据的因子逐条解释
    ordered = sorted(fs.items(), key=lambda kv: (kv[1].get("weighted") or 0), reverse=True)[:4]
    lines = []
    for key, sc in ordered:
        raw = sc.get("raw")
        label = FACTOR_LABELS.get(key, key)
        if key == "trend_strength":
            dev = t.get("close_vs_ma60_pct")
            extra = f",收盘{_fmt(price)}高于MA60 {_fmt(ma60)}({_ret(dev)})"
            if align_cn:
                extra += f",{align_cn}"
            lines.append(f"{label}:趋势强{extra}")
        elif key == "momentum_60d_ex5":
            lines.append(f"{label}:60日涨幅(剔除最近5日){_ret(raw)}")
        elif key == "ma20_deviation":
            lines.append(f"{label}:距MA20乖离 {_ret(raw)},贴近均线属低吸位置")
        elif key == "volume_price":
            vp = f"{raw:.2f}倍" if isinstance(raw, (int, float)) else "—"
            lines.append(f"{label}:放量上涨日均量/缩量回调日均量 = {vp},量能配合向上")
        elif key == "low_volatility_20d":
            lines.append(f"{label}:20日波动率 {_num(raw,4)},池内偏低更稳健")
        elif key == "growth":
            lines.append(f"{label}:营收同比 {_pct(f.get('revenue_yoy'))},净利润同比 {_pct(f.get('profit_yoy'))}")
        elif key == "quality":
            lines.append(f"{label}:ROE {_pct(f.get('roe'))},毛利率 {_pct(f.get('gross_margin'))},经营现金流为正" if f.get("fcf_positive") else f"{label}:ROE {_pct(f.get('roe'))},毛利率 {_pct(f.get('gross_margin'))}")
        elif key == "valuation":
            lines.append(f"{label}:PE {_num(f.get('pe'))} / PB {_num(f.get('pb'))},池内估值偏低")
        elif key == "moat":
            lines.append(f"{label}:毛利率 {_pct(f.get('gross_margin'))},轻资产(低资本开支)特征")
        elif key == "industry_prosperity":
            lines.append(f"{label}:营收增速 {_pct(f.get('revenue_yoy'))}(行业景气代理)")
        elif key == "momentum_12m_ex1m":
            lines.append(f"{label}:12月动量(剔除最近1月){_ret(raw)}")
        else:
            if isinstance(raw, (int, float)):
                lines.append(f"{label}:{_fmt_raw(raw)}(池内前 ...%)")
    return lines


def _fmt_raw(v) -> str:
    """因子原始值展示:小数(比例)→ 百分比,否则 2 位小数。"""
    if v is None:
        return "—"
    if isinstance(v, (int, float)) and abs(v) < 1.5:
        return f"{v*100:+.1f}%"
    return _fmt(v)


def _ret(v) -> str:
    """收益比例(0.0237 → '+2.4%',2.37 → '+237.0%')。用于动量/乖离等 return-ratio 因子。"""
    if not isinstance(v, (int, float)):
        return "—"
    return f"{v*100:+.1f}%"


# ---------- 卡片 ----------
def render_pick_card(pick: dict | None, profile: str = "", market: str = "") -> str:
    if pick is None:
        mkt = _MARKET_BADGE.get(market, ("", ""))[0]
        return f'<div class="card empty">{mkt}本期无符合条件标的</div>'
    mkt_label, mkt_color = _MARKET_BADGE.get(pick.get("market"), ("", "#95a5a6"))
    comp = pick.get("composite", 0)

    dims = "".join(d for d in [
        _factor_dim(pick),
        _fundamentals_dim(pick),
        _technicals_dim(pick),
        _rating_dim(pick),
        _forecast_dim(pick),
    ] if d)
    sig = _signals(pick)
    logic_lines = _explain(pick)
    logic_html = ""
    if logic_lines:
        items = "".join(f"<li>{x}</li>" for x in logic_lines)
        logic_html = f'<div class="logic-box"><b>买入逻辑</b><ul>{items}</ul></div>'
    ai = pick.get("ai_conclusion")
    ai_html = f'<div class="logic-box" style="background:#f8f9fa;border-left-color:#1f3a5f;color:#2c3e50;"><b>🤖 综合研判</b><div style="margin-top:4px;">{_md(ai)}</div></div>' if ai else ""

    kl = pick.get("key_levels") or {}
    price_row = f'''<div class="price-row">
<span class="pl"><span class="pl-l">现价</span><b>{_fmt(pick.get("price"))}</b></span>
<span class="pl neg"><span class="pl-l">压力</span>{_fmt(kl.get("resistance"))}</span>
<span class="pl pos"><span class="pl-l">支撑</span>{_fmt(kl.get("support"))}</span>
<span class="pl neg"><span class="pl-l">止损</span>{_fmt(pick.get("stop_level"))}</span>
</div>'''

    return f'''<div class="card" style="border-left-color:{mkt_color};">
  <div class="card-head">
    <span class="card-name">{pick.get("name","")}</span><span class="card-sym">{pick.get("symbol","")}</span><span class="mkt-badge" style="background:{mkt_color};">{mkt_label}</span>
    <span style="float:right;color:#95a5a6;font-size:11px;">分 {_num(comp,0)}</span>
  </div>
  {price_row}
  <div class="card-body">
    {sig}
    <div class="dims">{dims}</div>
    {logic_html}
    {ai_html}
  </div>
</div>'''


def render_pick_section(profile: str, cn_pick: dict | None, us_pick: dict | None) -> str:
    """同周期 A股+美股 两只【上下堆叠】(手机友好,不再左右排布)。"""
    title = _PROFILE_TITLE.get(profile, profile)
    return f'''<div class="profile-title">{title}</div>
{render_pick_card(cn_pick, profile, "cn")}
{render_pick_card(us_pick, profile, "us")}'''
