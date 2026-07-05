"""
A股 Market Provider — AKShare powered (macro view).

Provides macro data: indices, monetary policy, asset performance, economic calendar.
"""

import logging
from typing import Any

import pandas as pd

from investbrief.market.base import MarketProvider
from investbrief.data.cn_data import CNData

logger = logging.getLogger(__name__)

# 渲染名称 → (cn_index_daily.code, 展示用 6 位 symbol)
_INDEX_SYMBOLS = {
    "上证指数": ("sh000001", "000001"),
    "深证成指": ("sz399001", "399001"),
    "创业板指": ("sz399006", "399006"),
    "沪深300":  ("sh000300", "000300"),
    "科创50":  ("sh000688", "000688"),
}


class CNMarketProvider(MarketProvider):
    market_code = "cn"
    country_name = "A股市场"
    currency = "¥"
    flag = "🇨🇳"

    def __init__(self, data: "CNData | None" = None):
        self.data = data if data is not None else CNData()

    def refresh(self, force: bool = False):
        """增量取数落盘。force=False 时若当日已更新则跳过（DB-First）。失败不抛异常。"""
        if not force and self.data.is_fresh():
            logger.info("CN data already up-to-date for today, skip refresh")
            return
        try:
            self.data.update_incremental()
        except Exception as e:
            logger.warning(f"CN data refresh failed, falling back to stored values: {e}")

    def _index_bars(self, code: str):
        """从 cn_index_daily 最新两 bar 算 (point, change%, change_amt, amount)；无数据返回 None。"""
        bars = self.data.latest_bars("cn_index_daily", code, n=2)
        if bars.empty:
            return None
        latest = bars.iloc[0]
        point = float(latest["close"])
        change_amt = 0.0
        change = 0.0
        if len(bars) > 1:
            prev = float(bars.iloc[1]["close"])
            change_amt = point - prev
            change = (change_amt / prev * 100) if prev else 0.0
        amt = latest.get("amount")
        amount = float(amt) if pd.notna(amt) else None
        return point, change, change_amt, amount

    def get_indices(self) -> list[dict[str, Any]]:
        results = []
        for name, (code, sym) in _INDEX_SYMBOLS.items():
            got = self._index_bars(code)
            if got is None:
                continue
            point, change, change_amt, amount = got
            results.append({
                "name": name, "symbol": sym,
                "point": point, "change": change,
                "change_amt": change_amt, "amount": amount,
            })
        return results

    def get_monetary_policy(self) -> dict[str, Any]:
        return {
            "lpr_1y": self.data.latest_macro("LPR1Y", "cn"),
            "lpr_5y": self.data.latest_macro("LPR5Y", "cn"),
            "m2_yoy": self.data.latest_macro("M2_YOY", "cn"),
            "m1_yoy": self.data.latest_macro("M1_YOY", "cn"),
            "social_financing": self.data.latest_macro("SOCIAL_FIN", "cn"),
            "cn_10y_yield": self.data.latest_macro("10Y_TREASURY", "cn"),
        }

    def get_asset_performance(self) -> list[dict[str, Any]]:
        assets = self.get_indices()
        # USDCNY 存于 macro_data（无 code 列，不走 latest_bars），按日期取最近两期算 change
        fx_rows = self.data.query(
            "SELECT date, value FROM macro_data WHERE indicator='USDCNY' AND country='global' "
            "ORDER BY date DESC LIMIT 2"
        )
        if not fx_rows.empty:
            point = float(fx_rows.iloc[0]["value"])
            change = 0.0
            if len(fx_rows) > 1:
                prev = float(fx_rows.iloc[1]["value"])
                change = round((point - prev) / prev * 100, 2) if prev else 0.0
            assets.append({"name": "人民币汇率(USDCNY)", "point": point, "change": change})
        return assets

    def fetch_all(self) -> dict[str, Any]:
        from investbrief.market.cn.calendar import get_upcoming_events
        return {
            "monetary_policy": self.get_monetary_policy(),
            "asset_performance": self.get_asset_performance(),
            "economic_calendar": get_upcoming_events(),
        }

    # ==================== Rendering ====================

    def render_section(self, data: dict[str, Any], config: dict[str, Any], *,
                       macro_summary: str | None = None, risk_html: str = "",
                       regime_html: str = "") -> str:
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
      {regime_html}
      {risk_html}
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
        rows = []
        for label, val, suffix in pairs:
            if val is None:
                continue
            val_str = f"{val:.2f}" if isinstance(val, (int, float)) else str(val)
            rows.append(
                f'<div class="metric"><span class="label">{label}:</span> {val_str}{suffix}</div>'
            )
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
        """渲染指数行情卡片（flex 响应式，移动端单列 stack）。"""
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
            amount_str = (f'<div style="font-size:11px;color:#999;margin-top:6px;">额 {self._format_amount(amount)}</div>'
                          if amount else "")
            cards += f'''
        <div class="asset-card" style="background:#f8f9fa;border-radius:8px;padding:12px 10px;text-align:center;">
          <div style="font-size:12px;color:#7f8c8d;margin-bottom:4px;">{idx['name']}</div>
          <div style="font-size:18px;font-weight:bold;color:#2c3e50;">{point:,.2f}</div>
          <div style="font-size:14px;font-weight:bold;color:{color};">{change_str}</div>
          {amount_str}
        </div>'''

        return f'''
      <div class="asset-grid" style="display:flex;flex-wrap:wrap;gap:6px;">
        {cards.strip()}
      </div>'''

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
