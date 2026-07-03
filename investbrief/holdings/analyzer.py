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

    def _analyze_us_stock(self, symbol: str) -> HoldingResult:
        data = self._parallel({
            "quote": lambda: self._yf.get_quote(symbol),
            "info": lambda: self._yf.get_info(symbol),
            "recommendation": lambda: self._fh.get_recommendation(symbol),
            "price_target": lambda: self._fh.get_price_target(symbol),
            "yf_price_target": lambda: self._yf.get_price_targets(symbol),
            "upgrades": lambda: self._yf.get_upgrades_downgrades(symbol),
            "history": lambda: self._yf.get_history(symbol, period="6mo"),
            "news": lambda: self._fh.get_company_news(symbol, days=7),
        })
        quote = data.get("quote") or {}
        info = data.get("info") or {}
        current = quote.get("price")
        # finnhub price-target may 403 on free tier → fallback to yfinance
        price_target = data.get("price_target") or {}
        if not price_target.get("target_mean"):
            yf_pt = data.get("yf_price_target") or {}
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
                data.get("recommendation"), price_target,
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
        """场外基金：净值代替现价，近期收益代替基本面；无资金流/评级（接口不提供）。"""
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
        )

    # ==================== 评级结构标准化 ====================

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
