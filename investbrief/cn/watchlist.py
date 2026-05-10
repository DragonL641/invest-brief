"""A股行业配置映射。"""

from investbrief.cn.industries import CN_SW_INDUSTRIES

# 行业标签（用于展示）
INDUSTRY_LABELS: dict[str, str] = {s["key"]: s["label"] for s in CN_SW_INDUSTRIES}

# AKShare 板块名称映射（用于行业成分股 API 查询）
# 申万行业 key → 东方财富行业板块名称
INDUSTRY_SECTOR_NAMES: dict[str, str] = {
    "agriculture": "农牧饲渔",
    "coal": "煤炭行业",
    "petrochemical": "石油行业",
    "nonferrous_metals": "有色金属",
    "steel": "钢铁行业",
    "chemicals": "化工行业",
    "electronics": "半导体",
    "home_appliances": "家电行业",
    "food_beverage": "白酒",
    "textile_clothing": "纺织服装",
    "light_manufacturing": "包装印刷",
    "pharmaceuticals": "中药",
    "utilities": "电力行业",
    "transportation": "航运港口",
    "real_estate": "房地产开发",
    "banking": "银行",
    "non_bank_financials": "证券",
    "trade_retail": "商业百货",
    "social_services": "旅游酒店",
    "building_materials": "水泥建材",
    "building_decoration": "装修建材",
    "power_equipment": "光伏设备",
    "defense": "航天航空",
    "computer": "软件开发",
    "media": "游戏",
    "telecom": "通信服务",
    "machinery": "通用设备",
    "environmental": "环保行业",
    "beauty_care": "美容护理",
    "automotive": "汽车整车",
}
