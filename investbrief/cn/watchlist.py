"""A股行业关注列表。"""

INDUSTRY_WATCHLISTS: dict[str, list[dict[str, str]]] = {
    "semiconductor": [
        {"symbol": "002049", "name": "紫光国微"},
        {"symbol": "688981", "name": "中芯国际"},
        {"symbol": "603501", "name": "韦尔股份"},
        {"symbol": "300782", "name": "卓胜微"},
        {"symbol": "688012", "name": "中微公司"},
        {"symbol": "002371", "name": "北方华创"},
        {"symbol": "300661", "name": "圣邦股份"},
        {"symbol": "688256", "name": "寒武纪"},
    ],
    "new_energy": [
        {"symbol": "300750", "name": "宁德时代"},
        {"symbol": "002594", "name": "比亚迪"},
        {"symbol": "601012", "name": "隆基绿能"},
        {"symbol": "600438", "name": "通威股份"},
        {"symbol": "002709", "name": "天赐材料"},
        {"symbol": "300014", "name": "亿纬锂能"},
        {"symbol": "600905", "name": "三峡能源"},
    ],
    "consumption": [
        {"symbol": "600519", "name": "贵州茅台"},
        {"symbol": "000858", "name": "五粮液"},
        {"symbol": "000568", "name": "泸州老窖"},
        {"symbol": "600036", "name": "招商银行"},
        {"symbol": "601318", "name": "中国平安"},
        {"symbol": "000651", "name": "格力电器"},
        {"symbol": "600276", "name": "恒瑞医药"},
    ],
    "ai_digital": [
        {"symbol": "002230", "name": "科大讯飞"},
        {"symbol": "688787", "name": "海天瑞声"},
        {"symbol": "603019", "name": "中科曙光"},
        {"symbol": "000977", "name": "浪潮信息"},
        {"symbol": "688111", "name": "金山办公"},
        {"symbol": "300033", "name": "同花顺"},
    ],
}

INDUSTRY_LABELS: dict[str, str] = {
    "semiconductor": "半导体",
    "new_energy": "新能源",
    "consumption": "消费/金融",
    "ai_digital": "AI/数字经济",
}

# AKShare 板块名称映射（用于行业板块行情查询）
INDUSTRY_SECTOR_NAMES: dict[str, str] = {
    "semiconductor": "半导体",
    "new_energy": "光伏设备",
    "consumption": "白酒",
    "ai_digital": "软件开发",
}


def get_watchlist_stocks(industries: list[str]) -> list[dict[str, str]]:
    """获取指定行业的关注股票列表。"""
    result = []
    for industry in industries:
        stocks = INDUSTRY_WATCHLISTS.get(industry, [])
        for s in stocks:
            result.append({**s, "industry": industry})
    return result
