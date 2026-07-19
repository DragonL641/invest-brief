"""风险卡片 HTML 渲染 helper (P4-T1)。

将 RiskModel.calculate_score() 的输出渲染为可嵌入邮件的 HTML 片段。
- render_risk_card: 紧凑内联子卡片, 用于 cn/us 板块底部 / 黄金板块内部
- render_gold_section: 黄金独立 section (黄金无 market-data provider, 需自带 header)

颜色语义 = 风险语义 (高分=红=危险, 低分=绿=安全), 与价格涨跌的颜色约定相反。
"""
from __future__ import annotations

from investbrief.risk.config import (
    CN_ALL_INDICATORS,
    GOLD_ALL_INDICATORS,
)
# 辅助灰（与 mail 设计系统 INK_3 同色 #8b95a3）；risk 域自包含, 不跨域 import mail（域边界不变量）
INK_3 = "#8b95a3"


# === Indicator metadata: key → {name, scale, unit, explain, description, thresholds} ===
_INDICATOR_META = {}
for _d in (CN_ALL_INDICATORS, GOLD_ALL_INDICATORS):
    for _k, _v in _d.items():
        _INDICATOR_META[_k] = {
            "name": _v.get("name", _k),
            "scale": _v.get("scale", 1.0),
            "unit": _v.get("unit", ""),
            "explain": _v.get("explain", ""),
            "description": _v.get("description", ""),
            "thresholds": _v.get("thresholds", {}),
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


def _pct_label(pct) -> str:
    """percentile → 高位/中位/低位 label. None -> ''."""
    if pct is None:
        return ""
    try:
        p = float(pct)
    except (TypeError, ValueError):
        return ""
    if p >= 67:
        return "高位"
    if p >= 33:
        return "中位"
    return "低位"


def render_risk_card(score_data: dict) -> str:
    """渲染紧凑内联风险子卡片 HTML 片段。

    嵌入 market section (cn/us) 底部或 gold section 内部。
    显示: 📈 周期风险 标签 + 大号彩色分数 + 状态·操作 + 指标 2-line 详情
    (value/警戒/历史分位 + explain/算法)。指标仅渲染 value 非 None 的, 按分数降序。
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
    market = score_data.get("market") or ""

    # 收集 value 非 None 的指标, 按分数降序 (None 最后)
    items = []
    for key, ind in (score_data.get("indicators") or {}).items():
        if not isinstance(ind, dict) or ind.get("value") is None:
            continue
        ind_score = ind.get("score")
        try:
            ind_score_f = float(ind_score) if ind_score is not None else None
        except (TypeError, ValueError):
            ind_score_f = None
        items.append((key, ind, ind_score_f))
    items.sort(
        key=lambda t: (t[2] is None, -(t[2] if t[2] is not None else 0.0))
    )

    # 每条指标 2-line block
    indicators_html = ""
    for key, ind, ind_score_f in items:
        ind_color = _risk_color(ind_score_f * 10) if ind_score_f is not None else INK_3
        meta = _INDICATOR_META.get(
            key,
            {"name": key, "scale": 1.0, "unit": "", "explain": "",
             "description": "", "thresholds": {}},
        )
        name = meta["name"]
        scale = meta["scale"]
        unit = meta["unit"]
        val_str = _fmt_value(ind.get("value"), scale, unit)
        score_txt = _fmt_num(ind_score_f) if ind_score_f is not None else "-"

        # line 2 parts
        parts = []
        if meta["explain"]:
            parts.append(meta["explain"])
        threshold_raw = meta["thresholds"].get(market) if market else None
        if threshold_raw is not None:
            parts.append(f"警戒 {_fmt_value(threshold_raw, scale, unit)}")
        pct = ind.get("percentile")
        label = _pct_label(pct)
        if label:
            try:
                pct_txt = _fmt_num(float(pct))
            except (TypeError, ValueError):
                pct_txt = "-"
            parts.append(f"历史{label} {pct_txt}%")

        line2 = " · ".join(parts)
        indicators_html += (
            '<div class="ind">'
            '<div class="ind-line">'
            f'<span class="ind-name">{name}</span>'
            f'<span class="ind-val">{val_str}</span>'
            f'<span>→ 风险 <b style="color:{ind_color};">{score_txt}/10</b></span>'
            '</div>'
            f'<div class="ind-explain">{line2}</div>'
            '</div>'
        )

    return (
        '<div class="risk-wrap">'
        '<div class="risk-label">周期风险 · CYCLE RISK</div>'
        '<div class="risk-score-row">'
        f'<span class="risk-score" style="color:{color};">{score_str}</span>'
        '<span class="risk-score-out">/ 100</span>'
        '</div>'
        '<div class="risk-state">'
        f'<b style="color:{color};">{state}</b>'
        + (f' · {action}' if action else '')
        + '</div>'
        + indicators_html
        + '</div>'
    )


def render_gold_section(score_data: dict, valuation_html: str = "") -> str:
    """黄金独立 section (黄金无 market-data provider)。

    在 render_risk_card 外面包一层 section + 金色 header, 风格对齐 US/CN country-header。
    valuation_html（黄金估值 card，由 pipeline 通过 data-only 注入）插在 risk card 之前。
    无分数返回 ''。
    """
    if not score_data:
        return ""
    card = render_risk_card(score_data)
    if not card and not valuation_html:
        return ""
    return (
        '<div class="section">'
        '<div class="section-head">'
        '<span class="kicker">GOLD</span>'
        '<h2 class="section-title">黄金市场</h2>'
        '</div>'
        '<div class="card">'
        '<div class="card-body">'
        f'{valuation_html}{card}'
        '</div></div></div>'
    )
