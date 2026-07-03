"""风险卡片 HTML 渲染 helper (P4-T1)。

将 RiskModel.calculate_score() 的输出渲染为可嵌入邮件的 HTML 片段。
- render_risk_card: 紧凑内联子卡片, 用于 cn/us 板块底部 / 黄金板块内部
- render_gold_section: 黄金独立 section (黄金无 market-data provider, 需自带 header)

颜色语义 = 风险语义 (高分=红=危险, 低分=绿=安全), 与价格涨跌的颜色约定相反。
"""
from __future__ import annotations


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


def _fmt_score(score: float) -> str:
    """格式化分数: 整数去掉小数点。"""
    if score == int(score):
        return str(int(score))
    return f"{score:.1f}"


def render_risk_card(score_data: dict) -> str:
    """渲染紧凑内联风险子卡片 HTML 片段。

    嵌入 market section (cn/us) 底部或 gold section 内部。
    显示: 📈 周期风险 标签 + 大号彩色分数 + 状态·操作 + 维度 mini-bar + 指标 chips。
    跳过缺失/空维度 (gold 只有 估值/技术)。指标仅渲染 value 非 None 的。
    空/None 输入返回 ''。
    """
    if not score_data:
        return ""
    total_score = score_data.get("total_score")
    if total_score is None:
        return ""

    color = _risk_color(float(total_score))
    score_str = _fmt_score(float(total_score))
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
            f'<span style="margin-left:5px;color:{dim_color};font-weight:600;">{_fmt_score(dim_score_f)}</span>'
            '</div>'
        )

    # 指标 chips (仅 value 非 None)
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
        score_txt = _fmt_score(ind_score_f) if ind_score_f is not None else "-"
        indicators_html += (
            f'<span style="display:inline-block;margin:2px 4px 2px 0;padding:2px 6px;'
            f'background:#ffffff;border:1px solid #e9ecef;border-radius:3px;'
            f'font-size:11px;color:#555;">{key} '
            f'<b style="color:{ind_color};">{score_txt}</b></span>'
        )
    indicators_block = (
        f'<div style="margin-top:6px;">{indicators_html}</div>'
        if indicators_html else ""
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
