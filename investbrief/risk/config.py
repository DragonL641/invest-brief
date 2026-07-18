"""风险模型配置（移植自 StockCycleRiskDetector/config.py）。DB_PATH/retry 在 investbrief/core/config.py。"""

# === Market State Mapping ===
# Each entry: (score_min, score_max, state, crash_prob, expected_return, action)
# 注: crash_prob/expected_return 是历史分位对应的风险强度/收益区间参考, 非预测概率
#     (见 docs/methodology.html「这套方法做不到什么」: 跟踪≠预测)
MARKET_STATE_MAP = [
    (0, 10, "绝望冰点", "<1%", ">30%", "大胆满仓，越跌越买"),
    (10, 20, "信心恢复", "<5%", "15%-30%", "满仓持有，分批加仓"),
    (20, 40, "温和常态", "5%-15%", "8%-15%", "正常持仓，持有为主"),
    (40, 60, "乐观扩张", "15%-40%", "0%-8%", "逐步减仓至5成"),
    (60, 80, "狂热泡沫", "40%-70%", "-10%-0%", "大幅减仓至2成以下"),
    (80, 100, "崩盘前夜", ">70%", "<-30%", "清仓离场，现金为王"),
]

from investbrief.core.strategy_loader import load_strategy

_INDICATORS = load_strategy("risk_indicators")
COMMON_INDICATORS = _INDICATORS["common"]
CN_INDICATORS = _INDICATORS["cn"]  # 仍被 tests/test_risk_config.py 引用


def load_indicators(group: str) -> dict:
    """统一入口: 按 risk_group 名取该市场的全部 indicator 配置。

    cn 合并 common; gold 不含 common。未知 group 返回 {}。
    """
    if group == "gold":
        return _INDICATORS.get("gold", {})
    if group == "cn":
        return {**COMMON_INDICATORS, **_INDICATORS.get(group, {})}
    return {}


# 长期保留: risk/render.py 的 NAME_MAP 等仍按市场引用这些别名
CN_ALL_INDICATORS = load_indicators("cn")
GOLD_ALL_INDICATORS = load_indicators("gold")

# === Five Dimensions for Radar Chart ===
FIVE_DIMENSIONS = {
    "估值风险": {
        "cn": ["broad_erp", "structural_divergence"],
        "gold": ["gold_gdp_ratio", "gold_real_price"],
    },
    "技术面风险": {
        "cn": ["ma50_deviation", "volume_shrinkage"],
        "gold": ["gold_ma200_deviation"],
    },
    "流动性风险": {
        "cn": ["margin_growth", "margin_level"],
        "gold": [],
    },
    "情绪面风险": {
        "cn": ["market_breadth"],
        "gold": [],
    },
    "宏观基本面风险": {
        "cn": ["cpi_cycle"],
        "gold": ["real_yield"],
    },
}

# === Backtest Signal Thresholds ===
BACKTEST_BUY_THRESHOLD = 20   # score below this = buy signal
BACKTEST_SELL_THRESHOLD = 70  # score above this = sell signal
BACKTEST_EVALUATION_WINDOW = 63  # trading days (~3 months) for subsequent return

# === Risk Level Mapping ===
# state（绝望冰点/狂热泡沫...）用于报告渲染（人读）；risk_level（low/moderate/high/extreme）
# 用于决策分支 / Claude prompt / 未来告警阈值。两套口径分离。
RISK_LEVEL_MAP = [
    (0, 20, "low"),        # 绝望冰点 / 信心恢复
    (20, 40, "moderate"),  # 温和常态
    (40, 70, "high"),      # 乐观扩张
    (70, 101, "extreme"),  # 狂热泡沫 / 崩盘前夜
]


def score_to_risk_level(score: float) -> str:
    """0-100 分 → low/moderate/high/extreme。超出范围 clamp 到 moderate。"""
    for lo, hi, level in RISK_LEVEL_MAP:
        if lo <= score < hi:
            return level
    return "moderate"
