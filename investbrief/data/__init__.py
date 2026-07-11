"""统一数据层：SQLite 持久化 + 读取。"""
from investbrief.data.base import BaseData
from investbrief.data.cn_data import CNData
from investbrief.data.gold_data import GoldData

__all__ = ["BaseData", "CNData", "GoldData", "market_index_spec"]


def market_index_spec(market: str) -> dict:
    """该市场主序列规格(来自各 Data 子类的声明)。

    供 risk models / indicators 按 market 取主指数表与 code,
    取代散落的 `cn_index_daily`/`sh000001` 等硬编码。加市场 = 加一行表项。

    注意: 本函数按 market 字符串查表(不依赖某个 data_source 实例属于哪个市场),
    因为 RiskModel 用单一 data_source 算多市场, 表名选择只能靠 market。
    """
    from investbrief.data.cn_data import CNData
    from investbrief.data.gold_data import GoldData
    specs = {
        "cn": {"kind": "index", "table": CNData.primary_table, "code": CNData.primary_index},
        "gold": {"kind": "macro",
                 "indicator": GoldData.primary_indicator[0],
                 "country": GoldData.primary_indicator[1]},
    }
    if market not in specs:
        raise KeyError(f"Unknown market: {market}. Known: {sorted(specs)}")
    return specs[market]
