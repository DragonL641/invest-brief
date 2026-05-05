"""A股行业配置映射。"""

# 行业标签（用于邮件展示）
INDUSTRY_LABELS: dict[str, str] = {
    "semiconductor": "半导体",
    "new_energy": "新能源",
    "consumption": "消费/金融",
    "ai_digital": "AI/数字经济",
}

# AKShare 板块名称映射（用于行业成分股 API 查询）
INDUSTRY_SECTOR_NAMES: dict[str, str] = {
    "semiconductor": "半导体",
    "new_energy": "光伏设备",
    "consumption": "白酒",
    "ai_digital": "软件开发",
}
