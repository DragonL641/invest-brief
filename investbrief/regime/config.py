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

# 象限切换确认期(无状态回看)——按市场数据频率区分
# CN GDP 季度(一年 4 个)稀疏 → RUNS=1:不额外回看(季度本就稳,RUNS=2 会让拐点延迟 6-9 月)
# US 数据月度密 → RUNS=2:回看 1 期重判,去单期噪音
SWITCH_CONFIRMATION_RUNS_CN = 1
SWITCH_CONFIRMATION_RUNS_US = 2

# 方向投票窗口(按指标频率适配)
VOTE_WINDOW_MONTHLY = 3           # CPI / US-GDP(月度) / CN-信用(M2/社融月度)
VOTE_WINDOW_QUARTERLY = 2         # CN-GDP(季度)

# GDP 绝对值→同比的偏移周期(一年期数)
GDP_PERIOD_CN = 4   # 季度
GDP_PERIOD_US = 12  # 月度

# CN 信用信号(GDP 的领先指标):M2 同比 + 社融增量。
# - M2_YOY 已是同比%,直接投票
# - SOCIAL_FIN 是月度流量(强季节性,1月巨量),需 YoY 去季节性(period=12)
# 仅 CN;US M2 是绝对值且无等价社融,不加。
CREDIT_INDICATORS_CN = ("M2_YOY", "SOCIAL_FIN")
CREDIT_PERIOD_CN = 12  # SOCIAL_FIN 月度流量 → YoY 偏移(一年期数);M2_YOY 已同比不受影响

# macro_data 表 indicator key(对齐 data/ 层 cn_data.py / us_data.py)
GROWTH_INDICATOR = "GDP"
INFLATION_INDICATOR = "CPI"
