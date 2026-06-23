"""
A股 Market Provider — AKShare powered

Data fetching + HTML rendering for A-share market reports.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import pandas as pd

from investbrief.core.charts import generate_stock_chart
from investbrief.core.provider import MarketProvider
from investbrief.cn.client import AKShareClient
from investbrief.cn.watchlist import INDUSTRY_LABELS, INDUSTRY_SECTOR_NAMES
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

    def _batch_stock_quotes(self, symbols: list[str]) -> dict[str, dict]:
        """Batch fetch stock quotes. Returns {symbol: quote_dict}."""
        try:
            quotes_list = self.client.get_stock_quotes(symbols)
            return {q["symbol"]: q for q in quotes_list}
        except Exception as e:
            logger.warning(f"Batch quote fetch failed: {e}")
            return {}

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

    def get_holdings_data(self, holdings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """获取持仓个股详情。并发拉取每只股票的多个数据源。"""
        symbols = [h["symbol"] for h in holdings]

        # Pre-fetch all heavy batch data in parallel
        with ThreadPoolExecutor(max_workers=3) as pre_pool:
            quote_future = pre_pool.submit(self._batch_stock_quotes, symbols)
            research_future = pre_pool.submit(self.client.get_institutional_research_batch, symbols)
            # Pre-warm insider trades cache
            pre_pool.submit(self.client._get_all_insider_trades_df)

            batch_quotes = quote_future.result()
            try:
                batch_research = research_future.result()
            except Exception:
                batch_research = {}

        def _process_holding(h: dict[str, Any]) -> dict[str, Any]:
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

            # Skip inst_research in _fetch_stock_details since batch result exists
            details = self._fetch_stock_details(symbol, skip_keys={"inst_research"})
            details["inst_research"] = batch_research.get(symbol, [])

            data.update(details)
            return data

        # Parallelize across holdings
        results = [None] * len(holdings)
        with ThreadPoolExecutor(max_workers=min(len(holdings), 4)) as pool:
            futures = {pool.submit(_process_holding, h): i for i, h in enumerate(holdings)}
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    results[idx] = future.result()
                except Exception as e:
                    logger.warning(f"Holding fetch error ({holdings[idx]['symbol']}): {e}")
                    results[idx] = {"symbol": holdings[idx]["symbol"], "name": holdings[idx].get("name", "")}

        return [r for r in results if r is not None]

    def _fetch_stock_details(self, symbol: str, skip_keys: set[str] | None = None) -> dict[str, Any]:
        """并发拉取单只股票的多个独立数据源。"""
        skip_keys = skip_keys or set()
        client = self.client
        all_tasks = {
            "history": lambda: client.get_stock_history(symbol, days=180),
            "rating": lambda: client.get_analyst_rating_summary(symbol),
            "financial": lambda: client.get_financial_indicators(symbol),
            "insiders": lambda: client.get_insider_trades(symbol),
            "inst_research": lambda: client.get_institutional_research(symbol),
            "reports": lambda: client.get_research_reports(symbol, limit=5),
            "fund_flow": lambda: client.get_stock_fund_flow(symbol),
        }
        tasks = {k: v for k, v in all_tasks.items() if k not in skip_keys}

        results: dict[str, Any] = {}
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(fn): key for key, fn in tasks.items()}
            for future in as_completed(futures):
                key = futures[future]
                try:
                    results[key] = future.result()
                except Exception as e:
                    logger.warning(f"Concurrent fetch error ({symbol}.{key}): {e}")

        data: dict[str, Any] = {}

        history = results.get("history")
        if history is not None and not history.empty:
            chart_df = history.rename(columns={
                "open": "Open", "high": "High", "low": "Low",
                "close": "Close", "volume": "Volume",
            })
            chart_b64 = generate_stock_chart(symbol, chart_df, period="6月")
            if chart_b64:
                data["chart_b64"] = chart_b64
            data["technicals"] = self._calc_technicals(history)
            data["history"] = [
                {
                    "date": idx.strftime("%Y-%m-%d"),
                    "open": round(float(row["open"]), 2),
                    "high": round(float(row["high"]), 2),
                    "low": round(float(row["low"]), 2),
                    "close": round(float(row["close"]), 2),
                    "volume": int(row.get("volume", 0) or 0),
                }
                for idx, row in history.iterrows()
            ]

        if results.get("rating"):
            data["rating_summary"] = results["rating"]
        if results.get("financial"):
            data["financial"] = results["financial"]
        if results.get("insiders"):
            data["insider_trades"] = results["insiders"]
        if results.get("inst_research"):
            data["institutional_research"] = results["inst_research"]
        if results.get("reports"):
            data["research_reports"] = results["reports"]
        if results.get("fund_flow"):
            data["fund_flow"] = results["fund_flow"]

        return data

    def get_recommendations(
        self, industries: list[str], exclude: list[str] | None = None,
        max_recommendations: int = 3,
    ) -> list[dict[str, Any]]:
        """动态选股：基于行业成分股 + 资金流粗排，分析师评级精排。"""
        exclude = exclude or []

        # Step 1: 批量获取行业成分股
        industry_stocks: list[dict[str, Any]] = []
        for industry_key in industries:
            board_name = INDUSTRY_SECTOR_NAMES.get(industry_key)
            if not board_name:
                continue
            stocks = self.client.get_industry_stocks(board_name)
            for s in stocks:
                s["industry"] = industry_key
            industry_stocks.extend(stocks)

        if not industry_stocks:
            return []

        # Filter out holdings
        candidates = [s for s in industry_stocks if s["symbol"] not in exclude]
        if not candidates:
            return []

        # Step 2: 获取全量资金流
        fund_flow_map = self.client.get_all_fund_flow()

        # Step 3: 粗排 — 过滤 + 评分
        scored = []
        for s in candidates:
            pe = s.get("pe")
            if pe is None or pe <= 0 or pe >= 200:
                continue

            ff = fund_flow_map.get(s["symbol"], {})
            main_pct = ff.get("main_pct")
            if main_pct is None or main_pct <= 0:
                continue

            s["fund_flow"] = ff
            scored.append(s)

        if not scored:
            return []

        # Normalize indicators (min-max within candidate pool)
        def _normalize(values: list[float]) -> list[float]:
            mn, mx = min(values), max(values)
            rng = mx - mn
            if rng == 0:
                return [0.5] * len(values)
            return [(v - mn) / rng for v in values]

        main_pcts = [s["fund_flow"]["main_pct"] for s in scored]
        turnovers = [s.get("turnover_rate") or 0 for s in scored]
        changes = [s.get("change_pct") or 0 for s in scored]

        norm_main = _normalize(main_pcts)
        norm_turnover = _normalize(turnovers)
        norm_change = _normalize(changes)

        for i, s in enumerate(scored):
            s["_score"] = (
                norm_main[i] * 0.4
                + norm_turnover[i] * 0.2
                + norm_change[i] * 0.2
            )

        scored.sort(key=lambda x: x["_score"], reverse=True)
        top_candidates = scored[:10]

        # Step 4: 精排 — 并发调研报评级
        def _rate_stock(stock: dict) -> dict | None:
            symbol = stock["symbol"]
            rating = self.client.get_analyst_rating_summary(symbol)
            if not rating:
                return None
            total = rating["total_reports"]
            if total == 0:
                return None
            buy_count = rating.get("buy", 0) + rating.get("outperform", 0)
            buy_pct = buy_count / total * 100
            if buy_pct <= 50:
                return None
            return {**stock, "rating_summary": rating, "buy_pct": round(buy_pct, 1)}

        rated = []
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(_rate_stock, s): s for s in top_candidates}
            for future in as_completed(futures):
                try:
                    result = future.result()
                    if result:
                        rated.append(result)
                except Exception as e:
                    logger.warning(f"Rating fetch error: {e}")

        rated.sort(key=lambda x: x.get("buy_pct", 0), reverse=True)

        # Step 5: Build output
        results = []
        for r in rated[:max_recommendations]:
            label = INDUSTRY_LABELS.get(r["industry"], r["industry"])
            total_reports = r["rating_summary"]["total_reports"]
            data: dict[str, Any] = {
                "symbol": r["symbol"],
                "name": r["name"],
                "industry": r["industry"],
                "rating_summary": r["rating_summary"],
                "buy_pct": r["buy_pct"],
                "price": r.get("price"),
                "change": r.get("change_pct"),
                "currency": "¥",
                "recommendation_reason": (
                    f"{label} · {r['buy_pct']:.0f}%买入评级 · {total_reports}份研报"
                ),
            }
            results.append(data)

        return results

    def fetch_all(self, holdings: list[dict], industries: list[str],
                 max_recommendations: int = 3) -> dict[str, Any]:
        """获取 A 股全部数据。"""
        holdings_symbols = [h["symbol"] for h in holdings]

        ctx = {
            "holdings": holdings,
            "holdings_symbols": holdings_symbols,
            "industries": industries,
            "max_recommendations": max_recommendations,
        }

        results = {}
        for section_name in ["indices", "economic_calendar", "dragon_tiger",
                             "sector_performance", "holdings", "recommendations"]:
            results[section_name] = self.get_section_data(section_name, **ctx)

        return results

    def get_section_data(self, section_name: str, **kwargs) -> list[dict]:
        """Fetch a single section's data independently."""
        dispatch = {
            "indices": lambda: self.get_indices(),
            "economic_calendar": lambda: get_upcoming_events(),
            "dragon_tiger": lambda: self.client.get_dragon_tiger_list(days=3),
            "sector_performance": lambda: (
                self.client.get_sector_performance(
                    [INDUSTRY_SECTOR_NAMES[i] for i in kwargs.get("industries", [])
                     if i in INDUSTRY_SECTOR_NAMES]
                ) if kwargs.get("industries") else []
            ),
            "holdings": lambda: self.get_holdings_data(kwargs.get("holdings", [])),
            "recommendations": lambda: self.get_recommendations(
                kwargs.get("industries", []),
                kwargs.get("holdings_symbols", []),
                max_recommendations=kwargs.get("max_recommendations", 3),
            ),
        }
        fn = dispatch.get(section_name)
        if fn is None:
            raise ValueError(f"Unknown section: {section_name}")
        return fn()

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

        # Rule-based stock annotations
        annotations = self._get_stock_annotations(stock)
        if annotations:
            tags_html = " ".join(
                f'<span style="display:inline-block; font-size:11px; padding:2px 6px; border-radius:3px; margin:2px 2px 2px 0; {a["style"]}">{a["text"]}</span>'
                for a in annotations
            )
            html += f'''
  <div style="margin:4px 0 6px 0;">{tags_html}</div>'''

        # Key metrics: 市值 / PE / 换手率 + 行情明细
        metrics_items = []
        if stock.get("market_cap"):
            metrics_items.append(f'<span class="label">市值:</span> {self._format_cap_cn(stock["market_cap"])}')
        if stock.get("pe") is not None:
            metrics_items.append(f'<span class="label">PE:</span> {stock["pe"]:.1f}')
        if stock.get("turnover_rate") is not None:
            metrics_items.append(f'<span class="label">换手率:</span> {stock["turnover_rate"]:.2f}%')
        # 行情明细: 开高低 + 成交额
        detail_parts = []
        if stock.get("open") is not None:
            detail_parts.append(f"开 {currency}{stock['open']:.2f}")
        if stock.get("high") is not None and stock.get("low") is not None:
            detail_parts.append(f"高 {currency}{stock['high']:.2f} / 低 {currency}{stock['low']:.2f}")
        if stock.get("amount") is not None:
            detail_parts.append(f"成交额 {self._format_amount(stock['amount'])}")
        if detail_parts:
            metrics_items.append('<span class="label">行情:</span> ' + " | ".join(detail_parts))

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
            categories = [
                ("买入", "buy", "#e74c3c", "#fde8e8"),
                ("增持", "outperform", "#e67e22", "#fef5e7"),
                ("中性", "neutral", "#f39c12", "#fef9e7"),
                ("减持", "underperform", "#3498db", "#ebf5fb"),
                ("卖出", "sell", "#27ae60", "#e8f8f0"),
            ]
            rating_bars = ""
            for label, key, bar_color, bg_color in categories:
                count = rating.get(key, 0)
                pct = count / total * 100
                rating_bars += f'''
      <tr>
        <td width="36" style="color:#666; padding:3px 0;">{label}</td>
        <td width="24" style="font-weight:600; color:{bar_color}; padding:3px 4px 3px 0;">{count}</td>
        <td style="padding:3px 0;"><div style="background:{bg_color}; height:6px; border-radius:3px;"><div style="background:{bar_color}; height:6px; border-radius:3px; width:{pct:.1f}%;"></div></div></td>
        <td width="36" style="text-align:right; color:#999; padding:3px 0 3px 4px;">{pct:.0f}%</td>
      </tr>'''

            html += f'''
  <div class="analyst-section">
    <div style="font-weight:600; margin-bottom:6px; color:#2c3e50;">📊 研报评级分布 ({total}份)</div>
    <table width="100%" cellpadding="0" cellspacing="0" style="font-size:12px; margin:6px 0;">
{rating_bars}
    </table>
  </div>'''

            # 盈利预测一致预期
            consensus = rating.get("consensus", [])
            institutions = rating.get("institutions", 0)
            growth_rates = rating.get("eps_growth_rates", [])
            if consensus:
                consensus_rows = ""
                for c in consensus:
                    eps_str = f'EPS ¥{c["eps_avg"]:.2f}' if "eps_avg" in c else ""
                    pe_str = f'PE {c["pe_avg"]:.1f}x' if "pe_avg" in c else ""
                    consensus_rows += f'''
          <tr>
            <td style="color:#666; padding:3px 8px 3px 0; font-weight:600;">{c["year"]}</td>
            <td style="padding:3px 8px 3px 0;">{eps_str}</td>
            <td style="padding:3px 0;">{pe_str}</td>
          </tr>'''

                growth_str = ""
                if growth_rates:
                    parts = []
                    for i, g in enumerate(growth_rates):
                        yr = consensus[i + 1]["year"] if i + 1 < len(consensus) else f"Y{i+2}"
                        color = "#e74c3c" if g > 0 else "#27ae60"
                        parts.append(f'<span style="color:{color};">{yr} {g:+.1f}%</span>')
                    growth_str = f'''
      <div style="font-size:12px; margin-top:4px; color:#555;">
        盈利增速: {" → ".join(parts)}
      </div>'''

                inst_str = f" · {institutions}家机构覆盖" if institutions else ""
                html += f'''
  <div style="background:#f0f4f8; border-radius:6px; padding:10px; margin:8px 0; border-left:3px solid #3498db;">
    <div style="font-weight:600; margin-bottom:6px; color:#2c3e50;">📈 一致预期{inst_str}</div>
    <table width="100%" cellpadding="0" cellspacing="0" style="font-size:12px; margin:4px 0;">
{consensus_rows}
    </table>
    {growth_str}
  </div>'''

        # Main force fund flow (主力资金)
        ff = stock.get("fund_flow")
        if ff:
            main_net = ff.get("main_net")
            main_pct = ff.get("main_pct")
            huge_net = ff.get("huge_net")
            if main_net is not None:
                net_color = "#e74c3c" if main_net > 0 else "#27ae60"
                direction = "净流入" if main_net > 0 else "净流出"
                main_str = f'<strong style="color:{net_color};">{self._format_amount(abs(main_net))} {direction}</strong> ({main_pct:+.2f}%)'
                huge_str = ""
                if huge_net is not None:
                    huge_str = f' | 超大单 {self._format_amount(abs(huge_net))}'
                html += f'''
  <div style="background:#fff8f0; border-radius:6px; padding:8px 10px; margin:8px 0; border-left:3px solid #e67e22; font-size:13px;">
    <strong>💰 主力资金:</strong> {main_str}{huge_str}
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

        # Research reports list (最新研报)
        reports = stock.get("research_reports")
        if reports:
            html += self._render_research_reports(reports)

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
        if fin.get("gross_margin") is not None:
            items.append(f"毛利率: {fin['gross_margin']:.2f}%")
        if fin.get("net_margin") is not None:
            items.append(f"净利率: {fin['net_margin']:.2f}%")
        if fin.get("debt_ratio") is not None:
            items.append(f"负债率: {fin['debt_ratio']:.2f}%")

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

    def _render_research_reports(self, reports: list[dict]) -> str:
        """渲染最新研报列表。"""
        rows = ""
        for r in reports[:5]:
            rating = r.get("rating", "")
            rating_color = "#e74c3c" if rating in ("买入", "强烈推荐", "推荐") else "#e67e22" if rating in ("增持",) else "#f39c12" if rating in ("中性", "持有") else "#7f8c8d"
            rows += f'''
      <tr>
        <td style="padding:4px 5px; border-bottom:1px solid #f0e8d8; color:#2c3e50; font-size:11px; line-height:1.4;">{r.get("title", "")}</td>
        <td style="padding:4px 5px; border-bottom:1px solid #f0e8d8; font-size:11px; color:#555;">{r.get("institution", "")}</td>
        <td style="padding:4px 5px; border-bottom:1px solid #f0e8d8; font-size:11px; color:{rating_color}; font-weight:500;">{rating}</td>
        <td style="padding:4px 5px; border-bottom:1px solid #f0e8d8; font-size:11px; color:#999;">{r.get("date", "")}</td>
      </tr>'''

        return f'''
  <div class="research-section">
    <div style="font-weight:600; margin-bottom:6px; color:#2c3e50;">📝 最新研报</div>
    <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; font-size:12px; table-layout:fixed;">
      <colgroup><col style="width:45%"/><col style="width:22%"/><col style="width:15%"/><col style="width:18%"/></colgroup>
      <tr style="background:rgba(0,0,0,0.03);">
        <th style="text-align:left; padding:4px 5px; font-weight:600; color:#2c3e50; border-bottom:1px solid #ccc; font-size:11px;">标题</th>
        <th style="text-align:left; padding:4px 5px; font-weight:600; color:#2c3e50; border-bottom:1px solid #ccc; font-size:11px;">机构</th>
        <th style="text-align:left; padding:4px 5px; font-weight:600; color:#2c3e50; border-bottom:1px solid #ccc; font-size:11px;">评级</th>
        <th style="text-align:left; padding:4px 5px; font-weight:600; color:#2c3e50; border-bottom:1px solid #ccc; font-size:11px;">日期</th>
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

    def _render_sector_performance(self, sectors: list[dict]) -> str:
        """渲染行业板块表现。"""
        if not sectors:
            return ""
        rows = ""
        for s in sectors:
            change = s.get("change_pct") or 0
            color = "#e74c3c" if change > 0 else "#27ae60" if change < 0 else "#7f8c8d"
            change_str = f"+{change:.2f}%" if change > 0 else f"{change:.2f}%"
            up = int(s.get("up_count") or 0)
            down = int(s.get("down_count") or 0)
            leader = s.get("leader", "")
            leader_change = s.get("leader_change")
            leader_str = f"{leader} {leader_change:+.1f}%" if leader and leader_change is not None else leader
            rows += f'''
      <tr>
        <td style="padding:4px 8px; border-bottom:1px solid #eee; font-weight:500;">{s["name"]}</td>
        <td style="padding:4px 8px; border-bottom:1px solid #eee; color:{color}; font-weight:bold;">{change_str}</td>
        <td style="padding:4px 8px; border-bottom:1px solid #eee; color:#555; font-size:11px;">{up}涨 / {down}跌</td>
        <td style="padding:4px 8px; border-bottom:1px solid #eee; color:#999; font-size:11px;">领涨: {leader_str}</td>
      </tr>'''

        return f'''
      <div class="card">
        <div class="card-header" style="padding:12px 15px; background:#f8f9fa; border-bottom:1px solid #e9ecef; font-weight:600;">🏭 行业板块</div>
        <div class="card-body">
          <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; font-size:12px;">
            <colgroup><col style="width:20%"/><col style="width:15%"/><col style="width:25%"/><col style="width:40%"/></colgroup>
            <tr style="background:rgba(0,0,0,0.03);">
              <th style="text-align:left; padding:4px 8px; font-weight:600; color:#2c3e50; border-bottom:1px solid #ccc;">行业</th>
              <th style="text-align:left; padding:4px 8px; font-weight:600; color:#2c3e50; border-bottom:1px solid #ccc;">涨跌幅</th>
              <th style="text-align:left; padding:4px 8px; font-weight:600; color:#2c3e50; border-bottom:1px solid #ccc;">涨跌比</th>
              <th style="text-align:left; padding:4px 8px; font-weight:600; color:#2c3e50; border-bottom:1px solid #ccc;">领涨股</th>
            </tr>
            {rows}
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

    @staticmethod
    def _guidance_html(text: str | None) -> str:
        """Render a guidance tip block. Returns empty string if no text."""
        if not text:
            return ""
        return f'''
      <div style="font-size:12px; color:#6c757d; background:#f8f9fa; padding:8px 12px; border-radius:4px; margin:4px 0 8px 0; border-left:3px solid #adb5bd; line-height:1.5;">
        💡 {text}
      </div>'''

    @staticmethod
    def _get_stock_annotations(stock: dict) -> list[dict]:
        """Rule-based annotations for CN stock cards."""
        annotations = []
        techs = stock.get("technicals", {})

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

        # Main force fund flow
        ff = stock.get("fund_flow")
        if ff:
            main_net = ff.get("main_net")
            if main_net is not None and abs(main_net) > 50_000_000:  # > 5000万
                if main_net > 0:
                    annotations.append({"text": "💰 主力资金大幅流入", "style": "background:#e8f5e9; color:#2e7d32;"})
                else:
                    annotations.append({"text": "💰 主力资金大幅流出", "style": "background:#fde8e8; color:#c62828;"})

        # Insider trades
        insiders = stock.get("insider_trades")
        if insiders:
            buy_count = sum(1 for t in insiders if "增" in t.get("action", ""))
            if buy_count >= 2:
                annotations.append({"text": "👔 多位高管增持", "style": "background:#e8f5e9; color:#2e7d32;"})

        # Financial growth
        fin = stock.get("financial")
        if fin:
            rev_growth = fin.get("revenue_growth")
            profit_growth = fin.get("profit_growth")
            if rev_growth and profit_growth and rev_growth > 20 and profit_growth > 20:
                annotations.append({"text": f"📈 营收+利润双增长(营收{rev_growth:+.0f}%)", "style": "background:#e3f2fd; color:#1565c0;"})

        return annotations[:4]

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
