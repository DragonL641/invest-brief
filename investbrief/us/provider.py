"""
US Market Provider - yfinance powered (macro view).

Provides macro data: indices, monetary policy, asset performance, economic calendar.
"""

import logging
from typing import Dict, List, Any

import pandas as pd

from investbrief.core.provider import MarketProvider
from investbrief.data.us_data import USData

logger = logging.getLogger(__name__)

# Federal funds target rate range — update manually on FOMC moves
FED_FUNDS_TARGET = "5.25% - 5.50%"

# 渲染名称 → us_index_daily.code
_INDEX_SYMBOLS = {
    "S&P 500": "^GSPC",
    "NASDAQ": "^IXIC",
    "Dow Jones": "^DJI",
    "VIX": "^VIX",
    "10Y国债": "^TNX",
    "WTI原油": "CL=F",
    "美元指数": "DX-Y.NYB",
}


class USMarketProvider(MarketProvider):
    market_code = "us"
    country_name = "美国市场"
    flag = "🇺🇸"
    currency = "$"

    def __init__(self, data: "USData | None" = None):
        self.data = data if data is not None else USData()

    def refresh(self):
        """增量取数落盘。失败不抛异常——get_* 方法会回退到库内最新值。"""
        try:
            self.data.update_incremental()
        except Exception as e:
            logger.warning(f"US data refresh failed, falling back to stored values: {e}")

    # ==================== Data Methods ====================

    def _bar_point_change(self, code: str) -> tuple[float | None, float, float | None]:
        """从 us_index_daily 最新两 bar 算 (point, change%, volume)。"""
        bars = self.data.latest_bars("us_index_daily", code, n=2)
        if bars.empty:
            return None, 0.0, None
        latest = bars.iloc[0]
        point = float(latest["close"])
        volume = latest.get("volume")
        volume = float(volume) if pd.notna(volume) else None
        if len(bars) > 1:
            prev = float(bars.iloc[1]["close"])
            change = ((point - prev) / prev * 100) if prev else 0.0
        else:
            change = 0.0
        return point, change, volume

    def get_indices(self) -> List[Dict[str, Any]]:
        results = []
        for name, code in _INDEX_SYMBOLS.items():
            point, change, volume = self._bar_point_change(code)
            if point is None:
                continue
            results.append({
                "name": name,
                "point": point,
                "change": change,
                "volume": self._format_volume(volume) if volume else "-",
            })
        return results

    def get_monetary_policy(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "us_10y_yield": None, "us_5y_yield": None,
            "us_13w_yield": None, "fed_funds_rate": FED_FUNDS_TARGET,
        }
        for key, code in (("us_10y_yield", "^TNX"), ("us_5y_yield", "^FVX"), ("us_13w_yield", "^IRX")):
            point, _, _ = self._bar_point_change(code)
            if point is not None:
                result[key] = point
        return result

    def get_asset_performance(self) -> list[dict[str, Any]]:
        assets = self.get_indices()
        point, change, _ = self._bar_point_change("GC=F")
        if point is not None:
            assets.append({"name": "黄金(COMEX)", "point": point, "change": change})
        return assets

    def fetch_all(self) -> dict[str, Any]:
        from investbrief.us.calendar import get_upcoming_events_with_yfinance
        return {
            "monetary_policy": self.get_monetary_policy(),
            "asset_performance": self.get_asset_performance(),
            "economic_calendar": get_upcoming_events_with_yfinance(),
        }

    # ==================== Rendering ====================

    def render_section(self, data: Dict[str, Any], config: Dict[str, Any], *,
                       macro_summary: str | None = None, risk_html: str = "") -> str:
        """Render US market macro section.

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
      <div class="country-header" style="background-color:#2c3e50; color:#ffffff; padding:15px 20px; margin-bottom:15px;">
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
      {risk_html}
    </div>'''

    # ==================== Render Helpers ====================

    def _render_monetary_policy(self, monetary: dict, config: dict) -> str:
        """③ 货币政策与利率：美债收益率 + 联邦基金目标利率。"""
        if not monetary:
            return ""
        pairs = [
            ("美债10Y收益率", monetary.get("us_10y_yield"), "%"),
            ("美债5Y", monetary.get("us_5y_yield"), "%"),
            ("美债13周", monetary.get("us_13w_yield"), "%"),
            ("联邦基金目标", monetary.get("fed_funds_rate"), ""),
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

    def _render_economic_calendar(self, calendar: List[Dict]) -> str:
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

    def _render_indices_table(self, indices: List[Dict], config: Dict) -> str:
        # Categorize indices
        stock_names = {"S&P 500", "NASDAQ", "Dow Jones"}
        macro_names = {"10Y国债", "WTI原油", "美元指数"}

        groups = [
            ("📈 美股指数", [i for i in indices if i["name"] in stock_names]),
            ("🌐 宏观指标", [i for i in indices if i["name"] in macro_names]),
            ("📊 其他", [i for i in indices if i["name"] not in stock_names and i["name"] not in macro_names]),
        ]

        html = ""
        for label, items in groups:
            if not items:
                continue
            cards = ""
            for idx in items:
                change = idx.get("change", 0)
                change_str = f"+{change:.2f}%" if change > 0 else f"{change:.2f}%"
                color = config["color_up"] if change > 0 else (config["color_down"] if change < 0 else "#7f8c8d")
                vol = idx.get("volume", "-")
                cards += f'''
        <td style="padding:8px 6px; width:33%; vertical-align:top;">
          <div style="background:#f8f9fa; border-radius:8px; padding:10px; text-align:center;">
            <div style="font-size:12px; color:#7f8c8d; margin-bottom:4px;">{idx['name']}</div>
            <div style="font-size:18px; font-weight:bold; color:#2c3e50;">{idx['point']:,.2f}</div>
            <div style="font-size:14px; font-weight:bold; color:{color};">{change_str}</div>
            {f'<div style="font-size:11px; color:#999;">量 {vol}</div>' if vol != "-" else ""}
          </div>
        </td>'''
            # Wrap in rows of 3 columns
            cells = cards.split("</td>")
            cells = [c + "</td>" for c in cells if c.strip()]
            rows_html = ""
            for i in range(0, len(cells), 3):
                row_cells = "".join(cells[i:i+3])
                # Pad with empty cells if needed
                remaining = 3 - len(cells[i:i+3])
                for _ in range(remaining):
                    row_cells += '<td style="width:33%;"></td>'
                rows_html += f'<tr>{row_cells}</tr>'

            html += f'''
      <div style="margin-bottom:4px;">
        <div style="font-size:13px; font-weight:600; color:#555; margin-bottom:6px;">{label}</div>
        <table width="100%" cellpadding="0" cellspacing="6" style="border-collapse:separate;">
          {rows_html}
        </table>
      </div>'''

        return html

    # ==================== Utilities ====================

    @staticmethod
    def _format_volume(vol) -> str:
        if not vol:
            return "-"
        if vol >= 1_000_000_000:
            return f"{vol/1_000_000_000:.1f}B"
        if vol >= 1_000_000:
            return f"{vol/1_000_000:.1f}M"
        if vol >= 1_000:
            return f"{vol/1_000:.1f}K"
        return str(vol)
