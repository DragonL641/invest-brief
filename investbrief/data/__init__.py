"""统一数据层：SQLite 持久化 + 读取。"""
from investbrief.data.base import BaseData

__all__ = ["BaseData"]
# CNData/USData 在各自 Task 中加入导出
