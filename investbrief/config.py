"""invest-brief 全局配置常量。

P1 阶段只承载数据层所需；P2 移植风险指标时再扩展指标/阈值配置。
"""
import os
from pathlib import Path

# === Paths ===
BASE_DIR = Path(__file__).resolve().parent.parent  # 项目根
DB_PATH = os.environ.get(
    "INVESTBRIEF_DB_PATH",
    str(BASE_DIR / "data" / "macro_data.db"),
)

# === API Settings（移植自风险模型，供 BaseData._retry_api 使用）===
API_RETRY_COUNT = 3
API_RETRY_DELAY = 5  # seconds

# === US GDP 基期（USData._update_gdp 用，移植自风险模型 config.py）===
US_GDP_BASE_YEAR = 2023
US_GDP_BASE_VALUE = 27.36  # 万亿美元
