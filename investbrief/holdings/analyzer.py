"""持仓标的分析：按 market/type 分发到不同数据源，整合多维度（价格/评级/基本面/资金流）。

P1 范围：US 股票 + CN 股票 + CN ETF（复用 etf 包）+ CN 场外基金（stub，P2 实现）。
评级用单期快照；评级多期变化与技术面/新闻维度留 P2/P3。

韧性：单个数据源失败 try/except 跳过，对应维度留空，renderer 优雅降级，不阻塞整体。
跨标的去重缓存：同一 (symbol, market, type) 在一次运行内只分析一次（多收件人共享）。
"""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from typing import Any, Callable

from investbrief.datasources.akshare import AKShareClient
from investbrief.datasources.finnhub import FinnhubClient
from investbrief.datasources.yfinance import YFinanceClient
from investbrief.holdings.etf.analyzer import ETFAnalyzer, ETFAnalysisResult
from investbrief.holdings.etf.indicators import compute_indicators

logger = logging.getLogger(__name__)

_pool = ThreadPoolExecutor(max_workers=6)


@dataclass
class HoldingResult:
    """单个持仓标的标准化分析结果。缺失维度留空 dict/list，renderer 优雅降级。"""
    symbol: str
    market: str                  # us / cn
    type: str                    # stock / etf / fund
    name: str = ""
    price: dict = field(default_factory=dict)
    rating: dict = field(default_factory=dict)
    fundamentals: dict = field(default_factory=dict)
    flow: dict = field(default_factory=dict)
    signals: list = field(default_factory=list)
    technicals: dict = field(default_factory=dict)
    news: list = field(default_factory=list)
    events: dict = field(default_factory=dict)
    insider: dict = field(default_factory=dict)
    cn_activity: dict = field(default_factory=dict)
    forecast: dict = field(default_factory=dict)
    fund_meta: dict = field(default_factory=dict)
    ai_conclusion: str = ""
    error: str = ""              # 非空 → 该标的整体分析失败

    def to_dict(self) -> dict:
        return asdict(self)


class HoldingsAnalyzer:
    """分析一组持仓，跨标的去重缓存。"""

    def __init__(self):
        self._ak = AKShareClient()
        self._yf = YFinanceClient()
        self._fh = FinnhubClient()
        self._etf = ETFAnalyzer()
        self._cache: dict[tuple, HoldingResult] = {}

    def analyze(self, holdings: list[dict]) -> list[HoldingResult]:
        """分析一组 holdings（[{symbol,market,type}]），同标的只查一次。"""
        results: list[HoldingResult] = []
        for h in holdings:
            key = (h["symbol"], h["market"], h["type"])
            if key not in self._cache:
                self._cache[key] = self.analyze_one(h["symbol"], h["market"], h["type"])
            results.append(self._cache[key])
        return results

    def analyze_one(self, symbol: str, market: str, type_: str) -> HoldingResult:
        dispatch = {
            ("us", "stock"): self._analyze_us_stock,
            ("cn", "stock"): self._analyze_cn_stock,
            ("cn", "etf"): self._analyze_cn_etf,
            ("cn", "fund"): self._analyze_cn_fund,
        }
        handler = dispatch.get((market, type_))
        if handler is None:
            return HoldingResult(symbol=symbol, market=market, type=type_,
                                 error=f"unsupported market/type: {market}/{type_}")
        try:
            return handler(symbol)
        except Exception as e:
            logger.warning(f"analyze_one failed {market}/{type_} {symbol}: {e}")
            return HoldingResult(symbol=symbol, market=market, type=type_, error=str(e))

    # ==================== 分发实现 ====================

    def _collect_events(self, symbol: str, market: str) -> dict:
        """业绩日历。US=yfinance；CN=季报披露窗口规则推算。失败返回 {}。

        Field structure: {"next_earnings": "YYYY-MM-DD", "days_to_next": int, "is_in_window": bool}
        """
        from datetime import date
        try:
            if market == "us":
                # yfinance get_earnings_dates → [{"date": "YYYY-MM-DD"}, ...]（无 type 字段）
                dates = self._yf.get_earnings_dates(symbol) or []
                today_iso = date.today().isoformat()
                upcoming = [d for d in dates
                            if d.get("date", "") >= today_iso]
                if not upcoming:
                    return {}
                next_d = sorted(d["date"] for d in upcoming)[0]
            else:
                # CN 季报披露窗口：Q1 4-30、半年报 8-31、Q3 10-31、年报 次年 4-30
                today = date.today()
                windows = []
                year = today.year
                for _ in range(2):
                    windows += [
                        date(year, 4, 30), date(year, 8, 31),
                        date(year, 10, 31), date(year + 1, 4, 30),
                    ]
                    year += 1
                upcoming = sorted(w for w in windows if w >= today)
                if not upcoming:
                    return {}
                next_d = upcoming[0].isoformat()
            days = (date.fromisoformat(next_d) - date.today()).days
            return {"next_earnings": next_d, "days_to_next": days, "is_in_window": days <= 7}
        except Exception as e:
            logger.warning(f"events collect failed for {symbol}: {e}")
            return {}

    def _collect_insider(self, symbol: str, market: str) -> dict:
        """大股东/高管增减持，最近窗口聚合。失败返回 {}。

        Field structure: {"net_amount": float, "direction": "buy"/"sell"/"flat",
                          "latest_date": str, "count": int}

        数据源限制：
        - CN akshare major: action 文本（"增持4.16万"/"减持..."），无数值 → 仅参与方向判定。
        - CN akshare insider: 已过滤为「增」（buy），shares 可量化。
        - US yfinance: 已过滤为 Buy，value 字段为交易金额。
        net_amount 仅累加可量化的数值；方向由 sell/buy 计数主导（无可用数值时按方向多数）。
        """
        try:
            if market == "cn":
                major = self._ak.get_major_shareholder_trades(symbol, days=90) or []
                insider = self._ak.get_insider_trades(symbol, days=90) or []
                records = []
                # major: action 文本含「减」=sell，含「增」=buy；数值缺失
                for t in major:
                    action = str(t.get("action", ""))
                    if "减" in action:
                        records.append(("sell", None, t.get("date", "")))
                    elif "增" in action:
                        records.append(("buy", None, t.get("date", "")))
                # insider: 已是「增」（buy）；shares 可量化
                for t in insider:
                    shares = t.get("shares")
                    amt = float(shares) if shares is not None else None
                    records.append(("buy", amt, t.get("date", "")))
            else:
                txns = self._yf.get_insider_transactions(symbol, limit=10) or []
                records = [
                    ("buy", t.get("value"), t.get("date", ""))
                    for t in txns
                ]
            if not records:
                return {}
            net = sum(amt for _, amt, _ in records if amt is not None)
            buy_n = sum(1 for d, _, _ in records if d == "buy")
            sell_n = sum(1 for d, _, _ in records if d == "sell")
            if net != 0:
                direction = "buy" if net > 0 else "sell"
            elif buy_n > sell_n:
                direction = "buy"
            elif sell_n > buy_n:
                direction = "sell"
            else:
                direction = "flat"
            dates = [d for _, _, d in records if d]
            return {
                "net_amount": net,
                "direction": direction,
                "latest_date": max(dates) if dates else "",
                "count": len(records),
            }
        except Exception as e:
            logger.warning(f"insider collect failed for {symbol}: {e}")
            return {}

    def _collect_cn_activity(self, symbol: str, market: str = "cn") -> dict:
        """CN 独有：龙虎榜上榜次数（最近 30 天）+ 机构调研次数（90 天）。US 返回 {}。

        Field structure: {"dragon_tiger_count": int, "institution_research_count": int}

        - 龙虎榜：get_dragon_tiger_list 返回全市场最近 days 日上榜股票（字段 symbol），
          需按 symbol 后过滤统计次数。
        - 机构调研：get_institutional_research(symbol, days) 已按 symbol 过滤，长度即次数。
        """
        if market != "cn":
            return {}
        try:
            dragon = self._ak.get_dragon_tiger_list(days=30) or []
            dt_count = sum(1 for d in dragon if str(d.get("symbol", "")) == str(symbol))
            research = self._ak.get_institutional_research(symbol, days=90) or []
            return {
                "dragon_tiger_count": dt_count,
                "institution_research_count": len(research),
            }
        except Exception as e:
            logger.warning(f"cn_activity collect failed for {symbol}: {e}")
            return {}

    def _collect_forecast(self, symbol: str, market: str) -> dict:
        """盈利预估（EPS next-quarter + yoy growth）。CN 返回 {}（无免费源）。

        Field structure: {"eps_next": float, "yoy_pct": float, "revenue_next": float|None}

        yfinance.get_earnings_estimate 真实返回：{period_key: {avg, low, high, growth, num_analysts}}
        period_key 取值 0q/+1q/0y/+1y。我们取 **+1q（下一季度）** 的 avg 作为 eps_next，
        growth 即该期 EPS 同比；revenue 无免费源 → None。源缺 +1q → 对应字段 None（降级）。
        """
        if market != "us":
            return {}
        try:
            est = self._yf.get_earnings_estimate(symbol) or {}
            next_q = est.get("+1q") or {}
            return {
                "eps_next": next_q.get("avg"),
                "yoy_pct": next_q.get("growth"),
                "revenue_next": None,  # 无免费 revenue estimate 源
            }
        except Exception as e:
            logger.warning(f"forecast collect failed for {symbol}: {e}")
            return {}

    def _analyze_us_stock(self, symbol: str) -> HoldingResult:
        data = self._parallel({
            "quote": lambda: self._yf.get_quote(symbol),
            "info": lambda: self._yf.get_info(symbol),
            # 评级：yfinance 为主（免费、稳定），finnhub 为辅（提供 trend，但 free tier 常 403）
            "recommendation_yf": lambda: self._yf.get_recommendations(symbol),
            "recommendation_fh": lambda: self._fh.get_recommendation(symbol),
            "price_target_fh": lambda: self._fh.get_price_target(symbol),
            "price_target_yf": lambda: self._yf.get_price_targets(symbol),
            "upgrades": lambda: self._yf.get_upgrades_downgrades(symbol),
            "history": lambda: self._yf.get_history(symbol, period="6mo"),
            "news": lambda: self._fh.get_company_news(symbol, days=7),
        })
        quote = data.get("quote") or {}
        info = data.get("info") or {}
        current = quote.get("price")
        recommendation = self._merge_us_recommendation(
            data.get("recommendation_fh"), data.get("recommendation_yf"),
        )
        # finnhub price-target may 403 on free tier → fallback to yfinance
        price_target = data.get("price_target_fh") or {}
        if not price_target.get("target_mean"):
            yf_pt = data.get("price_target_yf") or {}
            if yf_pt.get("mean"):
                price_target = {
                    "target_mean": yf_pt.get("mean"),
                    "target_high": yf_pt.get("high"),
                    "target_low": yf_pt.get("low"),
                    "number_of_analysts": None,
                }
        return HoldingResult(
            symbol=symbol, market="us", type="stock",
            name=str(info.get("longName") or info.get("shortName") or symbol),
            price={
                "current": current,
                "change_pct": quote.get("change_percent"),
                "previous_close": quote.get("previous_close"),
                "day_high": quote.get("day_high"),
                "day_low": quote.get("day_low"),
                "volume": quote.get("volume"),
                "market_cap": quote.get("market_cap") or info.get("market_cap"),
            },
            rating=self._build_us_rating(
                recommendation, price_target,
                data.get("upgrades"), current,
            ),
            fundamentals={
                "pe": info.get("trailingPE") or info.get("forwardPE"),
                "roe": _ratio(info.get("returnOnEquity")),
                "revenue_growth": _ratio(info.get("revenueGrowth")),
                "profit_growth": _ratio(info.get("earningsGrowth")),
                "gross_margin": _ratio(info.get("grossMargins")),
                "net_margin": _ratio(info.get("profitMargins")),
            },
            flow={},  # US 个股资金流无免费数据源
            technicals=_extract_technicals(data.get("history"), uppercase_cols=True),
            news=_extract_news(data.get("news")),
            events=self._collect_events(symbol, "us"),
            insider=self._collect_insider(symbol, "us"),
            forecast=self._collect_forecast(symbol, "us"),
        )

    def _analyze_cn_stock(self, symbol: str) -> HoldingResult:
        data = self._parallel({
            "quote": lambda: self._ak.get_stock_quote(symbol),
            "rating": lambda: self._ak.get_analyst_rating_summary(symbol),
            "reports": lambda: self._ak.get_research_reports(symbol, limit=5),
            "fundamentals": lambda: self._ak.get_financial_indicators(symbol),
            "flow": lambda: self._ak.get_stock_fund_flow(symbol),
            "history": lambda: self._ak.get_stock_history(symbol, days=180),
            "news": lambda: self._ak.get_stock_news(symbol, limit=5),
        })
        quote = data.get("quote") or {}
        fin = data.get("fundamentals") or {}
        flow = data.get("flow") or {}
        return HoldingResult(
            symbol=symbol, market="cn", type="stock",
            name=quote.get("name", symbol),
            price={
                "current": quote.get("price"),
                "change_pct": quote.get("change_pct"),
                "open": quote.get("open"),
                "high": quote.get("high"),
                "low": quote.get("low"),
                "volume": quote.get("volume"),
                "amount": quote.get("amount"),
                "market_cap": quote.get("market_cap"),
            },
            rating=self._build_cn_rating(data.get("rating"), data.get("reports")),
            fundamentals={
                "pe": quote.get("pe"),
                "eps": fin.get("eps"),
                "roe": fin.get("roe"),
                "revenue_growth": fin.get("revenue_growth"),
                "profit_growth": fin.get("profit_growth"),
                "gross_margin": fin.get("gross_margin"),
                "net_margin": fin.get("net_margin"),
                "debt_ratio": fin.get("debt_ratio"),
                "report_date": fin.get("report_date"),
            },
            flow={
                "main_net": flow.get("main_net"),
                "main_pct": flow.get("main_pct"),
                "huge_net": flow.get("huge_net"),
                "big_net": flow.get("big_net"),
                "date": flow.get("date"),
            },
            technicals=_extract_technicals(data.get("history")),
            news=_extract_news(data.get("news")),
            events=self._collect_events(symbol, "cn"),
            insider=self._collect_insider(symbol, "cn"),
            cn_activity=self._collect_cn_activity(symbol, "cn"),
        )

    def _analyze_cn_etf(self, symbol: str) -> HoldingResult:
        result: ETFAnalysisResult = self._etf.analyze(symbol)
        return HoldingResult(
            symbol=result.symbol, market="cn", type="etf",
            name=result.name,
            price={
                "current": result.price,
                "change_pct": result.change_pct,
                "iopv": result.iopv,
                "premium_rate": result.premium_rate,
            },
            flow={"main_net_flow": result.main_net_flow},
            signals=list(result.rule_results),
            ai_conclusion=result.ai_conclusion or "",
        )

    def _analyze_cn_fund(self, symbol: str) -> HoldingResult:
        """场外基金：净值代替现价，近期收益代替基本面；无资金流/评级（接口不提供）。

        fund_meta（scale/manager/rating）：get_open_fund_nav 当前不提供这三个字段，
        统一返回 {scale: None, manager: None, rating: None}，键固定存在以供 renderer
        优雅降级。后续若源扩展（如 fund_individual_basic_info_xq），可在此直接映射。
        """
        data = self._parallel({"nav": lambda: self._ak.get_open_fund_nav(symbol)})
        nav = data.get("nav") or {}
        if not nav:
            return HoldingResult(symbol=symbol, market="cn", type="fund",
                                 name="（场外基金）", error="无法获取净值（代码错误或接口失败）")
        return HoldingResult(
            symbol=symbol, market="cn", type="fund",
            name=nav.get("name", symbol),
            price={
                "current": nav.get("nav"),            # 场外基金用单位净值代替现价
                "change_pct": nav.get("daily_change"),
                "acc_nav": nav.get("acc_nav"),
                "nav_date": nav.get("date"),
            },
            fundamentals={
                "return_1w": nav.get("return_1w"),
                "return_1m": nav.get("return_1m"),
                "return_3m": nav.get("return_3m"),
            },
            fund_meta={
                "scale": nav.get("scale"),
                "manager": nav.get("manager"),
                "rating": nav.get("rating"),
            },
        )

    # ==================== 评级结构标准化 ====================

    @staticmethod
    def _merge_us_recommendation(fh_rec, yf_rec) -> dict | None:
        """US 评级分布合并：finnhub 优先（带 trend），yfinance 兜底（仅当期分布）。

        - finnhub 成功 → 直接返回（含 latest/previous/change/periods，信息更全）。
        - finnhub 失败/空（如 free tier 403）→ yfinance flat dict 归一化为
          {latest: {strong_buy/buy/hold/sell/strong_sell}, change: {}, periods: []}。
          yfinance 无 previous 期数据，trend 留空 dict（renderer 已优雅降级）。
        - 两者都失败 → None（_build_us_rating 会产出空 distribution）。

        设计目标：finnhub 403 时评级维度仍可从 yfinance 构造，不依赖 finnhub。
        """
        if fh_rec and fh_rec.get("latest"):
            return fh_rec
        yf = yf_rec or {}
        if not any(yf.get(k) for k in ("strong_buy", "buy", "hold", "sell", "strong_sell")):
            return None
        return {
            "latest": {
                "strong_buy": yf.get("strong_buy"),
                "buy": yf.get("buy"),
                "hold": yf.get("hold"),
                "sell": yf.get("sell"),
                "strong_sell": yf.get("strong_sell"),
                "period": None,
            },
            "previous": None,
            "change": {},
            "periods": [],
        }

    @staticmethod
    def _build_us_rating(recommendation, price_target, upgrades, current) -> dict:
        rec = recommendation or {}
        latest = rec.get("latest") or {}
        distribution = {k: v for k, v in {
            "strong_buy": latest.get("strong_buy"),
            "buy": latest.get("buy"),
            "hold": latest.get("hold"),
            "sell": latest.get("sell"),
            "strong_sell": latest.get("strong_sell"),
        }.items() if v}
        total = sum(distribution.values()) or None
        pt = price_target or {}
        mean = pt.get("target_mean")
        upside = round((mean - current) / current * 100, 1) if (mean and current) else None
        actions = [{
            "firm": u.get("firm"), "from_grade": u.get("from_grade"),
            "to_grade": u.get("to_grade"), "action": u.get("action"),
            "price_target": u.get("price_target"), "date": u.get("date"),
        } for u in (upgrades or [])]
        return {
            "distribution": distribution,
            "total": total,
            "trend": rec.get("change") or {},        # 本期 vs 上期（pct-point）
            "period": latest.get("period"),
            "price_target": {
                "mean": mean, "high": pt.get("target_high"),
                "low": pt.get("target_low"), "upside_pct": upside,
                "num_analysts": pt.get("number_of_analysts"),
            } if pt else {},
            "actions": actions,
            "source": "finnhub/yfinance",
        }

    @staticmethod
    def _build_cn_rating(summary, reports) -> dict:
        s = summary or {}
        distribution = {k: v for k, v in {
            "buy": s.get("buy"),
            "outperform": s.get("outperform"),
            "neutral": s.get("neutral"),
            "underperform": s.get("underperform"),
            "sell": s.get("sell"),
        }.items() if v}
        actions = [{
            "institution": r.get("institution"),
            "rating": r.get("rating"),
            "date": r.get("date"),
        } for r in (reports or [])]
        return {
            "distribution": distribution,
            "total": s.get("total_reports"),          # 近 days 天研报数
            "total_all": s.get("total_reports_all"),
            "institutions": s.get("institutions"),
            "trend": s.get("change") or {},            # 近期 vs 上一周期（pct-point）
            "days": s.get("days"),
            "consensus": s.get("consensus", []),
            "eps_growth": s.get("eps_growth_rates", []),
            "price_target": {},  # akshare 研报接口无目标价字段
            "actions": actions,
            "source": "akshare",
        }

    # ==================== 并行拉取 ====================

    @staticmethod
    def _parallel(tasks: dict[str, Callable]) -> dict:
        results: dict[str, Any] = {}
        futures = {_pool.submit(fn): k for k, fn in tasks.items()}
        for f in as_completed(futures):
            k = futures[f]
            try:
                results[k] = f.result()
            except Exception as e:
                logger.warning(f"holdings parallel fetch failed [{k}]: {e}")
                results[k] = None
        return results


def _extract_technicals(hist, uppercase_cols: bool = False) -> dict:
    """从历史 DataFrame 提取关键技术指标（均线/RSI/MACD/区间位置/近期收益）。"""
    if hist is None or (hasattr(hist, "empty") and hist.empty):
        return {}
    if uppercase_cols:
        hist = hist.rename(columns={"Close": "close", "Volume": "volume"})
    try:
        ind = compute_indicators(hist)
    except Exception as e:
        logger.warning(f"technicals calc failed: {e}")
        return {}
    if not ind:
        return {}
    return {
        "ma_alignment": ind.get("ma_alignment"),
        "rsi": ind.get("rsi"),
        "macd_cross": ind.get("macd_cross"),
        "return_20d": ind.get("return_20d"),
        "return_60d": ind.get("return_60d"),
        "position_60d": ind.get("position_60d"),
    }


def _extract_news(items) -> list:
    """标准化新闻列表为 [{title, date, source}]，最多 3 条。

    date 兼容 finnhub 的 datetime（Unix 时间戳）和 akshare 的日期字符串。
    """
    if not items:
        return []
    from datetime import datetime as _dt
    out = []
    for n in items[:3]:
        raw = n.get("date")
        if raw is None:
            raw = n.get("datetime")
        date_str = ""
        if raw:
            if isinstance(raw, (int, float)):
                try:
                    date_str = _dt.fromtimestamp(int(raw)).strftime("%Y-%m-%d")
                except (ValueError, OSError):
                    date_str = str(raw)[:10]
            else:
                date_str = str(raw)[:10]
        out.append({
            "title": str(n.get("title") or n.get("headline", "")),
            "date": date_str,
            "source": str(n.get("source", "")),
        })
    return out


def _ratio(v) -> float | None:
    """yfinance 比率字段（小数）转百分比：0.166 → 16.6, 1.45 → 145.0（ROE 可 >100%）。"""
    if v is None:
        return None
    try:
        return round(float(v) * 100, 2)
    except (TypeError, ValueError):
        return None
