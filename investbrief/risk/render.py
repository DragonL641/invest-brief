"""风险卡片 HTML 渲染 helper (P4-T1)。

将 RiskModel.calculate_score() 的输出渲染为可嵌入邮件的 HTML 片段。
- render_risk_card: 紧凑内联子卡片, 用于 cn/us 板块底部 / 黄金板块内部
- render_gold_section: 黄金独立 section (黄金无 market-data provider, 需自带 header)

颜色语义 = 风险语义 (高分=红=危险, 低分=绿=安全), 与价格涨跌的颜色约定相反。
"""
from __future__ import annotations

from investbrief.risk.config import (
    CN_ALL_INDICATORS,
    US_ALL_INDICATORS,
    GOLD_ALL_INDICATORS,
)


# === Indicator metadata: key → {name, scale, unit} ===
_INDICATOR_META = {}
for _d in (CN_ALL_INDICATORS, US_ALL_INDICATORS, GOLD_ALL_INDICATORS):
    for _k, _v in _d.items():
        _INDICATOR_META[_k] = {
            "name": _v.get("name", _k),
            "scale": _v.get("scale", 1.0),
            "unit": _v.get("unit", ""),
        }


def _fmt_value(value, scale: float, unit: str) -> str:
    """原始值 × scale，2 位小数 + 单位。"""
    try:
        return f"{float(value) * scale:.2f}{unit}"
    except (TypeError, ValueError):
        return "-"


def _fmt_num(x) -> str:
    """数字格式化: 整数无小数点, 否则最多 2 位小数 (去尾零)。"""
    try:
        f = float(x)
    except (TypeError, ValueError):
        return "-"
    if f == int(f):
        return str(int(f))
    return f"{f:.2f}".rstrip("0").rstrip(".")


def _risk_color(score: float) -> str:
    """风险分 (0-100) → 颜色。高=危险=红, 低=安全=绿。"""
    if score >= 80:
        return "#c0392b"  # 崩盘前夜 deep red
    if score >= 60:
        return "#e74c3c"  # 狂热泡沫 red
    if score >= 40:
        return "#f39c12"  # 乐观扩张 orange
    if score >= 20:
        return "#27ae60"  # 温和常态 green
    return "#16a085"  # 低位 dark green


def render_risk_card(score_data: dict) -> str:
    """渲染紧凑内联风险子卡片 HTML 片段。

    嵌入 market section (cn/us) 底部或 gold section 内部。
    显示: 📈 周期风险 标签 + 大号彩色分数 + 状态·操作 + 维度 mini-bar + 指标详情行。
    跳过缺失/空维度 (gold 只有 估值/技术)。指标仅渲染 value 非 None 的。
    空/None 输入返回 ''。
    """
    if not score_data:
        return ""
    total_score = score_data.get("total_score")
    if total_score is None:
        return ""

    color = _risk_color(float(total_score))
    score_str = _fmt_num(total_score)
    state = score_data.get("state") or ""
    action = score_data.get("action") or ""

    # 维度 mini-bars
    dims_html = ""
    for name, dim_score in (score_data.get("dimensions") or {}).items():
        if dim_score is None:
            continue
        try:
            dim_score_f = float(dim_score)
        except (TypeError, ValueError):
            continue
        dim_pct = max(0.0, min(100.0, dim_score_f / 10.0 * 100.0))
        dim_color = _risk_color(dim_score_f * 10)
        dims_html += (
            '<div style="margin-bottom:5px;font-size:12px;color:#555;">'
            f'<span style="display:inline-block;width:84px;vertical-align:middle;">{name}</span>'
            '<span style="display:inline-block;width:90px;height:6px;'
            'background:#e9ecef;border-radius:3px;vertical-align:middle;overflow:hidden;">'
            f'<span style="display:block;width:{dim_pct:.0f}%;height:100%;'
            f'background:{dim_color};"></span></span>'
            f'<span style="margin-left:5px;color:{dim_color};font-weight:600;">{_fmt_num(dim_score_f)}</span>'
            '</div>'
        )

    # 指标详情行 (仅 value 非 None): 名称 · 原始值 → 风险分/10 (· scoring)
    indicators_html = ""
    for key, ind in (score_data.get("indicators") or {}).items():
        if not isinstance(ind, dict) or ind.get("value") is None:
            continue
        ind_score = ind.get("score")
        try:
            ind_score_f = float(ind_score) if ind_score is not None else None
        except (TypeError, ValueError):
            ind_score_f = None
        ind_color = _risk_color(ind_score_f * 10) if ind_score_f is not None else "#7f8c8d"
        meta = _INDICATOR_META.get(key, {"name": key, "scale": 1.0, "unit": ""})
        name = meta["name"]
        val_str = _fmt_value(ind.get("value"), meta["scale"], meta["unit"])
        score_txt = _fmt_num(ind_score_f) if ind_score_f is not None else "-"
        scoring = ind.get("scoring")
        scoring_html = (
            f'<span style="color:#95a5a6;font-weight:400;"> · {scoring}</span>'
            if scoring
            else ""
        )
        indicators_html += (
            '<div style="margin-bottom:4px;font-size:12px;color:#555;line-height:1.4;">'
            f'<span style="display:inline-block;width:96px;vertical-align:top;color:#34495e;">{name}</span>'
            f'<span style="display:inline-block;width:80px;vertical-align:top;">{val_str}</span>'
            f'<span style="vertical-align:top;">→ <b style="color:{ind_color};">{score_txt}/10</b>{scoring_html}</span>'
            '</div>'
        )
    indicators_block = (
        f'<div style="margin-top:6px;">{indicators_html}</div>'
        if indicators_html
        else ""
    )

    return (
        '<div style="margin-top:8px;padding:10px 12px;background:#f8f9fa;'
        'border-radius:8px;border:1px solid #e9ecef;">'
        '<div style="margin-bottom:6px;font-size:12px;color:#7f8c8d;font-weight:600;">'
        '📈 周期风险</div>'
        '<div style="margin-bottom:6px;">'
        f'<span style="font-size:26px;font-weight:700;color:{color};line-height:1;'
        f'vertical-align:middle;">{score_str}</span>'
        '<span style="font-size:12px;color:#95a5a6;margin-left:2px;vertical-align:middle;">/100</span>'
        '</div>'
        f'<div style="margin-bottom:8px;font-size:12px;color:#555;">'
        f'<b style="color:{color};">{state}</b>'
        + (f' · {action}' if action else '')
        + '</div>'
        + dims_html
        + indicators_block
        + '</div>'
    )


def render_gold_section(score_data: dict) -> str:
    """黄金独立 section (黄金无 market-data provider)。

    在 render_risk_card 外面包一层 section + 金色 header, 风格对齐 US/CN country-header。
    无分数返回 ''。
    """
    if not score_data:
        return ""
    card = render_risk_card(score_data)
    if not card:
        return ""
    return (
        '<div class="section">'
        '<div class="country-header" style="background-color:#b8860b; color:#ffffff; '
        'padding:15px 20px; margin-bottom:15px;">'
        '<h3 style="margin:0; font-size:16px; color:#ffffff;">🥇 黄金市场</h3>'
        '</div>'
        '<div class="card">'
        '<div class="card-body" style="padding:15px;">'
        f'{card}'
        '</div></div></div>'
    )
