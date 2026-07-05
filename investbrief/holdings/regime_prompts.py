"""Regime-aware prompt 指导段（方案 A，内置，轻量）。

按单标的 regime 注入 prompt，让 Claude 给出针对性结论。非可调参数，不外置 YAML。
"""

REGIME_PROMPTS = {
    "trending_up": (
        "上升趋势：重点分析趋势延续信号（均线多头支撑、量能温和配合）"
        "与潜在回调风险（短期超买、量价背离）。"
    ),
    "trending_down": (
        "下降趋势：重点分析下行风险（支撑位破位、放量下跌）"
        "与可能的反弹时机（超卖、缩量企稳）。"
    ),
    "volatile": (
        "高波动：重点分析震荡区间（近期高低点）"
        "与方向选择信号（突破/破位、量能异动）。"
    ),
    "sideways": (
        "横盘整理：重点分析区间上下沿（高抛低吸机会）"
        "与突破方向（量能配合、均线收敛）。"
    ),
}


def regime_hint(regime: str | None) -> str:
    """返回 regime 对应的 prompt 指导段；未知/None 返回空串。"""
    if not regime:
        return ""
    return REGIME_PROMPTS.get(regime, "")
