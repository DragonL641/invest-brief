"""风险模型配置（移植自 StockCycleRiskDetector/config.py）。DB_PATH/retry 在 investbrief/config.py。"""

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

# === Indicator Definitions ===
# Common indicators shared by both markets (63% total weight)
COMMON_INDICATORS = {
    "ma50_deviation": {
        "name": "50日均线偏离度",
        "weight": 0.05,
        "category": "technical",
        "thresholds": {"cn": 0.15, "us": 0.15},
        "low_thresholds": {"cn": 0.0, "us": 0.0},
        "description": "(收盘价 - MA50) / MA50",
        "scale": 100,
        "unit": "%",
        "explain": "偏离越大=超买或超卖越重",
    },
    "volume_shrinkage": {
        "name": "成交量萎缩度",
        "weight": 0.04,
        "category": "technical",
        "thresholds": {"cn": 0.7, "us": 0.7},
        "low_thresholds": {"cn": 0.7, "us": 0.7},
        "invert": True,
        "description": "5日均量 / 30日均量",
        "scale": 100,
        "unit": "%",
        "explain": "上涨中缩量=见顶信号",
    },
}

# A-share specific indicators (37% total weight)
CN_INDICATORS = {
    "hsh300_erp": {
        "name": "沪深300 ERP",
        "weight": 0.30,
        "category": "valuation",
        "thresholds": {"cn": 2.0},
        "low_thresholds": {"cn": 5.0},
        "invert": True,
        "description": "(1/沪深300PE) - 10Y国债, 高=股便宜=低风险",
        "scale": 1,
        "unit": "%",
        "explain": "高=股便宜=低风险",
    },
    "zz500_erp": {
        "name": "中证500 ERP",
        "weight": 0.24,
        "category": "valuation",
        "thresholds": {"cn": 0.5},
        "low_thresholds": {"cn": 3.0},
        "invert": True,
        "description": "(1/中证500PE) - 10Y国债, 中小盘成长ERP",
        "scale": 1,
        "unit": "%",
        "explain": "高=中小盘便宜=低风险",
    },
    "structural_divergence": {
        "name": "结构分化(等权/加权PE)",
        "weight": 0.18,
        "category": "valuation",
        "thresholds": {"cn": 2.5},
        "low_thresholds": {"cn": 1.5},
        "description": "沪深300等权PE/加权PE, 高=少数股泡沫(抱团/小盘疯)",
        "scale": 1,
        "unit": "倍",
        "explain": "高=少数股泡沫(抱团)",
    },
    "margin_growth": {
        "name": "融资余额增速",
        "weight": 0.10,
        "category": "liquidity",
        "thresholds": {"cn": 0.15},
        "low_thresholds": {"cn": 0.0},
        "description": "4周融资余额增速, 杠杆加速度(管2015杠杆顶)",
        "scale": 1,
        "unit": "%",
        "explain": "高=杠杆加速冲顶",
    },
    "margin_level": {
        "name": "融资余额水平",
        "weight": 0.09,
        "category": "liquidity",
        "thresholds": {"cn": 20000},
        "low_thresholds": {"cn": 5000},
        "description": "融资余额绝对值分位, 杠杆水平(管2021抱团顶)",
        "scale": 1,
        "unit": "亿",
        "explain": "高=杠杆仓位重",
    },
}

# US stock specific indicators (37% total weight)
US_INDICATORS = {
    "index_pe": {
        "name": "指数PE",
        "weight": 0.31,
        "category": "valuation",
        "thresholds": {"us": 28},
        "low_thresholds": {"us": 15},
        "description": "美股SPY trailing PE",
        "scale": 1,
        "unit": "",
        "explain": "高=估值贵=风险",
    },
    "sp500_erp": {
        "name": "标普500 ERP",
        "weight": 0.15,
        "category": "valuation",
        "thresholds": {"us": 2.0},
        "low_thresholds": {"us": 5.0},
        "invert": True,
        "description": "(1/标普500PE) - 10Y国债, 高=股便宜=低风险(与A股ERP同口径)",
        "scale": 1,
        "unit": "%",
        "explain": "高=股便宜=低风险",
    },
    "credit_spread": {
        "name": "信用利差",
        "weight": 0.20,
        "category": "liquidity",
        "thresholds": {"us": 0.05},  # 5% HYG underperformance
        "low_thresholds": {"us": -0.02},
        "description": "HYG价格相对国债的偏离",
        "scale": 100,
        "unit": "%",
        "explain": "扩大=资金逃风险",
    },
    "yield_curve_inversion": {
        "name": "收益率曲线倒挂",
        "weight": 0.14,
        "category": "macro",
        "thresholds": {"us": 0.5},  # 50bp spread widening after inversion
        "low_thresholds": {"us": -0.5},  # inverted = negative spread
        "description": "10年期 - 3个月期利差",
        "scale": 1,
        "unit": "%",
        "explain": "倒挂(负值)=衰退信号",
    },
    "vix": {
        "name": "VIX恐慌指数",
        "weight": 0.11,
        "category": "sentiment",
        "thresholds": {"us": 30},
        "low_thresholds": {"us": 12},
        "description": "VIX收盘值",
        "scale": 1,
        "unit": "",
        "explain": "高=市场恐慌",
    },
}

# === Gold-specific indicators (轻量版 3 指标, 方案A) ===
GOLD_INDICATORS = {
    "gold_gdp_ratio": {
        "name": "黄金GDP占比",
        "weight": 0.25,
        "category": "valuation",
        "thresholds": {"gold": 15.0},
        "low_thresholds": {"gold": 5.0},
        "description": "全部黄金价值/全球GDP(UP主方法: 全球GDP分母不受单国放水干扰, 均值~9%)",
        "scale": 1,
        "unit": "%",
        "explain": "高=金价相对经济偏高",
    },
    "gold_real_price": {
        "name": "实际金价 z-score",
        "weight": 0.375,
        "category": "valuation",
        "thresholds": {"gold": 2.0},
        "low_thresholds": {"gold": -2.0},
        "description": "金价/CPI 实际金价的历史 z-score",
        "scale": 1,
        "unit": "σ",
        "explain": "高=实际金价偏贵",
    },
    "gold_ma200_deviation": {
        "name": "金价MA200偏离度",
        "weight": 0.375,
        "category": "technical",
        "thresholds": {"gold": 0.30},
        "low_thresholds": {"gold": 0.0},
        "description": "(金价 - MA200) / MA200",
        "scale": 100,
        "unit": "%",
        "explain": "高=超买",
    },
}
GOLD_ALL_INDICATORS = GOLD_INDICATORS

# All indicators per market
CN_ALL_INDICATORS = {**COMMON_INDICATORS, **CN_INDICATORS}
US_ALL_INDICATORS = {**COMMON_INDICATORS, **US_INDICATORS}

# === Five Dimensions for Radar Chart ===
FIVE_DIMENSIONS = {
    "估值风险": {
        "cn": ["hsh300_erp", "zz500_erp", "structural_divergence"],
        "us": ["index_pe", "sp500_erp"],
        "gold": ["gold_gdp_ratio", "gold_real_price"],
    },
    "技术面风险": {
        "cn": ["ma50_deviation", "volume_shrinkage"],
        "us": ["ma50_deviation", "volume_shrinkage"],
        "gold": ["gold_ma200_deviation"],
    },
    "流动性风险": {
        "cn": ["margin_growth", "margin_level"],
        "us": ["credit_spread"],
        "gold": [],
    },
    "情绪面风险": {
        "cn": [],
        "us": ["vix"],
        "gold": [],
    },
    "宏观基本面风险": {
        "cn": [],
        "us": ["yield_curve_inversion"],
        "gold": [],
    },
}

# === Backtest Signal Thresholds ===
BACKTEST_BUY_THRESHOLD = 20   # score below this = buy signal
BACKTEST_SELL_THRESHOLD = 70  # score above this = sell signal
BACKTEST_EVALUATION_WINDOW = 63  # trading days (~3 months) for subsequent return
