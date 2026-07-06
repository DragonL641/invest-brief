"""Risk indicator 协议 — risk 只认这个接口, 不认任何市场。

各市场在自己目录下实现它(market/<mkt>/indicators.py), pipeline 把实例注入 RiskModel。
"""
from typing import Protocol, runtime_checkable


@runtime_checkable
class Indicator(Protocol):
    """一个 indicator: 输入 data_source + date, 输出 {name: {score, value, ...}}。"""

    def calculate(self, data_source, date: str | None = None) -> dict[str, dict]: ...
