"""经济环境四象限配置(Browne 永久投资模型:增长×通胀)。

定位 = 宏观环境参考信号(和 risk/ P4 同款"跟踪≠预测")。
只用 data/ 层已有的 CPI(同比) + GDP(绝对值,引擎自算同比),不依赖 PMI/PPI/核心CPI。
"""

# 象限定义 + 占优资产(卡片标注用)
QUADRANTS = {
    "繁荣": {"growth": "扩张", "inflation": "下行", "favors": "股票"},
    "通胀": {"growth": "扩张", "inflation": "上行", "favors": "商品"},
    "通缩": {"growth": "放缓", "inflation": "下行", "favors": "债券"},
    "滞胀": {"growth": "放缓", "inflation": "上行", "favors": "现金"},
    "中性": {"growth": None, "inflation": None, "favors": None},
}

# 阈值
INFLATION_UP_THRESHOLD = 2.5      # CPI 同比 > 此值且方向投票 up 才算"通胀上行象限"
DIRECTION_VOTE_MIN_AGREEING = 2   # 方向投票:最近 window 个逐期变化里最少一致期数
SWITCH_CONFIRMATION_RUNS = 2      # 象限切换确认期(无状态回看)

# 方向投票窗口(按指标频率适配)
VOTE_WINDOW_MONTHLY = 3           # CPI / US-GDP(月度)
VOTE_WINDOW_QUARTERLY = 2         # CN-GDP(季度)

# GDP 绝对值→同比的偏移周期(一年期数)
GDP_PERIOD_CN = 4   # 季度
GDP_PERIOD_US = 12  # 月度

# macro_data 表 indicator key(对齐 data/ 层 cn_data.py / us_data.py)
GROWTH_INDICATOR = "GDP"
INFLATION_INDICATOR = "CPI"
