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

    # —— 能力声明（子类覆盖；None/False = 该市场不具备此能力）——
    risk_group: str | None = None        # risk_indicators.yaml 的 group 名；None = 不参与 risk
    supports_regime: bool = False        # 是否参与 regime 四象限
    data_class: type | None = None       # 该市场的 BaseData 子类

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
    def render_section(self, data: dict[str, Any], config: dict[str, Any], **kwargs) -> str:
        """渲染该市场的 HTML 区块。"""

    def get_news(self, config: dict, limit: int) -> list:
        """该市场的新闻列表。默认空，子类覆盖。"""
        return []

    def get_economic_calendar(self) -> list:
        """该市场的经济日历。默认空，子类覆盖。"""
        return []

    def _render_economic_calendar(self, calendar: list[dict]) -> str:
        """渲染经济日历卡片（US/CN 共用，消除两份逐字重复的副本）。"""
        if not calendar:
            return ""
        rows = ""
        for e in calendar:
            importance = e.get("importance", "medium")
            badge_color = "#e74c3c" if importance == "high" else "#f39c12"
            days = e["days_away"]
            rows += f'''
      <tr>
        <td>{e["name"]}</td>
        <td>{e["date"]}</td>
        <td><span style="background:{badge_color}; color:#fff; padding:2px 6px; border-radius:3px; font-size:11px;">{days}天后</span></td>
      </tr>'''
        return f'''
      <div class="card">
        <div class="card-header" style="padding:12px 15px; background:#f8f9fa; border-bottom:1px solid #e9ecef; font-weight:600;">🏛️ 经济日历</div>
        <div class="card-body">
          <table>
<thead><tr><th>事件</th><th>日期</th><th>倒计时</th></tr></thead>
<tbody>{rows}</tbody>
</table>
        </div>
      </div>'''
