"""经济环境四象限 2×2 矩阵卡片渲染。

嵌入 US/CN market section 底部,独占一行。当前象限高亮(主题蓝)。
配色不使用涨跌红绿,避免和 P4 风险色冲突(只用"当前 vs 非当前"二态)。
"""
from __future__ import annotations

# 四象限在 2×2 矩阵的位置:
#   row 0 = 增长↑, row 1 = 增长↓
#   col 0 = 通胀↓, col 1 = 通胀↑
# 每格:(name, favors)
_CELLS = [
    [("繁荣", "股票"), ("通胀", "商品")],   # row 0: 增长↑
    [("通缩", "债券"), ("滞胀", "现金")],   # row 1: 增长↓
]


def _cell(name: str, favors: str, is_current: bool) -> str:
    cls = "regime-cell regime-cell-current" if is_current else "regime-cell"
    star = '<span class="regime-star">★</span>' if is_current else ""
    return (
        f'<td class="{cls}">'
        f'<div class="regime-name">{name}{star}</div>'
        f'<div class="regime-favors">占优 · {favors}</div>'
        f'</td>'
    )


def render_regime_card(data: dict) -> str:
    """渲染 2×2 四象限矩阵卡片 HTML 片段。

    空/None/quadrant 为空 → 返回 ''(pipeline 不阻塞)。
    """
    if not data or not data.get("quadrant"):
        return ""

    current = data["quadrant"]
    confidence = data.get("confidence", 0)
    growth_label = data.get("growth_axis", "信号不足")
    inflation_label = data.get("inflation_axis", "信号不足")
    credit_label = data.get("credit_axis")  # None(US,无信用轴)/"扩张"/"放缓"/"未知"
    inds = data.get("indicators") or {}

    # 构造 2×2 表格(带行/列标签)
    rows_html = ""
    for row_idx, row_cells in enumerate(_CELLS):
        growth_tag = "增长 ↑" if row_idx == 0 else "增长 ↓"
        cells = "".join(_cell(name, favors, name == current) for name, favors in row_cells)
        rows_html += (
            f'<tr><td class="regime-axis">{growth_tag}</td>{cells}</tr>'
        )

    # 判定依据行
    parts = [f'当前 <b>{current}</b> · 置信度 {confidence}%']
    if "GDP_YOY" in inds:
        try:
            parts.append(f'GDP同比 {inds["GDP_YOY"]:+.1f}% · 增长{growth_label}')
        except (TypeError, ValueError):
            parts.append(f'GDP同比 {inds["GDP_YOY"]} · 增长{growth_label}')
    if "CPI_LATEST" in inds:
        try:
            parts.append(f'CPI同比 {inds["CPI_LATEST"]:.1f}% · 通胀{inflation_label}')
        except (TypeError, ValueError):
            parts.append(f'CPI同比 {inds["CPI_LATEST"]} · 通胀{inflation_label}')
    # CN 信用轴(M2+社融,growth 领先指标);US credit_label=None 不显示
    # SOCIAL_FIN 是月度流量(亿),单点值太噪不展示;只展示 M2 同比作具体读数
    if credit_label:
        credit_bits = [f"信用{credit_label}"]
        m2 = inds.get("M2_YOY")
        if isinstance(m2, (int, float)):
            credit_bits.append(f"M2同比 {m2:.1f}%")
        parts.append(" · ".join(credit_bits))
    basis = " · ".join(parts)

    return (
        '<div class="regime-wrap">'
        '<div class="regime-label">宏观环境四象限 · REGIME</div>'
        '<table class="regime-table">'
        '<tr><td></td>'
        '<td class="regime-col-head">通胀 ↓</td>'
        '<td class="regime-col-head">通胀 ↑</td></tr>'
        f'{rows_html}'
        '</table>'
        f'<div class="regime-basis">{basis}</div>'
        '</div>'
    )
