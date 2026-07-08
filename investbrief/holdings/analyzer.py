"""持仓标的分析：按 market/type 分发到不同数据源，整合多维度（价格/评级/基本面/资金流）。

P1 范围：US 股票 + CN 股票 + CN ETF（复用 etf 包）+ CN 场外基金（stub，P2 实现）。
评级用单期快照；评级多期变化与技术面/新闻维度留 P2/P3。

韧性：单个数据源失败 try/except 跳过，对应维度留空，renderer 优雅降级，不阻塞整体。
跨标的去重缓存：同一 (symbol, market, type) 在一次运行内只分析一次（多收件人共享）。
"""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from typing import Any
from collections.abc import Callable

from investbrief.datasources.akshare import AKShareClient
from investbrief.datasources.finnhub import FinnhubClient
from investbrief.datasources.yfinance import YFinanceClient
from investbrief.holdings.etf.analyzer import ETFAnalyzer, ETFAnalysisResult
from investbrief.holdings.etf.indicators import compute_indicators
from investbrief.picks.cache import FactorCache

logger = logging.getLogger(__name__)

_pool = ThreadPoolExecutor(max_workers=2)  # CN stock 专题接口多，高并发加速触发 eastmoney 限流

# 跨日 TTL 缓存(复用 picks.cache.FactorCache): rating/fundamentals/cn_activity
# 是季频数据(分析师评级 / 财报 / 机构调研), TTL=7 天安全; quote/history/news 高频不缓存。
# 缓存文件 data/holdings_cache.db(与 picks_cache.db 分库, key 不碰撞), 可随时清空。
# miss 即重新拉取, 引擎正确性不依赖它。线程安全由 FactorCache 内部 Lock 保证。
_fcache: FactorCache | None = None
_SEASONAL_TTL = 7.0   # 季频: 分析师评级 / 基本面 / 调研


def init_cache(path: str):
    """注入 FactorCache 单例(pipelines/holdings.py 启动时调用;测试可显式 init 或留空禁用)。"""
    global _fcache
    _fcache = FactorCache(path)


def _factor_cache() -> FactorCache | None:
    return _fcache


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
        # run 级缓存：龙虎榜是全市场数据，多只 CN stock 共享一次拉取（省 ~2min/只）
        self._dragon_tiger_cache: dict[int, list] = {}

    def analyze(self, holdings: list[dict]) -> list[HoldingResult]:
        """分析一组 holdings（[{symbol,market,type}]），同标的只查一次。"""
        results: list[HoldingResult] = []
        for h in holdings:
            key = (h["symbol"], h["market"], h["type"])
            if key not in self._cache:
                self._cache[key] = self.analyze_one(h["symbol"], h["market"], h["type"])
            results.append(self._cache[key])
        return results

    def analyze_one(self, symbol: str, market: str, type_: str, *, with_ai: bool = True) -> HoldingResult:
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
            return handler(symbol, with_ai=with_ai)
        except Exception as e:
            logger.warning(f"analyze_one failed {market}/{type_} {symbol}: {e}")
            return HoldingResult(symbol=symbol, market=market, type=type_, error=str(e))

    def _with_ai(self, result: HoldingResult) -> HoldingResult:
        """填充单标的 ai_conclusion。lazy import brief 避免循环依赖。"""
        from investbrief.holdings.brief import generate_stock_conclusion
        result.ai_conclusion = generate_stock_conclusion(result)
        return result

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

    def _get_dragon_tiger_cached(self, days: int = 30) -> list:
        """run 级缓存龙虎榜（全市场数据，多只 CN stock 共享一次拉取）。"""
        if days not in self._dragon_tiger_cache:
            try:
                self._dragon_tiger_cache[days] = self._ak.get_dragon_tiger_list(days=days) or []
            except Exception as e:
                logger.warning(f"dragon_tiger_list fetch failed: {e}")
                self._dragon_tiger_cache[days] = []
        return self._dragon_tiger_cache[days]

    def _collect_cn_activity(self, symbol: str, market: str = "cn") -> dict:
        """CN 独有：龙虎榜上榜次数（最近 30 天）+ 机构调研次数（90 天）。US 返回 {}。

        Field structure: {"dragon_tiger_count": int, "institution_research_count": int}

        - 龙虎榜：get_dragon_tiger_list 返回全市场最近 days 日上榜股票（字段 symbol），
          需按 symbol 后过滤统计次数。
        - 机构调研：get_institutional_research(symbol, days) 已按 symbol 过滤，长度即次数。

        季频缓存 TTL=7d(机构调研 90 天窗口,龙虎榜 30 天窗口;7 天陈旧对持仓邮件可接受,
        且省去全市场 dragon_tiger_list 扫描 + 每股 research 调用)。
        """
        if market != "cn":
            return {}
        key = f"cn_act:{market}:{symbol}"
        return self._cached(key, _SEASONAL_TTL, lambda: self._fetch_cn_activity(symbol)) or {}

    def _fetch_cn_activity(self, symbol: str):
        try:
            dragon = self._get_dragon_tiger_cached(30)
            dt_count = sum(1 for d in dragon if str(d.get("symbol", "")) == str(symbol))
            research = self._ak.get_institutional_research(symbol, days=90) or []
            return {
                "dragon_tiger_count": dt_count,
                "institution_research_count": len(research),
            }
        except Exception as e:
            logger.warning(f"cn_activity fetch failed for {symbol}: {e}")
            return None

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

    # ==================== 季频维度跨日缓存(rating / fundamentals / cn_activity) ====================

    def _cached(self, key: str, ttl_days: float, fn: Callable):
        """TTL 缓存包装:命中复用,未命中调 fn 并写缓存。

        fn 抛异常或返回 None → 不缓存(返回 None/原值,调用方各自降级)。
        _factor_cache() 为 None(未 init_cache,如单测) → 透传 fn 直调,无缓存。
        """
        c = _factor_cache()
        if c is not None and c.fresh(key, ttl_days):
            v = c.get(key)
            if v is not None:
                return v
        try:
            v = fn()
        except Exception as e:
            logger.warning(f"cached fetch [{key}] failed: {e}")
            return None
        if c is not None and v is not None:
            c.set(key, v, ttl_days=ttl_days)
        return v

    def _collect_rating(self, symbol: str, market: str, *, current=None) -> dict:
        """分析师评级(季频,TTL=7d 缓存原始 API 响应;最终结构 fresh build)。

        US 的 price_target.upside_pct 依赖 live current → 取缓存的 raw bundle 后,
        每次 _build_us_rating 用当天 current 重算(不缓存 upside)。
        CN 无 current 依赖。raw fetch 任一源失败 → _build_*_rating 内部优雅降级。
        """
        key = f"rating:{market}:{symbol}"
        raw = self._cached(key, _SEASONAL_TTL, lambda: self._fetch_rating_raw(symbol, market))
        raw = raw or {}
        if market == "us":
            return self._build_us_rating(
                raw.get("recommendation"), raw.get("price_target"),
                raw.get("upgrades"), current,
            )
        return self._build_cn_rating(raw.get("summary"), raw.get("reports"))

    def _fetch_rating_raw(self, symbol: str, market: str) -> dict:
        """拉评级原始 API 响应并合并(US: yf+fh;CN: akshare)。返回可 JSON 序列化的 bundle。"""
        if market == "us":
            d = self._parallel({
                "recommendation_yf": lambda: self._yf.get_recommendations(symbol),
                "recommendation_fh": lambda: self._fh.get_recommendation(symbol),
                "price_target_fh": lambda: self._fh.get_price_target(symbol),
                "price_target_yf": lambda: self._yf.get_price_targets(symbol),
                "upgrades": lambda: self._yf.get_upgrades_downgrades(symbol),
            })
            recommendation = self._merge_us_recommendation(
                d.get("recommendation_fh"), d.get("recommendation_yf"))
            price_target = d.get("price_target_fh") or {}
            if not price_target.get("target_mean"):
                yf_pt = d.get("price_target_yf") or {}
                if yf_pt.get("mean"):
                    price_target = {
                        "target_mean": yf_pt.get("mean"),
                        "target_high": yf_pt.get("high"),
                        "target_low": yf_pt.get("low"),
                        "number_of_analysts": None,
                    }
            return {"recommendation": recommendation,
                    "price_target": price_target, "upgrades": d.get("upgrades")}
        # CN
        d = self._parallel({
            "summary": lambda: self._ak.get_analyst_rating_summary(symbol),
            "reports": lambda: self._ak.get_research_reports(symbol, limit=5),
        })
        return {"summary": d.get("summary"), "reports": d.get("reports")}

    def _collect_fundamentals(self, symbol: str, market: str):
        """基本面季频源(US: yfinance info / CN: akshare 财务指标),TTL=7d 缓存。

        返回原始 dict(US: info / CN: get_financial_indicators 输出),由调用方
        构造最终 fundamentals dict(CN 的 pe 来自 live quote,不在此缓存)。
        """
        key = f"fund:{market}:{symbol}"
        return self._cached(key, _SEASONAL_TTL, lambda: self._fetch_fund_raw(symbol, market))

    def _fetch_fund_raw(self, symbol: str, market: str):
        if market == "us":
            return self._yf.get_info(symbol)
        return self._ak.get_financial_indicators(symbol)

    def _analyze_us_stock(self, symbol: str, *, with_ai: bool = True) -> HoldingResult:
        # quote 作为 yfinance 健康探针：先单独调用。失败 → 该股其他 yfinance
        # endpoint (history/events/insider/forecast/fundamentals) 一律跳过，因为
        # quote 不通说明 yfinance 整体不可达，其余调用也会各自等到 8s timeout。
        # 这样每股 yfinance 调用从 5 降到失败时 1（8s timeout），避免 150s 阻塞。
        try:
            quote = self._yf.get_quote(symbol)
        except Exception as e:  # noqa: BLE001 — get_quote may raise on edge/mock; treat as unreachable
            logger.warning(f"yfinance quote error for {symbol}: {e}")
            quote = None
        if not quote:
            logger.warning(
                f"yfinance quote failed for {symbol}; skipping other yfinance endpoints"
            )
            # 降级：拉非 yfinance 维度（finnhub rating + news），其余维度留空由 renderer 降级
            try:
                news_items = self._fh.get_company_news(symbol, days=7)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"finnhub news fallback failed for {symbol}: {e}")
                news_items = []
            result = HoldingResult(
                symbol=symbol, market="us", type="stock", name=symbol,
                rating=self._collect_rating(symbol, "us"),  # finnhub 评级(非 yfinance)
                news=_extract_news(news_items),
            )
            return self._with_ai(result) if with_ai else result

        # quote ok → 季频 fundamentals (缓存) + 其余日频维度并行
        current = quote.get("price")
        info = self._collect_fundamentals(symbol, "us") or {}
        data = self._parallel({
            "history": lambda: self._yf.get_history(symbol, period="6mo"),
            "news": lambda: self._fh.get_company_news(symbol, days=7),
            "events": lambda: self._collect_events(symbol, "us"),
            "insider": lambda: self._collect_insider(symbol, "us"),
            "forecast": lambda: self._collect_forecast(symbol, "us"),
        })
        result = HoldingResult(
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
            rating=self._collect_rating(symbol, "us", current=current),
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
            events=data.get("events") or {},
            insider=data.get("insider") or {},
            forecast=data.get("forecast") or {},
        )
        return self._with_ai(result) if with_ai else result

    def _analyze_cn_stock(self, symbol: str, *, with_ai: bool = True) -> HoldingResult:
        # 季频维度(rating + fundamentals)走跨日缓存
        fin = self._collect_fundamentals(symbol, "cn") or {}
        # 日频维度(quote/flow/history/news/events/insider/cn_activity)并行,不缓存
        # (cn_activity 内部自带 7d 季频缓存)
        data = self._parallel({
            "quote": lambda: self._ak.get_stock_quote(symbol),
            "flow": lambda: self._ak.get_stock_fund_flow(symbol),
            "history": lambda: self._ak.get_stock_history(symbol, days=180),
            "news": lambda: self._ak.get_stock_news(symbol, limit=5),
            "events": lambda: self._collect_events(symbol, "cn"),
            "insider": lambda: self._collect_insider(symbol, "cn"),
            "cn_activity": lambda: self._collect_cn_activity(symbol, "cn"),
        })
        quote = data.get("quote") or {}
        flow = data.get("flow") or {}
        result = HoldingResult(
            symbol=symbol, market="cn", type="stock",
            name=quote.get("name") or symbol,
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
            rating=self._collect_rating(symbol, "cn"),
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
            events=data.get("events") or {},
            insider=data.get("insider") or {},
            cn_activity=data.get("cn_activity") or {},
        )
        return self._with_ai(result) if with_ai else result

    def _analyze_cn_etf(self, symbol: str, *, with_ai: bool = True) -> HoldingResult:
        result: ETFAnalysisResult = self._etf.analyze(symbol, with_ai=with_ai)
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

    def _analyze_cn_fund(self, symbol: str, *, with_ai: bool = True) -> HoldingResult:
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
        # 原有 6 个
        "ma_alignment": ind.get("ma_alignment"),
        "rsi": ind.get("rsi"),
        "macd_cross": ind.get("macd_cross"),
        "return_20d": ind.get("return_20d"),
        "return_60d": ind.get("return_60d"),
        "position_60d": ind.get("position_60d"),
        # 补全：MA 数值
        "ma5": ind.get("ma5"),
        "ma20": ind.get("ma20"),
        "ma60": ind.get("ma60"),
        # 补全：MACD 数值
        "macd_dif": ind.get("macd_dif"),
        "macd_bar": ind.get("macd_bar"),
        # 补全：布林位置
        "boll_position": ind.get("boll_position"),
        # 补全：短期收益
        "return_5d": ind.get("return_5d"),
        "return_10d": ind.get("return_10d"),
        # 补全：量能
        "volume_ratio": ind.get("volume_ratio"),
        # 补全：新高新低 + 60日高
        "new_high_60d": ind.get("new_high_60d"),
        "new_low_60d": ind.get("new_low_60d"),
        "high_60d": ind.get("high_60d"),
        # regime 推断（方案 A）
        "regime": ind.get("regime"),
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
