"""
A股 Market Provider — AKShare powered (macro view).

Provides macro data: indices, monetary policy, asset performance, economic calendar.
"""

import logging
from typing import Any

import pandas as pd

from investbrief.market.base import MarketProvider
from investbrief.data.cn_data import CNData
from investbrief.datasources.akshare import AKShareClient

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

    # —— 能力声明 ——
    risk_group = "cn"
    supports_regime = True
    data_class = CNData

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

    # ==================== News & Calendar ====================

    def get_news(self, config: dict, limit: int) -> list:
        from investbrief.market.cn.news import fetch_cn_macro_news
        try:
            return fetch_cn_macro_news(limit)
        except Exception as e:
            logger.warning(f"CN news fetch failed: {e}")
            return []

    def get_economic_calendar(self) -> list:
        from investbrief.market.cn.calendar import get_upcoming_events
        try:
            return get_upcoming_events()
        except Exception as e:
            logger.warning(f"CN calendar fetch failed: {e}")
            return []

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
            # 宏观指标（已在 macro_data 采集，喂给 Claude 写"宏观环境"，原仅入库 provider 不取）
            "cpi_yoy": self.data.latest_macro("CPI", "cn"),          # 源即同比 %
            "gdp_yoy": self.data.latest_macro_yoy("GDP", "cn", 4),   # 绝对值 → 同比(季频)
        }

    def get_asset_performance(self) -> list[dict[str, Any]]:
        assets = self.get_indices()
        # USDCNY:统一用实时口径(与 market/overseas.py 外围卡一致);失败回退 DB 最新值。
        point = None
        try:
            point = AKShareClient().get_fx_usdcny_realtime()
        except Exception as e:
            logger.warning(f"USDCNY realtime failed: {e}")
        # change 用 DB 最近两期算(实时接口无前值);实时失败时 point 也回退 DB 最新。
        fx_rows = self.data.query(
            "SELECT date, value FROM macro_data WHERE indicator='USDCNY' AND country='global' "
            "ORDER BY date DESC LIMIT 2"
        )
        if point is None and not fx_rows.empty:
            point = float(fx_rows.iloc[0]["value"])
        if point is None:
            return assets
        change = 0.0
        if not fx_rows.empty and len(fx_rows) > 1:
            prev = float(fx_rows.iloc[1]["value"])
            # point 走实时、prev 走 DB 前值:口径近似「相对昨收」,实时与 DB 非严格同源
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

    def get_sentiment(self) -> dict:
        """A 股 QVIX 恐慌指数(50ETF/300ETF)。失败键为 None。"""
        try:
            return AKShareClient().get_cn_qvix()
        except Exception as e:
            logger.warning(f"CN QVIX fetch failed: {e}")
            return {"qvix_50": None, "qvix_300": None}

    def _render_sentiment(self, sentiment: dict | None) -> str:
        """渲染 A 股 QVIX 恐慌情绪小卡。无数据/None 返回空串。"""
        if not sentiment:
            return ""
        q50 = sentiment.get("qvix_50")
        q300 = sentiment.get("qvix_300")
        if q50 is None and q300 is None:
            return ""
        def _row(label, val):
            return f'<div class="metric"><span class="label">{label}:</span> {val:.2f}</div>' if val else ""
        rows = _row("50ETF QVIX", q50) + _row("300ETF QVIX", q300)
        if not rows:
            return ""
        return (
            '<div class="card"><div class="card-header" style="padding:12px 15px;background:#f8f9fa;'
            'border-bottom:1px solid #e9ecef;font-weight:600;">😱 A股恐慌指数(QVIX)</div>'
            '<div class="card-body" style="padding:15px;">'
            '<div class="metrics-row" style="display:flex;flex-wrap:wrap;gap:8px;font-size:13px;color:#555;">'
            f'{rows}</div></div></div>'
        )

    # ==================== Rendering ====================

    def render_section(self, data: dict[str, Any], config: dict[str, Any], *,
                       macro_summary: str | None = None, risk_html: str = "",
                       regime_html: str = "", sentiment: dict | None = None) -> str:
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
      {self._render_sentiment(sentiment)}
      {econ_html}
      {regime_html}
      {risk_html}
    </div>'''

    # ==================== Render Helpers ====================

    def _render_monetary_policy(self, monetary: dict, config: dict) -> str:
        """③ 货币政策与利率：LPR / M2 / M1 / 社融 / 中国10Y国债 / CPI / GDP。"""
        if not monetary:
            return ""
        pairs = [
            ("LPR1Y", monetary.get("lpr_1y"), "%"),
            ("LPR5Y", monetary.get("lpr_5y"), "%"),
            ("M2同比", monetary.get("m2_yoy"), "%"),
            ("M1同比", monetary.get("m1_yoy"), "%"),
            ("社融增量", monetary.get("social_financing"), "亿元"),
            ("中国10Y国债", monetary.get("cn_10y_yield"), "%"),
            ("CPI同比", monetary.get("cpi_yoy"), "%"),
            ("GDP同比", monetary.get("gdp_yoy"), "%"),
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
        <div class="asset-card" style="background:#f8f9fa;border-radius:8px;padding:12px 10px;text-align:center;margin:4px;">
          <div style="font-size:12px;color:#7f8c8d;margin-bottom:4px;">{idx['name']}</div>
          <div style="font-size:18px;font-weight:bold;color:#2c3e50;">{point:,.2f}</div>
          <div style="font-size:14px;font-weight:bold;color:{color};">{change_str}</div>
          {amount_str}
        </div>'''

        return f'''
      <div class="asset-grid" style="display:flex;flex-wrap:wrap;">
        {cards.strip()}
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
