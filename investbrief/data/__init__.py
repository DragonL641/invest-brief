"""统一数据层：SQLite 持久化 + 读取。"""
from investbrief.data.base import BaseData
from investbrief.data.cn_data import CNData
from investbrief.data.us_data import USData
from investbrief.data.gold_data import GoldData

__all__ = ["BaseData", "CNData", "USData", "GoldData"]
