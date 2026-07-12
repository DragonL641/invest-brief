# investbrief/picks/renderer.py
"""picks 卡片/段落 HTML(注入 email_picks.j2 的 picks_sections)。

卡片信息密度参考 holdings 邮件:量化因子分项 + 基本面 + 技术面 + 关键信号 + 具体买入逻辑。
买入逻辑用实际指标值解释(不只"前 X%")。段落内两只标的上下堆叠(手机友好)。
"""
from __future__ import annotations

from investbrief.picks.factors import FACTOR_LABELS
from investbrief.core.textfmt import md_inline as _md

_PROFILE_TITLE = {"swing": "波段 · 2周~3个月", "medium": "中长线 · 3个月~1年", "long": "长线 · 1年~5年+"}
_MARKET_BADGE = {"cn": "A股"}


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


def _chg_cls(v):
    if v is None:
        return ""
    return "pos" if v > 0 else ("neg" if v < 0 else "")


def _fmt_chg(v):
    return f"{v:+.2f}%" if isinstance(v, (int, float)) else "—"


def _num(v, d=2) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):.{d}f}"
    except (TypeError, ValueError):
        return "—"


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
        f'<span class="signal-tag signal-tag-{cls}">{txt}</span>' for txt, cls in tags) + '</div>'


# ---------- 量化因子行(一行一个因子 + 右边解释) ----------
def _factor_dim(pick: dict) -> str:
    fs = pick.get("factor_scores") or {}
    rows = []
    for key, sc in fs.items():
        label = FACTOR_LABELS.get(key, key)
        explain = _explain_factor(key, sc, pick)
        if explain:
            rows.append(
                f'<div class="factor-row"><span class="fl-name">{label}</span>'
                f'<span class="fl-explain">{explain}</span></div>'
            )
    return f'<div class="dim-row"><div class="dim-name">量化因子</div><div class="factor-list">{"".join(rows)}</div></div>' if rows else ""


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
    """技术面按类别分3行:均线 / 动能 / 涨跌。return_*d 是百分数值(core/ta.py:104 *100),
    需 /100 归一化为小数后再 _pct;close_vs_ma60_pct 本身是小数。"""
    t = pick.get("technicals") or {}

    def _to_ret(v):
        # 百分比值(2.1 = 2.1%) → _pct 友好的小数(0.021)
        return v / 100 if isinstance(v, (int, float)) else None

    # 均线类
    align = {"bullish": "多头排列", "bearish": "空头排列", "mixed": "交织"}.get(t.get("ma_alignment"), "—")
    has_ma = any(t.get(k) is not None for k in ("ma20", "ma60", "ma120"))
    ma_cells = ""
    if has_ma:
        ma_cells = "".join([
            _cell("MA20", _num(t.get("ma20"))),
            _cell("MA60", _num(t.get("ma60"))),
            _cell("MA120", _num(t.get("ma120"))),
            _cell("排列", align),
            _cell("距MA60", _pct(t.get("close_vs_ma60_pct"))),
        ])

    # 动能类(macd_cross 缺失时用 macd_bar 红绿柱兜底,不丢信息)
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
    dyn_cells = "".join([
        _cell("RSI", _num(t.get("rsi"))),
        _cell("MACD", cross),
        _cell("量比", _num(t.get("volume_ratio"))),
    ])

    # 涨跌类(return_*d 是百分比值,/100 归一化)
    ret_cells = "".join([
        _cell("5日", _pct(_to_ret(t.get("return_5d")))),
        _cell("20日", _pct(_to_ret(t.get("return_20d")))),
        _cell("60日", _pct(_to_ret(t.get("return_60d")))),
    ])

    rows = "".join(r for r in [
        _dim("均线", ma_cells) if ma_cells else "",
        _dim("动能", dyn_cells),
        _dim("涨跌", ret_cells),
    ] if r)
    return rows


# ---------- 机构态度 / 盈利预测(复用 holdings analyzer 数据) ----------
def _rating_dim(pick: dict) -> str:
    """评级分布详情(各家数+共识+总数) + 目标价详情(均值/最高/最低+空间)。
    distribution key 对齐 holdings analyzer(US: strong_buy/buy/hold/sell/strong_sell;
    CN: buy/outperform/neutral/underperform/sell)。upside_pct 是百分数值(21.2 = 21%),
    需 /100 归一化后 _ret,避免放大成 +2120%。"""
    rt = pick.get("rating") or {}
    if not rt or not (rt.get("distribution") or rt.get("price_target")):
        return ""

    rows = []
    dist = rt.get("distribution") or {}
    if dist:
        total = rt.get("total") or sum(dist.values()) or 1
        buy_n = dist.get("buy", 0) + dist.get("strong_buy", 0) + dist.get("outperform", 0)
        buy_pct = buy_n / total * 100 if total else 0
        # CN/US distribution schema 归并进统一 4 格(避免 CN outperform/neutral/underperform 丢失):
        #   US: strong_buy→强烈买入、buy→买入、hold→持有、sell+strong_sell→卖出
        #   CN: buy→买入、outperform→买入、neutral→持有、underperform+sell→卖出
        dist_cells = "".join([
            _cell("强烈买入", dist.get("strong_buy", 0)),
            _cell("买入",   dist.get("buy", 0) + dist.get("outperform", 0)),
            _cell("持有",   dist.get("hold", 0) + dist.get("neutral", 0)),
            _cell("卖出",   dist.get("sell", 0) + dist.get("strong_sell", 0) + dist.get("underperform", 0)),
            _cell("共识",   f"{buy_pct:.0f}%"),
            _cell("共",     f"{total}家"),
        ])
        rows.append(_dim("评级", dist_cells))

    pt = rt.get("price_target") or {}
    if pt.get("mean") is not None:
        upside = pt.get("upside_pct")
        # upside_pct 是百分数(21.2),/100 → 小数后 _ret → "+21.2%"
        upside_disp = _ret(upside / 100) if isinstance(upside, (int, float)) else "—"
        cls = "pos" if isinstance(upside, (int, float)) and upside > 0 else ("neg" if isinstance(upside, (int, float)) and upside < 0 else "")
        pt_cells = "".join([
            _cell("均值", _num(pt.get("mean"))),
            _cell("最高", _num(pt.get("high"))),
            _cell("最低", _num(pt.get("low"))),
            _cell("空间", upside_disp, cls),
        ])
        rows.append(_dim("目标", pt_cells))

    return "".join(rows) if rows else ""


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
def _explain_factor(key: str, sc: dict, pick: dict) -> str | None:
    """单因子解释文案(实际指标值+含义)。复用原 _explain 的 per-factor 逻辑,
    返回无 label 前缀的解释串(调用方决定是否加前缀)。未知因子返回 None。"""
    t = pick.get("technicals") or {}
    f = pick.get("fundamentals") or {}
    raw = sc.get("raw")
    price = pick.get("price")
    ma60 = t.get("ma60")
    align_cn = {"bullish": "MA20>MA60>MA120 多头排列", "bearish": "MA20<MA60<MA120 空头排列"}.get(t.get("ma_alignment"), "")

    if key == "trend_strength":
        dev = t.get("close_vs_ma60_pct")
        extra = f",收盘{_fmt(price)}高于MA60 {_fmt(ma60)}({_ret(dev)})"
        if align_cn:
            extra += f",{align_cn}"
        return f"趋势强{extra}"
    elif key == "momentum_60d_ex5":
        return f"60日涨幅(剔除最近5日){_ret(raw)}"
    elif key == "ma20_deviation":
        return f"距MA20乖离 {_ret(raw)},贴近均线属低吸位置"
    elif key == "volume_price":
        vp = f"{raw:.2f}倍" if isinstance(raw, (int, float)) else "—"
        return f"放量上涨日均量/缩量回调日均量 = {vp},量能配合向上"
    elif key == "low_volatility_20d":
        return f"20日波动率 {_num(raw,4)},池内偏低更稳健"
    elif key == "growth":
        return f"营收同比 {_pct(f.get('revenue_yoy'))},净利润同比 {_pct(f.get('profit_yoy'))}"
    elif key == "quality":
        base = f"ROE {_pct(f.get('roe'))},毛利率 {_pct(f.get('gross_margin'))}"
        return base + ",经营现金流为正" if f.get("fcf_positive") else base
    elif key == "valuation":
        return f"PE {_num(f.get('pe'))} / PB {_num(f.get('pb'))},池内估值偏低"
    elif key == "moat":
        return f"毛利率 {_pct(f.get('gross_margin'))},轻资产(低资本开支)特征"
    elif key == "industry_prosperity":
        return f"营收增速 {_pct(f.get('revenue_yoy'))}(行业景气代理)"
    elif key == "momentum_12m_ex1m":
        return f"12月动量(剔除最近1月){_ret(raw)}"
    elif key == "profitability_stability":
        return f"连续盈利 {_fmt(raw)} 年"
    elif key == "main_flow":
        if raw is None:
            return None
        return f"近5日主力净流入占比 {_num(raw)}%"
    if isinstance(raw, (int, float)):
        return f"{_fmt_raw(raw)}(池内前 ...%)"
    return None


def _explain(pick: dict) -> list[str]:
    """对头部因子(贡献最大的几项)用实际指标值生成具体解释。"""
    fs = pick.get("factor_scores") or {}
    ordered = sorted(fs.items(), key=lambda kv: (kv[1].get("weighted") or 0), reverse=True)[:4]
    lines = []
    for key, sc in ordered:
        explain = _explain_factor(key, sc, pick)
        if explain:
            label = FACTOR_LABELS.get(key, key)
            lines.append(f"{label}:{explain}")
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
        mkt = _MARKET_BADGE.get(market, "")
        return f'<div class="card empty">{mkt}本期无符合条件标的</div>'
    mkt_label = _MARKET_BADGE.get(pick.get("market"), "")
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
    ai_html = f'<div class="ai-box"><span class="ai-label">综合研判</span>{_md(ai)}</div>' if ai else ""

    kl = pick.get("key_levels") or {}
    price_row = f'''<div class="price-row">
<span class="pl"><span class="pl-l">现价</span><b>{_fmt(pick.get("price"))}</b></span>
<span class="pl {_chg_cls(pick.get('change_pct'))}"><span class="pl-l">涨跌</span>{_fmt_chg(pick.get('change_pct'))}</span>
<span class="pl neg"><span class="pl-l">压力</span>{_fmt(kl.get("resistance"))}</span>
<span class="pl pos"><span class="pl-l">支撑</span>{_fmt(kl.get("support"))}</span>
<span class="pl neg"><span class="pl-l">止损</span>{_fmt(pick.get("stop_level"))}</span>
</div>'''

    return f'''<div class="card">
  <div class="card-head">
    <span class="card-name">{pick.get("name","")}</span><span class="card-sym">{pick.get("symbol","")}</span><span class="mkt-badge">{mkt_label}</span>
    <span class="card-score">分 <b>{_num(comp,0)}</b></span>
  </div>
  {price_row}
  <div class="card-body">
    {sig}
    <div class="dims">{dims}</div>
    {logic_html}
    {ai_html}
  </div>
</div>'''


def render_pick_section(profile: str, pick: dict | None) -> str:
    """单 profile 的 A股 Top1 卡片。"""
    title = _PROFILE_TITLE.get(profile, profile)
    return f'''<div class="profile-title">{title}</div>
{render_pick_card(pick, profile, "cn")}'''
