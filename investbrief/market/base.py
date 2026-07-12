"""Market provider abstract base class."""

from abc import ABC, abstractmethod
from typing import Any

from investbrief.data.base import BaseData


class MarketProvider(ABC):
    """各市场数据获取和渲染的统一接口。"""

    market_code: str = ""
    country_name: str = ""
    currency: str = "$"

    # —— 能力声明（子类覆盖；None/False = 该市场不具备此能力）——
    risk_group: str | None = None        # risk_indicators.yaml 的 group 名；None = 不参与 risk
    supports_regime: bool = False        # 是否参与 regime 四象限
    data_class: type | None = None       # 该市场的 BaseData 子类

    # data 由子类 __init__ 设置; 声明类型供调用方(macro.py)与 pyright
    data: BaseData | None = None

    @abstractmethod
    def get_indices(self) -> list[dict[str, Any]]:
        """获取主要指数行情。

        返回 ``list[dict]``,每项代表一个指数。CN 是参考实现,每项键集合为
        ``{name, symbol, point, change, change_amt, amount}``:
        ``change`` 为百分比涨跌幅(已 ×100),``change_amt`` 为绝对变动,
        ``amount`` 可为 None。轻量市场(如 gold)可不实现,返回 ``[]``。
        """

    @abstractmethod
    def get_monetary_policy(self) -> dict[str, Any]:
        """货币政策与利率（宏观板块③）。

        返回 ``dict``,键为指标短名、值为数值或 None(指标缺失时必须保留键、值为 None,
        以保证 render 层稳定)。CN 是参考实现,键集合为
        ``{lpr_1y, lpr_5y, m2_yoy, m1_yoy, social_financing, cn_10y_yield, cpi_yoy, gdp_yoy}``。
        轻量市场(如 gold)可不实现,返回 ``{}``。
        """

    @abstractmethod
    def get_asset_performance(self) -> list[dict[str, Any]]:
        """大类资产表现（宏观板块④）。

        返回 ``list[dict]``,每项至少含 ``{name, point, change}``(``change`` 为百分比);
        复用指数行情的市场(如 CN)其指数类项另带 ``symbol/change_amt/amount``。
        轻量市场(如 gold)可不实现,返回 ``[]``。
        """

    @abstractmethod
    def render_section(self, data: dict[str, Any], config: dict[str, Any], **kwargs) -> str:
        """渲染该市场的 HTML 区块。

        ``kwargs`` 用于跨域注入(cross-domain data-only handoff):pipeline 预先调算好
        ``risk_html=``(P4 风险卡片 HTML)与 ``regime_html=``(经济四象限卡片 HTML),
        由本方法嵌入到 section 末尾。``config`` 至少含 ``color_up``/``color_down``
        (CN 红涨绿跌惯例)。轻量市场(如 gold)的 ``render_section`` 可仅透传 ``risk_html``。"""

    def refresh(self, force: bool = False) -> None:
        """增量取数落盘。子类覆盖(US/CN 用 is_fresh 守门, Gold 直调 update)。默认空。"""
        pass

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
