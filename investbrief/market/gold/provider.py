"""Gold market provider — 提炼自 pipelines/macro.py 的 gold 特殊分支。

域边界: 不 import risk。gold section HTML(render_gold_section 输出)由 macro.py
pipeline 调算后通过 risk_html 注入, render_section 透传返回。
"""
import logging
from typing import Any

from investbrief.data.gold_data import GoldData
from investbrief.market.base import MarketProvider

logger = logging.getLogger(__name__)


class GoldMarketProvider(MarketProvider):
    market_code = "gold"
    country_name = "黄金"
    flag = "🥇"
    currency = "$"
    # 能力声明: gold 参与风险(单一指标 group), 不参与 regime, news/calendar 为空(继承默认)
    risk_group = "gold"
    supports_regime = False
    data_class = GoldData

    def __init__(self, data: "GoldData | None" = None):
        self.data = data if data is not None else GoldData()

    def refresh(self, force: bool = False):
        """GoldData 无 is_fresh; update_incremental 直调 update_all。失败仅 warn。"""
        try:
            self.data.update_incremental()
        except Exception as e:
            logger.warning(f"Gold data refresh failed, falling back to stored values: {e}")

    # gold 不在大类资产/货币政策的常规 macro 板块, 返回空
    def get_indices(self) -> list[dict[str, Any]]:
        return []

    def get_monetary_policy(self) -> dict[str, Any]:
        return {}

    def get_asset_performance(self) -> list[dict[str, Any]]:
        return []

    def render_section(self, data: dict[str, Any], config: dict[str, Any], *,
                       risk_html: str = "", **kwargs) -> str:
        """gold 是轻量市场: section = pipeline 注入的 gold risk section。

        不 import risk —— render_gold_section 由 macro.py pipeline(Task 18)调算后,
        通过 risk_html 参数注入, 本方法透传返回。
        """
        return risk_html
