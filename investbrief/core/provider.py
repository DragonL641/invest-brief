"""Market provider abstract base class."""

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class MarketProvider(ABC):
    """各市场数据获取和渲染的统一接口。"""

    market_code: str = ""
    country_name: str = ""
    currency: str = "$"

    @abstractmethod
    def get_indices(self) -> list[dict[str, Any]]:
        """获取主要指数行情。"""

    @abstractmethod
    def get_holdings_data(self, holdings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """获取持仓个股详情。"""

    @abstractmethod
    def get_recommendations(self, industries: list[str], exclude: list[str] | None = None) -> list[dict[str, Any]]:
        """按行业获取推荐关注个股。"""

    @abstractmethod
    def fetch_all(self, holdings: list[dict], industries: list[str]) -> dict[str, Any]:
        """获取该市场全部数据，返回供 report 使用的 dict。"""

    @abstractmethod
    def render_section(self, data: dict[str, Any], config: dict[str, Any]) -> str:
        """渲染该市场的 HTML 区块。"""
