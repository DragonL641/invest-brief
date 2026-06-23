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
    def get_monetary_policy(self) -> dict[str, Any]:
        """货币政策与利率（宏观板块③）。"""

    @abstractmethod
    def get_asset_performance(self) -> list[dict[str, Any]]:
        """大类资产表现（宏观板块④）。"""

    @abstractmethod
    def get_holdings_data(self, holdings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """获取持仓个股详情。"""

    @abstractmethod
    def get_recommendations(self, industries: list[str], exclude: list[str] | None = None,
                           max_recommendations: int = 3) -> list[dict[str, Any]]:
        """按行业获取推荐关注个股。"""

    @abstractmethod
    def fetch_all(self, holdings: list[dict], industries: list[str],
                 max_recommendations: int = 3) -> dict[str, Any]:
        """获取该市场全部数据，返回供 report 使用的 dict。"""

    @abstractmethod
    def render_section(self, data: dict[str, Any], config: dict[str, Any], **kwargs) -> str:
        """渲染该市场的 HTML 区块。"""
