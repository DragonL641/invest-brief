"""US industry classifications based on GICS (Global Industry Classification Standard)."""

US_GICS_SECTORS = [
    {"key": "energy", "label": "能源"},
    {"key": "materials", "label": "原材料"},
    {"key": "industrials", "label": "工业"},
    {"key": "consumer_discretionary", "label": "非必需消费品"},
    {"key": "consumer_staples", "label": "必需消费品"},
    {"key": "health_care", "label": "医疗保健"},
    {"key": "financials", "label": "金融"},
    {"key": "information_technology", "label": "信息技术"},
    {"key": "communication_services", "label": "通信服务"},
    {"key": "utilities", "label": "公用事业"},
    {"key": "real_estate", "label": "房地产"},
]

# Migration from old custom industry keys to GICS sectors
US_INDUSTRIES_MIGRATION = {
    "semiconductor_ai": "information_technology",
    "aerospace_defense": "industrials",
    "e_commerce": "consumer_discretionary",
    "software_cloud": "information_technology",
    "ev_automotive": "consumer_discretionary",
    "machinery": "industrials",
    "education": "consumer_discretionary",
}
