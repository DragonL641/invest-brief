"""
US Market Provider - yfinance powered

Rich data: analyst upgrades/downgrades, EPS estimates, insider trades,
price targets, fundamentals.
"""

import logging
from typing import Dict, List, Any

from .api_clients import YFinanceClient
from .charts import generate_stock_chart

logger = logging.getLogger(__name__)


class USMarketProvider:
    market_code = "us"
    country_name = "美国市场"
    flag = "🇺🇸"

    def __init__(self):
        self.yf = YFinanceClient()

    # ==================== Data Methods ====================

    def get_indices(self) -> List[Dict[str, Any]]:
        """Get US market indices."""
        index_symbols = {
            "S&P 500": "^GSPC",
            "NASDAQ": "^IXIC",
            "Dow Jones": "^DJI",
            "VIX": "^VIX",
        }
        results = []
        for name, symbol in index_symbols.items():
            quote = self.yf.get_quote(symbol)
            if quote:
                results.append({
                    "name": name,
                    "point": quote["price"],
                    "change": quote["change_percent"],
                    "volume": self._format_volume(quote.get("volume")),
                })
        return results

    def get_holdings_data(self, holdings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Get comprehensive data for US holdings."""
        results = []
        for h in holdings:
            symbol = h["symbol"]
            data = {"symbol": symbol, "name": h.get("name", symbol)}

            # Basic quote
            quote = self.yf.get_quote(symbol)
            if quote:
                data["price"] = quote["price"]
                data["change"] = quote["change_percent"]
                data["currency"] = "$"
                data["volume"] = quote.get("volume")
                data["market_cap"] = quote.get("market_cap")

            # Comprehensive info
            info = self.yf.get_info(symbol) or {}
            data["info"] = {
                "pe": info.get("trailingPE"),
                "forward_pe": info.get("forwardPE"),
                "beta": info.get("beta"),
                "52wk_high": info.get("fiftyTwoWeekHigh"),
                "52wk_low": info.get("fiftyTwoWeekLow"),
                "50d_avg": info.get("fiftyDayAverage"),
                "200d_avg": info.get("twoHundredDayAverage"),
                "sector": info.get("sector", ""),
                "industry": info.get("industry", ""),
                "short_name": info.get("shortName", symbol),
                "num_analysts": info.get("numberOfAnalystOpinions", 0),
            }

            # Analyst price targets
            targets = self.yf.get_price_targets(symbol)
            if targets:
                data["targets"] = targets
                # Calculate upside
                if data.get("price") and targets.get("mean"):
                    upside = ((targets["mean"] - data["price"]) / data["price"]) * 100
                    data["upside_pct"] = round(upside, 1)

            # Recommendation distribution
            recs = self.yf.get_recommendations(symbol)
            if recs:
                data["recommendations"] = recs

            # Upgrades/downgrades (real firm data)
            upgrades = self.yf.get_upgrades_downgrades(symbol, limit=5)
            if upgrades:
                data["upgrades"] = upgrades

            # EPS estimates
            eps = self.yf.get_earnings_estimate(symbol)
            if eps:
                data["eps"] = eps

            # Earnings history (last quarter surprise)
            earnings = self.yf.get_earnings_history(symbol)
            if earnings:
                data["earnings_history"] = earnings

            # Insider transactions
            insiders = self.yf.get_insider_transactions(symbol, limit=5)
            if insiders:
                data["insider_trades"] = insiders

            # 1-month chart
            history = self.yf.get_history(symbol, period="1mo")
            if history is not None:
                chart_b64 = generate_stock_chart(symbol, history, period="1mo")
                if chart_b64:
                    data["chart_b64"] = chart_b64

            results.append(data)
        return results

    def get_recommendations_from_industries(self, industries: List[str], holdings_symbols: List[str] = None) -> List[Dict[str, Any]]:
        """
        Find high-conviction analyst picks from industry watchlists.

        For each industry, fetches analyst ratings for watchlist stocks,
        filters to those with strong buy/buy consensus, and returns top picks.
        """
        from .watchlists import get_watchlist_stocks, INDUSTRY_LABELS

        holdings_symbols = holdings_symbols or []
        watchlist = get_watchlist_stocks(industries)
        if not watchlist:
            return []

        results = []
        for stock in watchlist:
            symbol = stock["symbol"]
            # Skip if already in holdings
            if symbol in holdings_symbols:
                continue

            # Get recommendation distribution
            recs = self.yf.get_recommendations(symbol)
            if not recs:
                continue

            total = recs.get("strong_buy", 0) + recs.get("buy", 0) + recs.get("hold", 0) + recs.get("sell", 0) + recs.get("strong_sell", 0)
            if total == 0:
                continue

            buy_pct = (recs.get("strong_buy", 0) + recs.get("buy", 0)) / total * 100
            # Only include if buy rating > 50%
            if buy_pct <= 50:
                continue

            # Get basic data
            data = {"symbol": symbol, "name": stock["name"], "industry": stock["industry"]}

            quote = self.yf.get_quote(symbol)
            if quote:
                data["price"] = quote["price"]
                data["change"] = quote["change_percent"]
                data["currency"] = "$"

            info = self.yf.get_info(symbol) or {}
            data["info"] = {
                "short_name": info.get("shortName", stock["name"]),
                "sector": info.get("sector", ""),
                "num_analysts": info.get("numberOfAnalystOpinions", 0),
            }

            # Price target
            targets = self.yf.get_price_targets(symbol)
            if targets and targets.get("mean"):
                data["targets"] = targets
                if data.get("price") and targets.get("mean"):
                    upside = ((targets["mean"] - data["price"]) / data["price"]) * 100
                    data["upside_pct"] = round(upside, 1)

            data["recommendations"] = recs
            data["buy_pct"] = round(buy_pct, 1)
            data["recommendation_reason"] = f"{INDUSTRY_LABELS.get(stock['industry'], stock['industry'])} · {buy_pct:.0f}%买入评级 · {total}位分析师"

            results.append(data)

        # Sort by buy_pct descending, take top 5
        results.sort(key=lambda x: x.get("buy_pct", 0), reverse=True)
        return results[:5]

    def get_recommendations(self) -> List[Dict[str, Any]]:
        """Get stock recommendations. Use get_recommendations_from_industries() instead."""
        return []

    # ==================== Rendering ====================

    def render_section(self, data: Dict[str, Any], config: Dict[str, Any]) -> str:
        """Render US market section."""
        indices_html = self._render_indices_table(data.get("indices", []), config)
        holdings_html = self._render_holdings(data.get("holdings", []), config)
        recommendations_html = self._render_recommendations(
            data.get("recommendations", []), config
        )

        return f'''
    <div class="section">
      <div class="country-header" style="background-color:#2c3e50; color:#ffffff; padding:15px 20px; margin-bottom:15px;">
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

      <div class="card">
        <div class="card-header" style="padding:12px 15px; background:#f8f9fa; border-bottom:1px solid #e9ecef; font-weight:600;">⭐ 推荐关注</div>
        <div class="card-body">
          {recommendations_html}
        </div>
      </div>
    </div>'''

    # ==================== Render Helpers ====================

    def _render_indices_table(self, indices: List[Dict], config: Dict) -> str:
        rows = ""
        for idx in indices:
            change = idx.get("change", 0)
            change_str = f"+{change:.2f}%" if change > 0 else f"{change:.2f}%"
            color = config["color_up"] if change > 0 else (config["color_down"] if change < 0 else "#7f8c8d")
            rows += f'''
      <tr>
        <td>{idx['name']}</td>
        <td>{idx['point']:,.2f}</td>
        <td style="color: {color}; font-weight: bold;">{change_str}</td>
        <td>{idx.get('volume', '-')}</td>
      </tr>'''
        return f'''<table>
<thead><tr><th>指数</th><th>点位</th><th>涨跌幅</th><th>成交量</th></tr></thead>
<tbody>{rows}</tbody>
</table>'''

    def _render_holdings(self, holdings: List[Dict], config: Dict) -> str:
        if not holdings:
            return '<div class="no-data">📌 当前无持仓</div>'

        html = ""
        for h in holdings:
            html += self._render_stock_card(h, config)
        return html

    def _render_stock_card(self, stock: Dict, config: Dict) -> str:
        change = stock.get("change", 0)
        change_str = f"+{change:.2f}%" if change > 0 else f"{change:.2f}%"
        color = config["color_up"] if change > 0 else (config["color_down"] if change < 0 else "#7f8c8d")
        currency = stock.get("currency", "$")
        price = stock.get("price", 0)
        info = stock.get("info", {})
        short_name = info.get("short_name", stock.get("name", stock["symbol"]))

        html = f'''
<div class="stock-detail" style="background:#f8f9fa; padding:12px; margin:8px 0;">
  <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; margin-bottom:8px;">
    <tr>
      <td style="font-weight:600; font-size:15px;">{short_name} ({stock['symbol']})</td>
      <td style="text-align:right; font-size:18px; font-weight:bold; color:{color};">{currency}{price:,.2f} <small>{change_str}</small></td>
    </tr>
  </table>'''

        # Key metrics
        metrics_items = []
        if stock.get("market_cap"):
            metrics_items.append(f'<span class="label">市值:</span> {self._format_cap(stock["market_cap"])}')
        if info.get("pe"):
            metrics_items.append(f'<span class="label">P/E:</span> {info["pe"]:.1f}')
        if info.get("beta"):
            metrics_items.append(f'<span class="label">Beta:</span> {info["beta"]:.2f}')
        if info.get("52wk_high") and info.get("52wk_low"):
            metrics_items.append(
                f'<span class="label">52周:</span> {currency}{info["52wk_low"]:,.0f} ~ {currency}{info["52wk_high"]:,.0f}'
            )
        if info.get("50d_avg") and price:
            pct = ((price - info["50d_avg"]) / info["50d_avg"]) * 100
            metrics_items.append(f'<span class="label">50日均线:</span> {currency}{info["50d_avg"]:,.2f} ({pct:+.1f}%)')

        if metrics_items:
            metrics_html = "".join(f'<div class="metric">{m}</div>' for m in metrics_items)
            html += f'''
  <div class="metrics-row">
    {metrics_html}
  </div>'''

        # Analyst targets
        targets = stock.get("targets")
        if targets and targets.get("mean"):
            upside = stock.get("upside_pct", 0)
            upside_color = config["color_up"] if upside > 0 else config["color_down"]

            # Rating distribution bar
            recs = stock.get("recommendations")
            total = sum(recs[k] for k in ("strong_buy", "buy", "hold", "sell", "strong_sell")) if recs else 0
            num_analysts = total if total > 0 else info.get("num_analysts", 0)

            html += f'''
  <div class="analyst-section">
    <div class="analyst-row">
      <span><span class="analyst-label">🎯 目标价:</span> {currency}{targets['mean']:,.0f} (均值)</span>
      <span style="color: {upside_color}; font-weight: 600;">↑ {upside:+.1f}%</span>
    </div>
    <div class="analyst-row">
      <span><span class="analyst-label">范围:</span> {currency}{targets.get('low', 0):,.0f} ~ {currency}{targets.get('high', 0):,.0f}</span>
      <span style="color: #999;">{num_analysts}位分析师</span>
    </div>'''

            if recs and total > 0:
                buy_count = recs["strong_buy"] + recs["buy"]
                hold_count = recs["hold"]
                sell_count = recs["sell"] + recs["strong_sell"]
                buy_pct_val = buy_count / total * 100
                hold_pct_val = hold_count / total * 100
                sell_pct_val = sell_count / total * 100

                html += f'''
    <table width="100%" cellpadding="0" cellspacing="0" style="font-size:12px; margin:6px 0;">
      <tr>
        <td width="36" style="color:#666; padding:3px 0;">买入</td>
        <td width="24" style="font-weight:600; color:#27ae60; padding:3px 4px 3px 0;">{buy_count}</td>
        <td style="padding:3px 0;"><div style="background:#e8f5e9; height:6px; border-radius:3px;"><div style="background:#27ae60; height:6px; border-radius:3px; width:{buy_pct_val:.1f}%;"></div></div></td>
        <td width="36" style="text-align:right; color:#999; padding:3px 0 3px 4px;">{buy_pct_val:.0f}%</td>
      </tr>
      <tr>
        <td style="color:#666; padding:3px 0;">持有</td>
        <td style="font-weight:600; color:#f39c12; padding:3px 4px 3px 0;">{hold_count}</td>
        <td style="padding:3px 0;"><div style="background:#fef9e7; height:6px; border-radius:3px;"><div style="background:#f39c12; height:6px; border-radius:3px; width:{hold_pct_val:.1f}%;"></div></div></td>
        <td style="text-align:right; color:#999; padding:3px 0 3px 4px;">{hold_pct_val:.0f}%</td>
      </tr>
      <tr>
        <td style="color:#666; padding:3px 0;">卖出</td>
        <td style="font-weight:600; color:#e74c3c; padding:3px 4px 3px 0;">{sell_count}</td>
        <td style="padding:3px 0;"><div style="background:#fdedec; height:6px; border-radius:3px;"><div style="background:#e74c3c; height:6px; border-radius:3px; width:{sell_pct_val:.1f}%;"></div></div></td>
        <td style="text-align:right; color:#999; padding:3px 0 3px 4px;">{sell_pct_val:.0f}%</td>
      </tr>
    </table>'''
            html += '</div>'

        # Upgrades/downgrades
        upgrades = stock.get("upgrades")
        if upgrades:
            html += '''
  <div class="analyst-section">
    <div style="font-weight: 600; margin-bottom: 6px; color: #2c3e50;">📈 最近评级变动</div>
    <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; font-size:12px; table-layout:fixed;">
      <colgroup><col style="width:30%"/><col style="width:25%"/><col style="width:20%"/><col style="width:25%"/></colgroup>
      <tr style="background:rgba(0,0,0,0.03);">
        <th style="text-align:left; padding:4px 5px; font-weight:600; color:#2c3e50; border-bottom:1px solid #ccc;">机构</th>
        <th style="text-align:left; padding:4px 5px; font-weight:600; color:#2c3e50; border-bottom:1px solid #ccc;">评级</th>
        <th style="text-align:right; padding:4px 5px; font-weight:600; color:#2c3e50; border-bottom:1px solid #ccc;">目标价</th>
        <th style="text-align:right; padding:4px 5px; font-weight:600; color:#2c3e50; border-bottom:1px solid #ccc;">日期</th>
      </tr>'''
            for u in upgrades[:5]:
                html += f'''
      <tr>
        <td style="padding:4px 5px; border-bottom:1px solid #eee; font-weight:500; color:#2c3e50; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">{u['firm']}</td>
        <td style="padding:4px 5px; border-bottom:1px solid #eee; color:#555; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">{u['to_grade']} {u.get('action', '')}</td>
        <td style="padding:4px 5px; border-bottom:1px solid #eee; text-align:right;">{currency}{u['price_target']:,.0f}</td>
        <td style="padding:4px 5px; border-bottom:1px solid #eee; text-align:right; color:#999; font-size:11px;">{u['date']}</td>
      </tr>'''
            html += '</table></div>'

        # EPS estimates
        eps = stock.get("eps")
        if eps:
            html += '''
  <div class="eps-section">
    <div style="font-weight: 600; margin-bottom: 6px; color: #2c3e50;">💰 EPS 预估</div>'''
            period_labels = {"0q": "当季", "+1q": "下季", "0y": "今年", "+1y": "明年"}
            for period in ["0q", "0y"]:
                if period in eps:
                    e = eps[period]
                    growth_str = f"+{e['growth']*100:.1f}%" if e.get("growth") else "-"
                    html += f'''
    <div class="eps-row">
      <span class="eps-label">{period_labels.get(period, period)}:</span>
      <span>{currency}{e['avg']:.2f} (预期增长 {growth_str})</span>
    </div>'''

            # Last earnings surprise
            earnings = stock.get("earnings_history")
            if earnings and len(earnings) > 0:
                last = earnings[0]
                surprise = last.get("surprise_pct", 0) * 100
                cls = "earnings-beat" if surprise >= 0 else "earnings-miss"
                html += f'''
    <div class="eps-row" style="margin-top: 4px;">
      <span class="eps-label">上季财报:</span>
      <span>实际 {currency}{last['eps_actual']:.2f} vs 预期 {currency}{last['eps_estimate']:.2f} (<span class="{cls}">{surprise:+.1f}%</span>)</span>
    </div>'''
            html += '</div>'

        # Insider trades
        insiders = stock.get("insider_trades")
        if insiders:
            html += '''
  <div class="insider-section">
    <div style="font-weight: 600; margin-bottom: 6px; color: #2c3e50;">👔 内部人交易</div>
    <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; font-size:12px; table-layout:fixed;">
      <colgroup><col style="width:30%"/><col style="width:15%"/><col style="width:15%"/><col style="width:20%"/><col style="width:20%"/></colgroup>
      <tr style="background:rgba(0,0,0,0.03);">
        <th style="text-align:left; padding:4px 5px; font-weight:600; color:#2c3e50; border-bottom:1px solid #ccc;">人员</th>
        <th style="text-align:left; padding:4px 5px; font-weight:600; color:#2c3e50; border-bottom:1px solid #ccc;">操作</th>
        <th style="text-align:right; padding:4px 5px; font-weight:600; color:#2c3e50; border-bottom:1px solid #ccc;">股数</th>
        <th style="text-align:right; padding:4px 5px; font-weight:600; color:#2c3e50; border-bottom:1px solid #ccc;">金额</th>
        <th style="text-align:right; padding:4px 5px; font-weight:600; color:#2c3e50; border-bottom:1px solid #ccc;">日期</th>
      </tr>'''
            for ins in insiders[:5]:
                action_label = ins.get("transaction", "")
                action_color = "#27ae60" if "Buy" in action_label else "#e74c3c" if "Sale" in action_label else "#555"
                value_str = f'{currency}{ins["value"]:,.0f}' if ins.get("value") else "-"
                shares_str = f'{ins["shares"]:,}' if ins.get("shares") else "-"
                person = ins.get("insider", "")
                position = ins.get("position", "")
                person_display = f"{person} ({position})" if position else person
                html += f'''
      <tr>
        <td style="padding:4px 5px; border-bottom:1px solid #f0e8d8; font-weight:500; color:#2c3e50; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">{person_display}</td>
        <td style="padding:4px 5px; border-bottom:1px solid #f0e8d8; color:{action_color}; font-weight:500;">{action_label}</td>
        <td style="padding:4px 5px; border-bottom:1px solid #f0e8d8; text-align:right;">{shares_str}</td>
        <td style="padding:4px 5px; border-bottom:1px solid #f0e8d8; text-align:right;">{value_str}</td>
        <td style="padding:4px 5px; border-bottom:1px solid #f0e8d8; text-align:right; color:#999; font-size:11px;">{ins.get("date", "")}</td>
      </tr>'''
            html += '</table></div>'

        # 6-month chart
        chart_b64 = stock.get("chart_b64")
        if chart_b64:
            symbol = stock["symbol"]
            html += f'''
  <div style="margin: 8px 0;">
    <img src="data:image/png;base64,{chart_b64}" alt="{symbol} chart" style="width:100%; max-width:760px; border-radius:6px; border:1px solid #eee;" />
    <div style="text-align: center; margin-top: 4px;">
      <a href="https://www.tradingview.com/symbols/NASDAQ-{symbol}/" style="color: #2980b9; font-size: 12px; text-decoration: none;" target="_blank">📈 查看多时间框架走势图 (1D / 1M / 6M / 1Y / 3Y)</a>
    </div>
  </div>'''

        html += '</div>'
        return html

    def _render_recommendations(self, recommendations: List[Dict], config: Dict) -> str:
        if not recommendations:
            return '<div class="no-data">📌 暂无推荐关注</div>'
        html = ""
        for r in recommendations:
            card_html = self._render_stock_card(r, config)
            # Add recommendation reason badge
            reason = r.get("recommendation_reason", "")
            if reason:
                badge = f'<div style="background:#fff3cd; padding:6px 10px; border-radius:0 0 6px 6px; font-size:12px; color:#856404; border:1px solid #ffeeba; border-top:none;">💡 {reason}</div>'
                # Insert badge before the closing </div> of the stock-detail
                card_html = card_html.rstrip()
                if card_html.endswith('</div>'):
                    card_html = card_html[:-6] + badge + '</div>'
            html += card_html
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

    @staticmethod
    def _format_cap(cap: float) -> str:
        if cap >= 1_000_000_000_000:
            return f"${cap/1_000_000_000_000:.1f}万亿"
        if cap >= 1_000_000_000:
            return f"${cap/1_000_000_000:.0f}亿"
        if cap >= 1_000_000:
            return f"${cap/1_000_000:.0f}M"
        return f"${cap:,.0f}"
