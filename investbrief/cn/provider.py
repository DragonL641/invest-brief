"""
A股 Market Provider — AKShare powered

Data fetching + HTML rendering for A-share market reports.
"""

import logging
from typing import Any

import pandas as pd

from investbrief.core.charts import generate_stock_chart
from investbrief.core.provider import MarketProvider
from investbrief.cn.client import AKShareClient
from investbrief.cn.watchlist import get_watchlist_stocks, INDUSTRY_LABELS
from investbrief.cn.calendar import get_upcoming_events

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
        results = []
        for name, symbol in self.INDEX_SYMBOLS.items():
            quote = self.client.get_index_quote(symbol)
            if quote:
                results.append({
                    "name": name,
                    "symbol": symbol,
                    "point": quote["price"],
                    "change": quote.get("change_pct"),
                    "change_amt": quote.get("change"),
                    "amount": quote.get("amount"),
                })
        return results

    def get_holdings_data(self, holdings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """获取持仓个股详情。"""
        symbols = [h["symbol"] for h in holdings]

        # Batch fetch quotes to avoid repeated full-table scans
        batch_quotes = {}
        try:
            quotes_list = self.client.get_stock_quotes(symbols)
            for q in quotes_list:
                batch_quotes[q["symbol"]] = q
        except Exception as e:
            logger.warning(f"Batch quote fetch failed, falling back: {e}")

        results = []
        for h in holdings:
            symbol = h["symbol"]
            data: dict[str, Any] = {"symbol": symbol, "name": h.get("name", symbol)}

            # Quote (prefer batch result, fallback to single)
            quote = batch_quotes.get(symbol) or self.client.get_stock_quote(symbol)
            if quote:
                data["price"] = quote["price"]
                data["change"] = quote.get("change_pct")
                data["change_amt"] = quote.get("change")
                data["currency"] = "¥"
                data["market_cap"] = quote.get("market_cap")
                data["pe"] = quote.get("pe")
                data["turnover_rate"] = quote.get("turnover_rate")

            # History + chart
            history = self.client.get_stock_history(symbol, days=180)
            if history is not None and not history.empty:
                # generate_stock_chart expects uppercase column names (Close, etc.)
                chart_df = history.rename(columns={
                    "open": "Open", "high": "High", "low": "Low",
                    "close": "Close", "volume": "Volume",
                })
                chart_b64 = generate_stock_chart(symbol, chart_df, period="6月")
                if chart_b64:
                    data["chart_b64"] = chart_b64
                data["technicals"] = self._calc_technicals(history)

            # Analyst rating summary
            rating = self.client.get_analyst_rating_summary(symbol)
            if rating:
                data["rating_summary"] = rating

            # Financial indicators
            financial = self.client.get_financial_indicators(symbol)
            if financial:
                data["financial"] = financial

            # Insider trades
            insiders = self.client.get_insider_trades(symbol)
            if insiders:
                data["insider_trades"] = insiders

            # Institutional research
            inst = self.client.get_institutional_research(symbol)
            if inst:
                data["institutional_research"] = inst

            # Research reports
            reports = self.client.get_research_reports(symbol, limit=5)
            if reports:
                data["research_reports"] = reports

            results.append(data)
        return results

    def get_recommendations(
        self, industries: list[str], exclude: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """按行业获取推荐关注个股（买入评级 > 50%）。"""
        exclude = exclude or []
        watchlist = get_watchlist_stocks(industries)
        if not watchlist:
            return []

        results = []
        for stock in watchlist:
            symbol = stock["symbol"]
            if symbol in exclude:
                continue

            rating = self.client.get_analyst_rating_summary(symbol)
            if not rating:
                continue

            total = rating["total_reports"]
            if total == 0:
                continue

            buy_count = rating.get("buy", 0) + rating.get("outperform", 0)
            buy_pct = buy_count / total * 100
            if buy_pct <= 50:
                continue

            data: dict[str, Any] = {
                "symbol": symbol,
                "name": stock["name"],
                "industry": stock["industry"],
                "rating_summary": rating,
                "buy_pct": round(buy_pct, 1),
            }

            # Basic quote
            quote = self.client.get_stock_quote(symbol)
            if quote:
                data["price"] = quote["price"]
                data["change"] = quote.get("change_pct")
                data["currency"] = "¥"

            label = INDUSTRY_LABELS.get(stock["industry"], stock["industry"])
            data["recommendation_reason"] = (
                f"{label} · {buy_pct:.0f}%买入评级 · {total}份研报"
            )

            results.append(data)

        results.sort(key=lambda x: x.get("buy_pct", 0), reverse=True)
        return results[:5]

    def fetch_all(self, holdings: list[dict], industries: list[str]) -> dict[str, Any]:
        """获取 A 股全部数据。"""
        holdings_symbols = [h["symbol"] for h in holdings]

        indices = self.get_indices()
        holdings_data = self.get_holdings_data(holdings)
        recommendations = self.get_recommendations(industries, holdings_symbols)
        dragon_tiger = self.client.get_dragon_tiger_list(days=3)
        economic_calendar = get_upcoming_events()

        return {
            "indices": indices,
            "holdings": holdings_data,
            "recommendations": recommendations,
            "dragon_tiger": dragon_tiger,
            "economic_calendar": economic_calendar,
        }

    # ==================== Rendering ====================

    def render_section(self, data: dict[str, Any], config: dict[str, Any]) -> str:
        """渲染 A 股市场 HTML 区块。"""
        indices_html = self._render_indices_table(data.get("indices", []), config)
        holdings_html = self._render_holdings(data.get("holdings", []), config)

        # Dragon tiger (A-share specific)
        dt = data.get("dragon_tiger", [])
        dt_html = self._render_dragon_tiger(dt, config) if dt else ""

        # Economic calendar
        econ = data.get("economic_calendar", [])
        econ_html = self._render_economic_calendar(econ) if econ else ""

        recommendations_html = self._render_recommendations(
            data.get("recommendations", []), config
        )

        return f'''
    <div class="section">
      <div class="country-header" style="background-color:#c0392b; color:#ffffff; padding:15px 20px; margin-bottom:15px;">
        <h3 style="margin:0; font-size:16px; color:#ffffff;">{self.flag} {self.country_name}</h3>
      </div>

      <div class="card">
        <div class="card-header" style="padding:12px 15px; background:#f8f9fa; border-bottom:1px solid #e9ecef; font-weight:600;">📊 市场总览</div>
        <div class="card-body">
          {indices_html}
        </div>
      </div>
      <div class="card">
        <div class="card-header" style="padding:12px 15px; background:#f8f9fa; border-bottom:1px solid #e9ecef; font-weight:600;">💼 持仓股票</div>
        <div class="card-body">
          {holdings_html}
        </div>
      </div>
      {dt_html}
      {econ_html}
      <div class="card">
        <div class="card-header" style="padding:12px 15px; background:#f8f9fa; border-bottom:1px solid #e9ecef; font-weight:600;">⭐ 推荐关注</div>
        <div class="card-body">
          {recommendations_html}
        </div>
      </div>
    </div>'''

    # ==================== Render Helpers ====================

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
        <td style="padding:8px 6px; width:20%; vertical-align:top;">
          <div style="background:#f8f9fa; border-radius:8px; padding:10px; text-align:center;">
            <div style="font-size:12px; color:#7f8c8d; margin-bottom:4px;">{idx['name']}</div>
            <div style="font-size:18px; font-weight:bold; color:#2c3e50;">{point:,.2f}</div>
            <div style="font-size:14px; font-weight:bold; color:{color};">{change_str}</div>
            {amount_str}
          </div>
        </td>'''

        # Wrap in rows of 5
        cells = cards.split("</td>")
        cells = [c + "</td>" for c in cells if c.strip()]
        rows_html = ""
        for i in range(0, len(cells), 5):
            row_cells = "".join(cells[i : i + 5])
            remaining = 5 - len(cells[i : i + 5])
            for _ in range(remaining):
                row_cells += '<td style="width:20%;"></td>'
            rows_html += f"<tr>{row_cells}</tr>"

        return f'''
      <table width="100%" cellpadding="0" cellspacing="6" style="border-collapse:separate;">
        {rows_html}
      </table>'''

    def _render_holdings(self, holdings: list[dict], config: dict) -> str:
        if not holdings:
            return '<div class="no-data">📌 当前无持仓</div>'
        html = ""
        for h in holdings:
            html += self._render_stock_card(h, config)
        return html

    def _render_stock_card(self, stock: dict, config: dict) -> str:
        change = stock.get("change") or 0
        change_str = f"+{change:.2f}%" if change > 0 else f"{change:.2f}%"
        color = (
            config.get("color_up", "#e74c3c") if change > 0
            else config.get("color_down", "#27ae60") if change < 0
            else "#7f8c8d"
        )
        currency = stock.get("currency", "¥")
        price = stock.get("price", 0) or 0
        name = stock.get("name", stock["symbol"])

        html = f'''
<div class="stock-detail" style="background:#f8f9fa; padding:12px; margin:8px 0;">
  <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; margin-bottom:8px;">
    <tr>
      <td style="font-weight:600; font-size:15px;">{name} ({stock['symbol']})</td>
      <td style="text-align:right; font-size:18px; font-weight:bold; color:{color};">{currency}{price:,.2f} <small>{change_str}</small></td>
    </tr>
  </table>'''

        # Key metrics: 市值 / PE / 换手率
        metrics_items = []
        if stock.get("market_cap"):
            metrics_items.append(f'<span class="label">市值:</span> {self._format_cap_cn(stock["market_cap"])}')
        if stock.get("pe") is not None:
            metrics_items.append(f'<span class="label">PE:</span> {stock["pe"]:.1f}')
        if stock.get("turnover_rate") is not None:
            metrics_items.append(f'<span class="label">换手率:</span> {stock["turnover_rate"]:.2f}%')

        if metrics_items:
            metrics_html = "".join(f'<div class="metric">{m}</div>' for m in metrics_items)
            html += f'''
  <div class="metrics-row">
    {metrics_html}
  </div>'''

        # Rating distribution bars
        rating = stock.get("rating_summary")
        if rating and rating.get("total_reports", 0) > 0:
            total = rating["total_reports"]
            buy = rating.get("buy", 0) + rating.get("outperform", 0)
            neutral = rating.get("neutral", 0)
            sell = rating.get("underperform", 0) + rating.get("sell", 0)
            buy_pct = buy / total * 100
            neutral_pct = neutral / total * 100
            sell_pct = sell / total * 100

            html += f'''
  <div class="analyst-section">
    <div style="font-weight:600; margin-bottom:6px; color:#2c3e50;">📊 研报评级分布 ({total}份)</div>
    <table width="100%" cellpadding="0" cellspacing="0" style="font-size:12px; margin:6px 0;">
      <tr>
        <td width="36" style="color:#666; padding:3px 0;">买入</td>
        <td width="24" style="font-weight:600; color:#e74c3c; padding:3px 4px 3px 0;">{buy}</td>
        <td style="padding:3px 0;"><div style="background:#fde8e8; height:6px; border-radius:3px;"><div style="background:#e74c3c; height:6px; border-radius:3px; width:{buy_pct:.1f}%;"></div></div></td>
        <td width="36" style="text-align:right; color:#999; padding:3px 0 3px 4px;">{buy_pct:.0f}%</td>
      </tr>
      <tr>
        <td style="color:#666; padding:3px 0;">中性</td>
        <td style="font-weight:600; color:#f39c12; padding:3px 4px 3px 0;">{neutral}</td>
        <td style="padding:3px 0;"><div style="background:#fef9e7; height:6px; border-radius:3px;"><div style="background:#f39c12; height:6px; border-radius:3px; width:{neutral_pct:.1f}%;"></div></div></td>
        <td style="text-align:right; color:#999; padding:3px 0 3px 4px;">{neutral_pct:.0f}%</td>
      </tr>
      <tr>
        <td style="color:#666; padding:3px 0;">卖出</td>
        <td style="font-weight:600; color:#27ae60; padding:3px 4px 3px 0;">{sell}</td>
        <td style="padding:3px 0;"><div style="background:#e8f8f0; height:6px; border-radius:3px;"><div style="background:#27ae60; height:6px; border-radius:3px; width:{sell_pct:.1f}%;"></div></div></td>
        <td style="text-align:right; color:#999; padding:3px 0 3px 4px;">{sell_pct:.0f}%</td>
      </tr>
    </table>
  </div>'''

        # Technical indicators
        techs = stock.get("technicals")
        if techs:
            html += self._render_technicals(techs, price, currency)

        # Financial indicators
        fin = stock.get("financial")
        if fin:
            html += self._render_financial(fin, currency)

        # Insider trades (高管增减持)
        insiders = stock.get("insider_trades")
        if insiders:
            html += self._render_insider_trades(insiders)

        # Institutional research (机构调研)
        inst = stock.get("institutional_research")
        if inst:
            html += self._render_institutional_research(inst)

        # Chart
        chart_b64 = stock.get("chart_b64")
        if chart_b64:
            symbol = stock["symbol"]
            html += f'''
  <div style="margin: 8px 0;">
    <img src="data:image/png;base64,{chart_b64}" alt="{symbol} chart" style="width:100%; max-width:760px; border-radius:6px; border:1px solid #eee;" />
  </div>'''

        html += "</div>"
        return html

    def _render_technicals(
        self, techs: dict, price: float, currency: str
    ) -> str:
        rsi = techs.get("rsi_14")
        rsi_color = "#e74c3c" if rsi and rsi > 70 else "#27ae60" if rsi and rsi < 30 else "#7f8c8d"
        rsi_label = "超买" if rsi and rsi > 70 else "超卖" if rsi and rsi < 30 else ""

        macd_hist = techs.get("macd_hist", 0)
        macd_label = "金叉" if macd_hist > 0 else "死叉"
        macd_color = "#e74c3c" if macd_hist > 0 else "#27ae60"

        items = []
        if rsi:
            items.append(f'RSI(14): <strong style="color:{rsi_color}">{rsi:.1f}</strong> {rsi_label}')
        sma_50 = techs.get("sma_50")
        if sma_50 and price:
            pct = ((price - sma_50) / sma_50) * 100
            items.append(f"MA50: {currency}{sma_50:.2f} ({pct:+.1f}%)")
        sma_200 = techs.get("sma_200")
        if sma_200 and price:
            pct = ((price - sma_200) / sma_200) * 100
            items.append(f"MA200: {currency}{sma_200:.2f} ({pct:+.1f}%)")
        if macd_hist is not None:
            items.append(f'MACD: <strong style="color:{macd_color}">{macd_label}</strong>')

        spans = "".join(f"<span>{it}</span>" for it in items)
        return f'''
  <div style="background:#f0f4f8; border-radius:6px; padding:10px; margin:8px 0; border-left:3px solid #c0392b;">
    <div style="font-weight:600; margin-bottom:6px; color:#2c3e50;">📊 技术指标</div>
    <div style="display:flex; flex-wrap:wrap; gap:12px; font-size:13px;">{spans}</div>
  </div>'''

    def _render_financial(self, fin: dict, currency: str) -> str:
        items = []
        if fin.get("eps") is not None:
            items.append(f"每股收益: {currency}{fin['eps']:.2f}")
        if fin.get("roe") is not None:
            items.append(f"ROE: {fin['roe']:.2f}%")
        if fin.get("revenue_growth") is not None:
            items.append(f"营收增长: {fin['revenue_growth']:+.2f}%")
        if fin.get("profit_growth") is not None:
            items.append(f"净利润增长: {fin['profit_growth']:+.2f}%")

        if not items:
            return ""

        spans = "".join(f"<span>{it}</span>" for it in items)
        report_date = fin.get("report_date", "")
        date_str = f" ({report_date})" if report_date else ""

        return f'''
  <div style="background:#f8f4e8; border-radius:6px; padding:10px; margin:8px 0; border-left:3px solid #f39c12;">
    <div style="font-weight:600; margin-bottom:6px; color:#2c3e50;">💰 财务指标{date_str}</div>
    <div style="display:flex; flex-wrap:wrap; gap:12px; font-size:13px;">{spans}</div>
  </div>'''

    def _render_insider_trades(self, trades: list[dict]) -> str:
        rows = ""
        for t in trades[:5]:
            action = t.get("action", "")
            action_color = "#e74c3c" if "增" in action else "#27ae60" if "减" in action else "#555"
            shares_str = f'{t["shares"]:,.0f}' if t.get("shares") else "-"
            rows += f'''
      <tr>
        <td style="padding:4px 5px; border-bottom:1px solid #f0e8d8; font-weight:500; color:#2c3e50;">{t.get("name", "")}</td>
        <td style="padding:4px 5px; border-bottom:1px solid #f0e8d8; color:{action_color}; font-weight:500;">{action}</td>
        <td style="padding:4px 5px; border-bottom:1px solid #f0e8d8; text-align:right;">{shares_str}</td>
        <td style="padding:4px 5px; border-bottom:1px solid #f0e8d8; text-align:right; color:#999; font-size:11px;">{t.get("date", "")}</td>
      </tr>'''

        return f'''
  <div class="insider-section">
    <div style="font-weight:600; margin-bottom:6px; color:#2c3e50;">👔 高管增减持</div>
    <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; font-size:12px; table-layout:fixed;">
      <colgroup><col style="width:30%"/><col style="width:20%"/><col style="width:25%"/><col style="width:25%"/></colgroup>
      <tr style="background:rgba(0,0,0,0.03);">
        <th style="text-align:left; padding:4px 5px; font-weight:600; color:#2c3e50; border-bottom:1px solid #ccc;">姓名</th>
        <th style="text-align:left; padding:4px 5px; font-weight:600; color:#2c3e50; border-bottom:1px solid #ccc;">操作</th>
        <th style="text-align:right; padding:4px 5px; font-weight:600; color:#2c3e50; border-bottom:1px solid #ccc;">股数</th>
        <th style="text-align:right; padding:4px 5px; font-weight:600; color:#2c3e50; border-bottom:1px solid #ccc;">日期</th>
      </tr>
      {rows}
    </table>
  </div>'''

    def _render_institutional_research(self, research: list[dict]) -> str:
        rows = ""
        for r in research[:5]:
            rows += f'''
      <tr>
        <td style="padding:4px 5px; border-bottom:1px solid #f0e8d8; color:#2c3e50;">{r.get("date", "")}</td>
        <td style="padding:4px 5px; border-bottom:1px solid #f0e8d8; font-weight:500;">{r.get("institution", "")}家机构</td>
        <td style="padding:4px 5px; border-bottom:1px solid #f0e8d8; color:#555;">{r.get("type", "")}</td>
      </tr>'''

        return f'''
  <div class="institution-section">
    <div style="font-weight:600; margin-bottom:6px; color:#2c3e50;">🏢 机构调研</div>
    <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; font-size:12px; table-layout:fixed;">
      <colgroup><col style="width:25%"/><col style="width:35%"/><col style="width:40%"/></colgroup>
      <tr style="background:rgba(0,0,0,0.03);">
        <th style="text-align:left; padding:4px 5px; font-weight:600; color:#2c3e50; border-bottom:1px solid #ccc;">日期</th>
        <th style="text-align:left; padding:4px 5px; font-weight:600; color:#2c3e50; border-bottom:1px solid #ccc;">参与机构</th>
        <th style="text-align:left; padding:4px 5px; font-weight:600; color:#2c3e50; border-bottom:1px solid #ccc;">方式</th>
      </tr>
      {rows}
    </table>
  </div>'''

    def _render_dragon_tiger(self, items: list[dict], config: dict) -> str:
        """渲染龙虎榜。"""
        if not items:
            return ""

        rows = ""
        for it in items[:15]:
            change = it.get("change_pct") or 0
            change_str = f"+{change:.2f}%" if change > 0 else f"{change:.2f}%"
            color = (
                config.get("color_up", "#e74c3c") if change > 0
                else config.get("color_down", "#27ae60") if change < 0
                else "#7f8c8d"
            )
            net_buy = it.get("net_buy")
            net_buy_str = f'{self._format_amount(net_buy)}' if net_buy else "-"
            net_color = "#e74c3c" if (net_buy or 0) > 0 else "#27ae60"

            rows += f'''
      <tr>
        <td style="padding:4px 5px; border-bottom:1px solid #eee; font-weight:500;">{it.get("name", "")} ({it.get("symbol", "")})</td>
        <td style="padding:4px 5px; border-bottom:1px solid #eee; color:{color}; font-weight:bold;">{change_str}</td>
        <td style="padding:4px 5px; border-bottom:1px solid #eee; text-align:right; color:{net_color};">{net_buy_str}</td>
        <td style="padding:4px 5px; border-bottom:1px solid #eee; color:#999; font-size:11px;">{it.get("reason", "")}</td>
        <td style="padding:4px 5px; border-bottom:1px solid #eee; color:#999; font-size:11px;">{it.get("date", "")}</td>
      </tr>'''

        return f'''
      <div class="card">
        <div class="card-header" style="padding:12px 15px; background:#fff8f0; border-bottom:1px solid #ffe0b2; font-weight:600;">🐉 龙虎榜</div>
        <div class="card-body">
          <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; font-size:12px; table-layout:fixed;">
            <colgroup><col style="width:28%"/><col style="width:12%"/><col style="width:18%"/><col style="width:27%"/><col style="width:15%"/></colgroup>
            <tr style="background:rgba(0,0,0,0.03);">
              <th style="text-align:left; padding:4px 5px; font-weight:600; color:#2c3e50; border-bottom:1px solid #ccc;">股票</th>
              <th style="text-align:left; padding:4px 5px; font-weight:600; color:#2c3e50; border-bottom:1px solid #ccc;">涨跌幅</th>
              <th style="text-align:right; padding:4px 5px; font-weight:600; color:#2c3e50; border-bottom:1px solid #ccc;">净买入</th>
              <th style="text-align:left; padding:4px 5px; font-weight:600; color:#2c3e50; border-bottom:1px solid #ccc;">上榜原因</th>
              <th style="text-align:left; padding:4px 5px; font-weight:600; color:#2c3e50; border-bottom:1px solid #ccc;">日期</th>
            </tr>
            {rows}
          </table>
        </div>
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

    def _render_recommendations(self, recommendations: list[dict], config: dict) -> str:
        if not recommendations:
            return '<div class="no-data">📌 暂无推荐关注</div>'

        html = ""
        for r in recommendations:
            card_html = self._render_stock_card(r, config)
            reason = r.get("recommendation_reason", "")
            if reason:
                badge = f'<div style="background:#fff3cd; padding:6px 10px; border-radius:0 0 6px 6px; font-size:12px; color:#856404; border:1px solid #ffeeba; border-top:none;">💡 {reason}</div>'
                card_html = card_html.rstrip()
                if card_html.endswith("</div>"):
                    card_html = card_html[:-6] + badge + "</div>"
            html += card_html
        return html

    # ==================== Utilities ====================

    @staticmethod
    def _calc_technicals(history: pd.DataFrame) -> dict[str, Any]:
        """从日K线历史计算 RSI / MA / MACD。"""
        close = history["close"]
        result: dict[str, Any] = {}

        # RSI(14)
        if len(close) >= 15:
            delta = close.diff()
            gain = delta.where(delta > 0, 0.0)
            loss = (-delta).where(delta < 0, 0.0)
            avg_gain = gain.rolling(window=14, min_periods=14).mean()
            avg_loss = loss.rolling(window=14, min_periods=14).mean()
            rs = avg_gain / avg_loss.replace(0, float("inf"))
            rsi = 100 - (100 / (1 + rs))
            val = rsi.iloc[-1]
            if pd.notna(val):
                result["rsi_14"] = round(float(val), 2)

        # MA50 / MA200
        if len(close) >= 50:
            result["sma_50"] = round(float(close.rolling(window=50).mean().iloc[-1]), 2)
        if len(close) >= 200:
            result["sma_200"] = round(float(close.rolling(window=200).mean().iloc[-1]), 2)

        # MACD (12, 26, 9)
        if len(close) >= 35:
            ema12 = close.ewm(span=12, adjust=False).mean()
            ema26 = close.ewm(span=26, adjust=False).mean()
            dif = ema12 - ema26
            dea = dif.ewm(span=9, adjust=False).mean()
            macd_hist = (dif - dea) * 2
            result["macd_hist"] = round(float(macd_hist.iloc[-1]), 4)
            result["dif"] = round(float(dif.iloc[-1]), 4)
            result["dea"] = round(float(dea.iloc[-1]), 4)

        return result

    @staticmethod
    def _format_cap_cn(cap: float) -> str:
        """市值中文格式化：万/亿/万亿。"""
        if cap is None:
            return "-"
        if cap >= 1_000_000_000_000:
            return f"¥{cap / 1_000_000_000_000:.2f}万亿"
        if cap >= 100_000_000:
            return f"¥{cap / 100_000_000:.1f}亿"
        if cap >= 10_000:
            return f"¥{cap / 10_000:.1f}万"
        return f"¥{cap:,.0f}"

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
