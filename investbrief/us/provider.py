"""
US Market Provider - yfinance powered

Rich data: analyst upgrades/downgrades, EPS estimates, insider trades,
price targets, fundamentals.
"""

import logging
from typing import Dict, List, Any

from .clients import YFinanceClient
from investbrief.core.charts import generate_stock_chart
from investbrief.core.provider import MarketProvider

logger = logging.getLogger(__name__)


class USMarketProvider(MarketProvider):
    market_code = "us"
    country_name = "美国市场"
    flag = "🇺🇸"
    currency = "$"

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
            "10Y国债": "^TNX",
            "WTI原油": "CL=F",
            "美元指数": "DX-Y.NYB",
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

    def _enrich_stock_detail(self, symbol: str, data: Dict[str, Any]) -> None:
        """Enrich a stock data dict with comprehensive detail fields.

        Mutates data in-place. Skips fields that already exist.
        Used by both holdings and recommendations to share the same enrichment logic.
        """
        # Basic quote
        if "price" not in data:
            quote = self.yf.get_quote(symbol)
            if quote:
                data["price"] = quote["price"]
                data["change"] = quote["change_percent"]
                data["currency"] = "$"
                data["volume"] = quote.get("volume")
                data["market_cap"] = quote.get("market_cap")

        # Comprehensive info — merge into existing info dict or create new
        info = self.yf.get_info(symbol) or {}
        full_info = {
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
        if "info" in data:
            full_info.update(data["info"])
        data["info"] = full_info

        # Analyst price targets
        if "targets" not in data:
            targets = self.yf.get_price_targets(symbol)
            if targets:
                data["targets"] = targets
        if "upside_pct" not in data and data.get("price") and data.get("targets", {}).get("mean"):
            upside = ((data["targets"]["mean"] - data["price"]) / data["price"]) * 100
            data["upside_pct"] = round(upside, 1)

        # Recommendation distribution
        if "recommendations" not in data:
            recs = self.yf.get_recommendations(symbol)
            if recs:
                data["recommendations"] = recs

        # Upgrades/downgrades
        if "upgrades" not in data:
            upgrades = self.yf.get_upgrades_downgrades(symbol, limit=5)
            if upgrades:
                data["upgrades"] = upgrades

        # EPS estimates
        if "eps" not in data:
            eps = self.yf.get_earnings_estimate(symbol)
            if eps:
                data["eps"] = eps

        # Earnings history
        if "earnings_history" not in data:
            earnings = self.yf.get_earnings_history(symbol)
            if earnings:
                data["earnings_history"] = earnings

        # Insider transactions
        if "insider_trades" not in data:
            insiders = self.yf.get_insider_transactions(symbol, limit=5)
            if insiders:
                data["insider_trades"] = insiders

        # 6-month chart
        if "chart_b64" not in data:
            history = self.yf.get_history(symbol, period="6mo")
            if history is not None and not history.empty:
                chart_b64 = generate_stock_chart(symbol, history, period="6mo")
                if chart_b64:
                    data["chart_b64"] = chart_b64
                data["history"] = [
                    {
                        "date": idx.strftime("%Y-%m-%d"),
                        "open": round(float(row["Open"]), 2),
                        "high": round(float(row["High"]), 2),
                        "low": round(float(row["Low"]), 2),
                        "close": round(float(row["Close"]), 2),
                        "volume": int(row.get("Volume", 0) or 0),
                    }
                    for idx, row in history.iterrows()
                ]

        # Technical indicators
        if "technicals" not in data:
            tech = self.yf.get_technical_indicators(symbol)
            if tech:
                data["technicals"] = tech

    def get_holdings_data(self, holdings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Get comprehensive data for US holdings."""
        results = []
        for h in holdings:
            symbol = h["symbol"]
            data = {"symbol": symbol, "name": h.get("name", symbol)}
            self._enrich_stock_detail(symbol, data)
            results.append(data)
        return results

    def get_recommendations_from_industries(self, industries: List[str], holdings_symbols: List[str] = None) -> List[Dict[str, Any]]:
        """
        Find high-conviction analyst picks from industry watchlists.

        For each industry, fetches analyst ratings for watchlist stocks,
        filters to those with strong buy/buy consensus, and returns top picks.
        """
        from .watchlist import get_watchlist_stocks, INDUSTRY_LABELS

        holdings_symbols = holdings_symbols or []
        watchlist = get_watchlist_stocks(industries)
        if not watchlist:
            return []

        # Phase 1: lightweight filtering — only fetch recommendation distribution
        candidates = []
        for stock in watchlist:
            symbol = stock["symbol"]
            if symbol in holdings_symbols:
                continue

            recs = self.yf.get_recommendations(symbol)
            if not recs:
                continue

            total = recs.get("strong_buy", 0) + recs.get("buy", 0) + recs.get("hold", 0) + recs.get("sell", 0) + recs.get("strong_sell", 0)
            if total == 0:
                continue

            buy_pct = (recs.get("strong_buy", 0) + recs.get("buy", 0)) / total * 100
            if buy_pct <= 50:
                continue

            candidates.append({
                "symbol": symbol,
                "name": stock["name"],
                "industry": stock["industry"],
                "recommendations": recs,
                "buy_pct": round(buy_pct, 1),
                "total_analysts": total,
            })

        # Sort and take top 5
        candidates.sort(key=lambda x: x.get("buy_pct", 0), reverse=True)
        top = candidates[:5]

        # Phase 2: full enrichment for selected stocks only
        for data in top:
            label = INDUSTRY_LABELS.get(data["industry"], data["industry"])
            data["recommendation_reason"] = f"{label} · {data['buy_pct']:.0f}%买入评级 · {data['total_analysts']}位分析师"
            del data["total_analysts"]
            self._enrich_stock_detail(data["symbol"], data)

        return top

    def get_recommendations(self, industries: List[str], exclude: List[str] | None = None,
                           max_recommendations: int = 3) -> List[Dict[str, Any]]:
        """Get stock recommendations by industry."""
        return self.get_recommendations_from_industries(industries, exclude)

    def get_premarket_movers(self, holdings_symbols: List[str], threshold: float = 2.0) -> List[Dict[str, Any]]:
        """Get holdings with pre-market moves exceeding threshold."""
        movers = []
        for symbol in holdings_symbols:
            data = self.yf.get_premarket_data(symbol)
            if data and abs(data["preMarketChangePercent"]) >= threshold:
                info = self.yf.get_info(symbol) or {}
                data["name"] = info.get("shortName", symbol)
                movers.append(data)
        movers.sort(key=lambda x: abs(x["preMarketChangePercent"]), reverse=True)
        return movers

    def get_earnings_calendar(self, holdings: List[Dict], recommendations: List[Dict]) -> List[Dict[str, Any]]:
        """Get upcoming earnings dates for holdings + recommendations."""
        from datetime import datetime, timedelta

        all_symbols = [(h["symbol"], h.get("name", h["symbol"])) for h in holdings]
        seen = {s[0] for s in all_symbols}
        for r in recommendations:
            if r["symbol"] not in seen:
                all_symbols.append((r["symbol"], r.get("name", r["symbol"])))
                seen.add(r["symbol"])

        now = datetime.now()
        cutoff = now + timedelta(days=21)
        calendar = []

        for symbol, name in all_symbols:
            dates = self.yf.get_earnings_dates(symbol)
            if not dates:
                continue
            for ed in dates:
                try:
                    earnings_dt = datetime.strptime(ed["date"], "%Y-%m-%d")
                except ValueError:
                    continue
                if now <= earnings_dt <= cutoff:
                    calendar.append({
                        "symbol": symbol,
                        "name": name,
                        "date": ed["date"],
                        "days_away": (earnings_dt - now).days,
                    })

        calendar.sort(key=lambda x: x["days_away"])
        return calendar

    def fetch_all(self, holdings: list[dict], industries: list[str],
                 max_recommendations: int = 3) -> dict[str, Any]:
        """获取美股全部数据。"""
        holdings_symbols = [h["symbol"] for h in holdings]

        ctx = {
            "holdings": holdings,
            "holdings_symbols": holdings_symbols,
            "industries": industries,
        }

        # Pre-fetch recommendations for cross-section dependency
        recommendations = self.get_section_data("recommendations", **ctx)
        ctx["recommendations"] = recommendations

        results = {}
        for section_name in ["indices", "economic_calendar", "premarket_movers",
                             "earnings_calendar", "congressional_trades",
                             "holdings", "recommendations"]:
            if section_name == "recommendations":
                results[section_name] = recommendations
            else:
                results[section_name] = self.get_section_data(section_name, **ctx)

        return results

    def get_section_data(self, section_name: str, **kwargs) -> list[dict]:
        """Fetch a single section's data independently."""
        from .calendar import get_upcoming_events_with_yfinance
        from .congress import get_recent_congressional_trades

        dispatch = {
            "indices": lambda: self.get_indices(),
            "economic_calendar": lambda: get_upcoming_events_with_yfinance(),
            "premarket_movers": lambda: self.get_premarket_movers(
                kwargs.get("holdings_symbols", [])
            ),
            "earnings_calendar": lambda: self.get_earnings_calendar(
                kwargs.get("holdings", []),
                kwargs.get("recommendations", []),
            ),
            "congressional_trades": lambda: get_recent_congressional_trades(
                tickers=kwargs.get("holdings_symbols", [])
            ),
            "holdings": lambda: self.get_holdings_data(kwargs.get("holdings", [])),
            "recommendations": lambda: self.get_recommendations_from_industries(
                kwargs.get("industries", []),
                kwargs.get("holdings_symbols", []),
            ),
        }
        fn = dispatch.get(section_name)
        if fn is None:
            raise ValueError(f"Unknown section: {section_name}")
        return fn()

    # ==================== Rendering ====================

    def render_section(self, data: Dict[str, Any], config: Dict[str, Any], *,
                       guidance: Dict[str, str] | None = None) -> str:
        """Render US market section."""
        guidance = guidance or {}

        # Build earnings days mapping for stock annotations
        earnings_symbols = {}
        for e in data.get("earnings_calendar", []):
            earnings_symbols[e["symbol"]] = e["days_away"]

        indices_html = self._render_indices_table(data.get("indices", []), config)
        holdings_html = self._render_holdings(
            data.get("holdings", []), config, earnings_symbols=earnings_symbols
        )
        recommendations_html = self._render_recommendations(
            data.get("recommendations", []), config
        )

        # Pre-market movers (conditional)
        premarket = data.get("premarket_movers", [])
        premarket_html = self._render_premarket(premarket, config) if premarket else ""

        # Earnings calendar (conditional)
        earnings_cal = data.get("earnings_calendar", [])
        earnings_cal_html = self._render_earnings_calendar(earnings_cal) if earnings_cal else ""

        # Economic calendar (conditional)
        econ_cal = data.get("economic_calendar", [])
        econ_cal_html = self._render_economic_calendar(econ_cal) if econ_cal else ""

        # Congressional trades (conditional)
        congress = data.get("congressional_trades", [])
        congress_html = self._render_congressional_trades(congress) if congress else ""

        # Section guidance snippets
        overview_tip = self._guidance_html(guidance.get("market_overview"))
        holdings_tip = self._guidance_html(guidance.get("holdings"))
        recs_tip = self._guidance_html(guidance.get("recommendations"))

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
      {overview_tip}
      {premarket_html}
      <div class="card">
        <div class="card-header" style="padding:12px 15px; background:#f8f9fa; border-bottom:1px solid #e9ecef; font-weight:600;">💼 持仓股票</div>
        <div class="card-body">
          {holdings_html}
        </div>
      </div>
      {holdings_tip}
      {earnings_cal_html}
      {econ_cal_html}
      {congress_html}
      <div class="card">
        <div class="card-header" style="padding:12px 15px; background:#f8f9fa; border-bottom:1px solid #e9ecef; font-weight:600;">⭐ 推荐关注</div>
        <div class="card-body">
          {recommendations_html}
        </div>
      </div>
      {recs_tip}
    </div>'''

    # ==================== Render Helpers ====================

    def _render_premarket(self, movers: List[Dict], config: Dict) -> str:
        if not movers:
            return ""
        rows = ""
        for m in movers:
            change = m["preMarketChangePercent"]
            change_str = f"+{change:.2f}%" if change > 0 else f"{change:.2f}%"
            color = config["color_up"] if change > 0 else config["color_down"]
            name = m.get("name", m["symbol"])
            price = m["preMarketPrice"]
            rows += f'''
      <tr>
        <td>{name} ({m["symbol"]})</td>
        <td>${price:.2f}</td>
        <td style="color:{color}; font-weight:bold;">{change_str}</td>
      </tr>'''
        return f'''
      <div class="card">
        <div class="card-header" style="padding:12px 15px; background:#fff3cd; border-bottom:1px solid #ffeeba; font-weight:600;">🔄 盘前异动</div>
        <div class="card-body">
          <table>
<thead><tr><th>股票</th><th>盘前价格</th><th>盘前涨跌</th></tr></thead>
<tbody>{rows}</tbody>
</table>
        </div>
      </div>'''

    def _render_earnings_calendar(self, calendar: List[Dict]) -> str:
        if not calendar:
            return ""
        rows = ""
        for e in calendar:
            days = e["days_away"]
            urgency = "color:#e74c3c; font-weight:bold;" if days <= 3 else "color:#f39c12;" if days <= 7 else ""
            rows += f'''
      <tr>
        <td>{e["name"]} ({e["symbol"]})</td>
        <td>{e["date"]}</td>
        <td style="{urgency}">{days}天后</td>
      </tr>'''
        return f'''
      <div class="card">
        <div class="card-header" style="padding:12px 15px; background:#f8f9fa; border-bottom:1px solid #e9ecef; font-weight:600;">📅 财报日历</div>
        <div class="card-body">
          <table>
<thead><tr><th>股票</th><th>财报日期</th><th>倒计时</th></tr></thead>
<tbody>{rows}</tbody>
</table>
        </div>
      </div>'''

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

    def _render_congressional_trades(self, trades: List[Dict]) -> str:
        if not trades:
            return ""
        rows = ""
        for t in trades:
            tx_type = t.get("transaction_type", "")
            action_color = "#27ae60" if "purchase" in tx_type.lower() or "buy" in tx_type.lower() else "#e74c3c"
            action_label = "买入" if "purchase" in tx_type.lower() or "buy" in tx_type.lower() else "卖出"
            rows += f'''
      <tr>
        <td>{t["representative"]}</td>
        <td>{t["ticker"]}</td>
        <td style="color:{action_color}; font-weight:600;">{action_label}</td>
        <td>{t["amount"]}</td>
        <td>{t["transaction_date"]}</td>
        <td style="font-size:11px; color:#999;">{t["source"]}</td>
      </tr>'''
        return f'''
      <div class="card">
        <div class="card-header" style="padding:12px 15px; background:#fff8f0; border-bottom:1px solid #ffe0b2; font-weight:600;">🏛️ 国会议员交易</div>
        <div class="card-body">
          <table>
<thead><tr><th>议员</th><th>股票</th><th>操作</th><th>金额</th><th>日期</th><th>来源</th></tr></thead>
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

    def _render_holdings(self, holdings: List[Dict], config: Dict, *,
                         earnings_symbols: Dict[str, int] | None = None) -> str:
        if not holdings:
            return '<div class="no-data">📌 当前无持仓</div>'

        html = ""
        for h in holdings:
            html += self._render_stock_card(h, config, earnings_symbols=earnings_symbols)
        return html

    def _render_stock_card(self, stock: Dict, config: Dict, *,
                           earnings_symbols: Dict[str, int] | None = None) -> str:
        change = stock.get("change", 0)
        change_str = f"+{change:.2f}%" if change > 0 else f"{change:.2f}%"
        color = config["color_up"] if change > 0 else (config["color_down"] if change < 0 else "#7f8c8d")
        currency = stock.get("currency", "$")
        price = stock.get("price", 0)
        info = stock.get("info", {})
        short_name = info.get("short_name", stock.get("name", stock["symbol"]))
        symbol = stock["symbol"]

        html = f'''
<div class="stock-detail" style="background:#f8f9fa; padding:12px; margin:8px 0;">
  <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; margin-bottom:8px;">
    <tr>
      <td style="font-weight:600; font-size:15px;">{short_name} ({symbol})</td>
      <td style="text-align:right; font-size:18px; font-weight:bold; color:{color};">{currency}{price:,.2f} <small>{change_str}</small></td>
    </tr>
  </table>'''

        # Rule-based stock annotations
        annotations = self._get_stock_annotations(stock, earnings_symbols)
        if annotations:
            tags_html = " ".join(
                f'<span style="display:inline-block; font-size:11px; padding:2px 6px; border-radius:3px; margin:2px 2px 2px 0; {a["style"]}">{a["text"]}</span>'
                for a in annotations
            )
            html += f'''
  <div style="margin:4px 0 6px 0;">{tags_html}</div>'''

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

        # 52-Week Range position bar
        if info.get("52wk_high") and info.get("52wk_low") and price:
            low_52 = info["52wk_low"]
            high_52 = info["52wk_high"]
            if high_52 > low_52:
                pct_pos = max(0, min(100, ((price - low_52) / (high_52 - low_52)) * 100))
                bar_color = "#27ae60" if pct_pos > 60 else "#f39c12" if pct_pos > 30 else "#e74c3c"
                html += f'''
  <div style="margin: 6px 0;">
    <div style="background:#eee; height:6px; border-radius:3px; position:relative;">
      <div style="background:{bar_color}; height:6px; border-radius:3px; width:{pct_pos:.1f}%;"></div>
    </div>
    <div style="display:flex; justify-content:space-between; font-size:11px; color:#999; margin-top:2px;">
      <span>{currency}{low_52:,.0f}</span>
      <span style="color:{bar_color}; font-weight:600;">52周位置: {pct_pos:.0f}%</span>
      <span>{currency}{high_52:,.0f}</span>
    </div>
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
        <td style="padding:4px 5px; border-bottom:1px solid #eee; text-align:right;">{currency}{f"{u['price_target']:,.0f}" if u.get('price_target') is not None else '-'}</td>
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

        # Technical indicators
        techs = stock.get("technicals")
        if techs:
            rsi = techs.get("rsi_14")
            rsi_color = "#e74c3c" if rsi and rsi > 70 else "#27ae60" if rsi and rsi < 30 else "#7f8c8d"
            rsi_label = "超买" if rsi and rsi > 70 else "超卖" if rsi and rsi < 30 else ""

            macd_hist = techs.get("macd_hist", 0)
            macd_label = "金叉" if macd_hist > 0 else "死叉"
            macd_color = "#27ae60" if macd_hist > 0 else "#e74c3c"

            html += f'''
  <div style="background:#f0f4f8; border-radius:6px; padding:10px; margin:8px 0; border-left:3px solid #3498db;">
    <div style="font-weight:600; margin-bottom:6px; color:#2c3e50;">📊 技术指标</div>
    <div style="display:flex; flex-wrap:wrap; gap:12px; font-size:13px;">'''
            if rsi:
                html += f'<span>RSI(14): <strong style="color:{rsi_color}">{rsi:.1f}</strong> {rsi_label}</span>'
            sma_50 = techs.get("sma_50")
            if sma_50 and price:
                sma_pct = ((price - sma_50) / sma_50) * 100
                html += f'<span>MA50: {currency}{sma_50:.2f} ({sma_pct:+.1f}%)</span>'
            sma_200 = techs.get("sma_200")
            if sma_200 and price:
                sma2_pct = ((price - sma_200) / sma_200) * 100
                html += f'<span>MA200: {currency}{sma_200:.2f} ({sma2_pct:+.1f}%)</span>'
            if macd_hist is not None:
                html += f'<span>MACD: <strong style="color:{macd_color}">{macd_label}</strong></span>'
            html += '</div></div>'

        # Insider buys
        insiders = stock.get("insider_trades")
        if insiders:
            html += '''
  <div class="insider-section">
    <div style="font-weight: 600; margin-bottom: 6px; color: #2c3e50;">👔 内部人买入</div>
    <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; font-size:12px; table-layout:fixed;">
      <colgroup><col style="width:35%"/><col style="width:20%"/><col style="width:25%"/><col style="width:20%"/></colgroup>
      <tr style="background:rgba(0,0,0,0.03);">
        <th style="text-align:left; padding:4px 5px; font-weight:600; color:#2c3e50; border-bottom:1px solid #ccc;">人员</th>
        <th style="text-align:right; padding:4px 5px; font-weight:600; color:#2c3e50; border-bottom:1px solid #ccc;">股数</th>
        <th style="text-align:right; padding:4px 5px; font-weight:600; color:#2c3e50; border-bottom:1px solid #ccc;">金额</th>
        <th style="text-align:right; padding:4px 5px; font-weight:600; color:#2c3e50; border-bottom:1px solid #ccc;">日期</th>
      </tr>'''
            for ins in insiders[:5]:
                value_str = f'{currency}{ins["value"]:,.0f}' if ins.get("value") else "-"
                shares_str = f'{ins["shares"]:,}' if ins.get("shares") else "-"
                person = ins.get("insider", "")
                position = ins.get("position", "")
                person_display = f"{person} ({position})" if position else person
                html += f'''
      <tr>
        <td style="padding:4px 5px; border-bottom:1px solid #f0e8d8; font-weight:500; color:#2c3e50; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">{person_display}</td>
        <td style="padding:4px 5px; border-bottom:1px solid #f0e8d8; text-align:right; color:#2e7d32;">{shares_str}</td>
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

    @staticmethod
    def _guidance_html(text: str | None) -> str:
        """Render a guidance tip block. Returns empty string if no text."""
        if not text:
            return ""
        return f'''
      <div style="font-size:12px; color:#6c757d; background:#f8f9fa; padding:8px 12px; border-radius:4px; margin:4px 0 8px 0; border-left:3px solid #adb5bd; line-height:1.5;">
        💡 {text}
      </div>'''

    # ==================== Stock Annotations ====================

    @staticmethod
    def _get_stock_annotations(stock: Dict, earnings_symbols: Dict[str, int] | None = None) -> list[dict]:
        """Rule-based annotations for stock cards. Returns list of {text, style}."""
        annotations = []
        techs = stock.get("technicals", {})
        info = stock.get("info", {})
        symbol = stock["symbol"]

        # RSI signals
        rsi = techs.get("rsi_14")
        if rsi:
            if rsi > 70:
                annotations.append({"text": "⚠️ RSI超买，注意回调", "style": "background:#fde8e8; color:#c62828;"})
            elif rsi < 30:
                annotations.append({"text": "💡 RSI超卖，关注反弹机会", "style": "background:#e8f5e9; color:#2e7d32;"})

        # MACD signals
        macd_hist = techs.get("macd_hist")
        if macd_hist is not None:
            if macd_hist > 0:
                annotations.append({"text": "📊 MACD金叉", "style": "background:#e8f5e9; color:#2e7d32;"})
            elif macd_hist < 0 and (rsi and rsi < 50):
                annotations.append({"text": "📊 MACD死叉，短期承压", "style": "background:#fde8e8; color:#c62828;"})

        # Target upside
        upside = stock.get("upside_pct")
        if upside and upside > 30:
            annotations.append({"text": f"🎯 分析师看好，上涨空间{upside:.0f}%", "style": "background:#e3f2fd; color:#1565c0;"})

        # Earnings surprise
        earnings = stock.get("earnings_history")
        if earnings:
            last = earnings[0]
            surprise = last.get("surprise_pct", 0) * 100
            if abs(surprise) > 10:
                label = "超预期" if surprise > 0 else "不及预期"
                color = "#2e7d32" if surprise > 0 else "#c62828"
                bg = "#e8f5e9" if surprise > 0 else "#fde8e8"
                annotations.append({"text": f"💰 上季财报{label}{surprise:+.0f}%", "style": f"background:{bg}; color:{color};"})

        # Insider buys
        insiders = stock.get("insider_trades")
        if insiders and len(insiders) >= 2:
            annotations.append({"text": "👔 多位内部人买入", "style": "background:#e8f5e9; color:#2e7d32;"})

        # Earnings approaching
        if earnings_symbols and symbol in earnings_symbols:
            days = earnings_symbols[symbol]
            if days <= 3:
                annotations.append({"text": "📅 财报临近，波动可能加大", "style": "background:#fff3cd; color:#856404;"})

        return annotations[:4]  # Max 4 annotations per card

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
