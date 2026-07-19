"""黄金估值信号 card：TIPS 实际利率（10年分位）+ 金价 vs 开采成本 AISC（14年分位 + 溢价）。

DB-First 读 macro_data；任一指标缺失 → 对应行不渲染（诚实缺省，不 fallback）。
两行均缺 → 整 card 返回空串（pipeline 不注入）。
"""
import logging

logger = logging.getLogger(__name__)


def fetch_gold_valuation(data_source, config) -> dict:
    """返回 {tips_yield, tips_pct_10y, aisc, aisc_pct_14y, gold_price, premium_pct}。

    缺失项为 None。premium 仅在 gold_price 与 aisc 都有值时计算。
    """
    tips = data_source.latest_macro("REAL_YIELD_10Y", "us")
    tips_pct = data_source.latest_percentile("REAL_YIELD_10Y", "us", 10)
    aisc = data_source.latest_macro("GOLD_AISC", "global")
    aisc_pct = data_source.latest_percentile("GOLD_AISC", "global", 14)  # 2012 起 14 年
    gold_price = data_source.latest_macro("GOLD_PRICE", "global")
    premium = None
    if gold_price and aisc and aisc > 0:
        premium = round((gold_price / aisc - 1) * 100, 1)
    return {
        "tips_yield": tips, "tips_pct_10y": tips_pct,
        "aisc": aisc, "aisc_pct_14y": aisc_pct,
        "gold_price": gold_price, "premium_pct": premium,
    }


def _fmt(v, suffix="", spec=".2f") -> str:
    return f"{v:{spec}}{suffix}" if isinstance(v, (int, float)) else "-"


def render_gold_valuation_card(valuation: dict) -> str:
    """渲染黄金估值 card。两行均缺 → 返回 ''。"""
    if not valuation:
        return ""
    tips = valuation.get("tips_yield")
    aisc = valuation.get("aisc")
    gold = valuation.get("gold_price")
    premium = valuation.get("premium_pct")

    has_tips = tips is not None
    has_aisc = aisc is not None and gold is not None

    if not has_tips and not has_aisc:
        return ""

    rows = []
    if has_tips:
        tips_pct = valuation.get("tips_pct_10y")
        pct_str = f"，近10年 {tips_pct:.1f}%分位" if isinstance(tips_pct, (int, float)) else ""
        rows.append(
            f'<div class="ind-line"><span class="ind-name">实际利率 TIPS</span>'
            f'<span class="ind-val">{_fmt(tips, "%")}</span>'
            f'<span class="ind-explain">{pct_str.lstrip("，")}</span></div>'
        )
    if has_aisc:
        aisc_pct = valuation.get("aisc_pct_14y")
        pct_str = f"，成本近14年 {aisc_pct:.1f}%分位" if isinstance(aisc_pct, (int, float)) else ""
        rows.append(
            f'<div class="ind-line"><span class="ind-name">金价 vs 开采成本</span>'
            f'<span class="ind-val">溢价 {_fmt(premium, "%", spec=".1f")}</span>'
            f'<span class="ind-explain">金价 ${gold:,.0f} / AISC ${aisc:,.0f}{pct_str}</span></div>'
        )

    return (
        '<div class="card"><div class="card-head">黄金估值信号</div>'
        '<div class="card-body">'
        + "".join(rows) +
        '</div></div>'
    )
