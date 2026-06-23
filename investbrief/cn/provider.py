"""
A股 Market Provider — AKShare powered (macro view).

Provides macro data: indices, monetary policy, asset performance, economic calendar.
"""

import logging
from typing import Any

from investbrief.core.provider import MarketProvider
from investbrief.cn.client import AKShareClient

logger = logging.getLogger(__name__)


class CNMarketProvider(MarketProvider):
    market_code = "cn"
    country_name = "A股市场"
    currency = "¥"
    flag = "🇨🇳"

    INDEX_SYMBOLS = {
        "上证指数": "000001",
        "深证成指": "399001",
        "创业板指": "399006",
        "沪深300": "000300",
        "科创50": "000688",
    }

    def __init__(self):
        self.client = AKShareClient()

    # ==================== Data Methods ====================

    def get_indices(self) -> list[dict[str, Any]]:
        """获取 A 股主要指数行情。"""
        symbols = list(self.INDEX_SYMBOLS.values())
        names = {s: n for n, s in self.INDEX_SYMBOLS.items()}
        quotes = self.client.get_index_quotes(symbols)
        results = []
        for q in quotes:
            sym = q["symbol"]
            if sym in names:
                results.append({
                    "name": names[sym],
                    "symbol": sym,
                    "point": q["price"],
                    "change": q.get("change_pct"),
                    "change_amt": q.get("change"),
                    "amount": q.get("amount"),
                })
        return results

    def get_monetary_policy(self) -> dict[str, Any]:
        """③ 货币政策与利率：LPR / M2 / M1 / 社融 / 中国10Y国债。"""
        try:
            return self.client.get_cn_monetary_policy()
        except Exception as e:
            logger.warning(f"CN monetary policy failed: {e}")
            return {}

    def get_asset_performance(self) -> list[dict[str, Any]]:
        """④ 大类资产表现：A 股指数 + 人民币汇率。"""
        assets = self.get_indices()
        try:
            fx = self.client.get_fx_rate_usdcny()
            if fx:
                assets.append({
                    "name": "人民币汇率(USDCNY)",
                    "point": fx.get("price"),
                    "change": fx.get("change_pct"),
                })
        except Exception as e:
            logger.warning(f"CN fx rate failed: {e}")
        return assets

    def fetch_all(self) -> dict[str, Any]:
        """获取 A 股宏观数据。"""
        from investbrief.cn.calendar import get_upcoming_events
        return {
            "monetary_policy": self.get_monetary_policy(),
            "asset_performance": self.get_asset_performance(),
            "economic_calendar": get_upcoming_events(),
        }

    # ==================== Rendering ====================

    def render_section(self, data: dict[str, Any], config: dict[str, Any], *,
                       macro_summary: str | None = None) -> str:
        """渲染 A 股市场宏观区块。

        Macro view: ② economic calendar, ③ monetary policy, ④ asset performance.
        ① core view and ⑥ risk are injected at the pipeline/template layer.
        `macro_summary` is reserved for future use (core-view summary), unused now.
        """
        assets = data.get("asset_performance") or data.get("indices") or []
        indices_html = self._render_indices_table(assets, config)
        monetary_html = self._render_monetary_policy(data.get("monetary_policy", {}), config)
        econ = data.get("economic_calendar", [])
        econ_html = self._render_economic_calendar(econ) if econ else ""

        return f'''
    <div class="section">
      <div class="country-header" style="background-color:#c0392b; color:#ffffff; padding:15px 20px; margin-bottom:15px;">
        <h3 style="margin:0; font-size:16px; color:#ffffff;">{self.flag} {self.country_name}</h3>
      </div>

      <div class="card">
        <div class="card-header" style="padding:12px 15px; background:#f8f9fa; border-bottom:1px solid #e9ecef; font-weight:600;">📊 大类资产</div>
        <div class="card-body">
          {indices_html}
        </div>
      </div>
      {monetary_html}
      {econ_html}
    </div>'''

    # ==================== Render Helpers ====================

    def _render_monetary_policy(self, monetary: dict, config: dict) -> str:
        """③ 货币政策与利率：LPR / M2 / M1 / 社融 / 中国10Y国债。"""
        if not monetary:
            return ""
        pairs = [
            ("LPR1Y", monetary.get("lpr_1y"), "%"),
            ("LPR5Y", monetary.get("lpr_5y"), "%"),
            ("M2同比", monetary.get("m2_yoy"), "%"),
            ("M1同比", monetary.get("m1_yoy"), "%"),
            ("社融增量", monetary.get("social_financing"), "亿元"),
            ("中国10Y国债", monetary.get("cn_10y_yield"), "%"),
        ]
        rows = [
            f'<div class="metric"><span class="label">{label}:</span> {val}{suffix}</div>'
            for label, val, suffix in pairs if val is not None
        ]
        if not rows:
            return ""
        return (
            '<div class="card"><div class="card-header" style="padding:12px 15px;background:#f8f9fa;'
            'border-bottom:1px solid #e9ecef;font-weight:600;">🏦 货币政策与利率</div>'
            '<div class="card-body" style="padding:15px;">'
            '<div class="metrics-row" style="display:flex;flex-wrap:wrap;gap:8px;font-size:13px;color:#555;">'
            f'{"".join(rows)}</div></div></div>'
        )

    def _render_indices_table(
        self, indices: list[dict], config: dict
    ) -> str:
        """渲染指数行情表格。"""
        if not indices:
            return '<div class="no-data">暂无指数数据</div>'

        cards = ""
        for idx in indices:
            change = idx.get("change") or 0
            change_str = f"+{change:.2f}%" if change > 0 else f"{change:.2f}%"
            color = (
                config.get("color_up", "#e74c3c") if change > 0
                else config.get("color_down", "#27ae60") if change < 0
                else "#7f8c8d"
            )
            point = idx.get("point", 0)
            amount = idx.get("amount")
            amount_str = f'<div style="font-size:11px; color:#999;">额 {self._format_amount(amount)}</div>' if amount else ""
            cards += f'''
        <td style="padding:8px 6px; width:33.3%; vertical-align:top;">
          <div style="background:#f8f9fa; border-radius:8px; padding:10px; text-align:center;">
            <div style="font-size:12px; color:#7f8c8d; margin-bottom:4px;">{idx['name']}</div>
            <div style="font-size:18px; font-weight:bold; color:#2c3e50;">{point:,.2f}</div>
            <div style="font-size:14px; font-weight:bold; color:{color};">{change_str}</div>
            {amount_str}
          </div>
        </td>'''

        # Wrap in rows of 3
        cells = cards.split("</td>")
        cells = [c + "</td>" for c in cells if c.strip()]
        rows_html = ""
        for i in range(0, len(cells), 3):
            row_cells = "".join(cells[i : i + 3])
            remaining = 3 - len(cells[i : i + 3])
            for _ in range(remaining):
                row_cells += '<td style="width:33.3%;"></td>'
            rows_html += f"<tr>{row_cells}</tr>"

        return f'''
      <table width="100%" cellpadding="0" cellspacing="6" style="border-collapse:separate;">
        {rows_html}
      </table>'''

    def _render_economic_calendar(self, calendar: list[dict]) -> str:
        """渲染经济日历。"""
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

    # ==================== Utilities ====================

    @staticmethod
    def _format_amount(val) -> str:
        """金额中文格式化。"""
        if val is None:
            return "-"
        if val >= 100_000_000:
            return f"¥{val / 100_000_000:.2f}亿"
        if val >= 10_000:
            return f"¥{val / 10_000:.1f}万"
        return f"¥{val:,.0f}"
