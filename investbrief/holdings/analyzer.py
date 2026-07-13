"""持仓标的分析（纯 CN）：按 type 分发到不同数据源，整合多维度（价格/评级/基本面/资金流）。

范围：CN 股票 + CN ETF（复用 etf 包）+ CN 场外基金。US 持仓分析已移除。
评级用单期快照；评级多期变化与技术面/新闻维度留 P2/P3。

韧性：单个数据源失败 try/except 跳过，对应维度留空，renderer 优雅降级，不阻塞整体。
跨标的去重缓存：同一 (symbol, market, type) 在一次运行内只分析一次（多收件人共享）。
"""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from typing import Any
from collections.abc import Callable

import pandas as pd

from investbrief.datasources.akshare import AKShareClient
from investbrief.holdings.etf.analyzer import ETFAnalyzer, ETFAnalysisResult
from investbrief.holdings.etf.indicators import compute_indicators
from investbrief.picks.cache import FactorCache

logger = logging.getLogger(__name__)

# 串行化(max_workers=1)：用时间换稳定 —— 请求严格按全局 2.5s 节流速率，em 不再
# 觉高频 → 不触发 IP 限流。CN stock 专题接口多，并发(max 2)会拉高请求密度触发限流。
_pool = ThreadPoolExecutor(max_workers=1)
# _parallel 总超时（秒）：兜底防某 task 卡死（em 连接挂起等）拖垮整个分析；
# 超时后 cancel 剩余 task + 降级返回部分结果（优先保邮件发出，数据可降级）。
_PARALLEL_TIMEOUT = 150

# 跨日 TTL 缓存(复用 picks.cache.FactorCache): rating/fundamentals/cn_activity
# 是季频数据(分析师评级 / 财报 / 机构调研), TTL=7 天安全; quote/history/news 高频不缓存。
# 缓存文件 data/holdings_cache.db(与 picks_cache.db 分库, key 不碰撞), 可随时清空。
# miss 即重新拉取, 引擎正确性不依赖它。线程安全由 FactorCache 内部 Lock 保证。
_fcache: FactorCache | None = None
_SEASONAL_TTL = 7.0   # 季频: 分析师评级 / 基本面 / 调研


def init_cache(path: str):
    """注入 FactorCache 单例(pipelines/holdings.py 启动时调用;测试可显式 init 或留空禁用)。"""
    global _fcache
    if _fcache is not None:
        try:
            _fcache.close()
        except Exception:
            pass
    _fcache = FactorCache(path)


def _factor_cache() -> FactorCache | None:
    return _fcache


# ---- holdings history DB-First（stock_daily 跨日复用） ----
# 持仓固定（不像 universe 扫描那样每日变动），跨日复用收益最大：有 today bar → 0 网络请求。
_db_handle = None


def _stock_db():
    """共享 BaseData 句柄用于 stock_daily DB-First。

    CNData(db_path=DB_PATH) 只触发 BaseData.__init__ → _ensure_tables（CREATE TABLE IF NOT EXISTS），
    无 refresh / 网络副作用（已验证：CNData 未覆盖 __init__）。惰性初始化，跨调用复用同一连接。
    """
    global _db_handle
    if _db_handle is None:
        from investbrief.core.config import DB_PATH
        from investbrief.data.cn_data import CNData
        _db_handle = CNData(db_path=DB_PATH)
    return _db_handle


def _history_db_first(market: str, symbol: str, *, days: int, db, live_fetch):
    """holdings history DB-First fast-path。

    1. stock_daily 有 today bar → 直接返回 DB（0 网络请求）。
    2. 否则 → live_fetch(symbol, days) 拉取 → 回写 stock_daily → 返回 live 结果。
    任一步失败 → 回退 live_fetch 原始结果（DB 不是强依赖，pipeline 不阻塞）。

    列归一化覆盖源形状：
    - CN akshare get_stock_history: lowercase 列 + DatetimeIndex(date) + amount
    date 是 index（非列），需从 index 合成并 strftime 成 "YYYY-MM-DD"（匹配 has_today_bar 的 isoformat）。
    """
    try:
        if db is not None and db.has_today_bar(market, symbol):
            cached = db.query_stock_daily(market, symbol, n=days)
            if cached is not None and not cached.empty:
                # 归一化成与 live 一致的 shape（DatetimeIndex + ohlcv[+amount]），对齐 compute_indicators 契约：
                # query_stock_daily 返回 date 为列 + market/symbol 多余列；live 路径（akshare）date 是 index。
                dt_idx = pd.to_datetime(cached["date"])
                cached = cached.drop(columns=[c for c in ("market", "symbol", "date") if c in cached.columns])
                return cached.set_index(dt_idx)
    except Exception as e:
        logger.warning(f"_history_db_first DB read {market}:{symbol} failed: {e}")
    df = live_fetch(symbol, days)
    try:
        if db is not None and isinstance(df, pd.DataFrame) and not df.empty:
            rows = df.rename(columns={
                "Open": "open", "High": "high", "Low": "low",
                "Close": "close", "Volume": "volume",
                "Date": "date",  # 兼容个别 mock 把 Date 作为列
            }).copy()
            rows["market"] = market
            rows["symbol"] = symbol
            if "date" not in rows.columns:
                rows["date"] = df.index  # akshare 源 date 是 index
            rows["date"] = pd.to_datetime(rows["date"]).dt.strftime("%Y-%m-%d")
            db.upsert_stock_df(rows)
    except Exception as e:
        logger.warning(f"_history_db_first DB write {market}:{symbol} failed: {e}")
    return df


@dataclass
class HoldingResult:
    """单个持仓标的标准化分析结果。缺失维度留空 dict/list，renderer 优雅降级。"""
    symbol: str
    market: str                  # cn
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
        self._etf = ETFAnalyzer()
        self._cache: dict[tuple, HoldingResult] = {}
        # run 级缓存：龙虎榜是全市场数据，多只 CN stock 共享一次拉取（省 ~2min/只）
        self._dragon_tiger_cache: dict[int, list] = {}
        # run 级缓存：机构调研批量预取结果（pipeline 注入；None → 单股 fallback）
        self._research_batch: dict | None = None

    def set_research_batch(self, batch: dict):
        """注入 run 级机构调研批量结果（pipeline 在分析前一次拉取注入）。

        batch: {symbol -> list[research_item]}，结构与 get_institutional_research 单股返回一致。
        注入后 _fetch_cn_activity 走 batch 查表，不再每股调 get_institutional_research。
        未注入（None）→ fallback 原单股路径（analyze_one/测试兼容）。
        """
        self._research_batch = batch

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
        """业绩日历（CN 季报披露窗口规则推算）。失败返回 {}。

        Field structure: {"next_earnings": "YYYY-MM-DD", "days_to_next": int, "is_in_window": bool}
        """
        from datetime import date
        try:
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
        """CN 大股东/高管增减持，最近窗口聚合。失败返回 {}。

        Field structure: {"net_shares": float, "direction": "buy"/"sell"/"flat",
                          "latest_date": str, "count": int}

        数据源限制：
        - CN akshare major: action 文本（"增持4.16万"/"减持..."），无数值 → 仅参与方向判定。
        - CN akshare insider: 已过滤为「增」（buy），shares 可量化。
        net_shares 仅累加可量化的 shares（股数，非金额）；方向由 sell/buy 计数主导（无可用数值时按方向多数）。
        """
        try:
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
                "net_shares": net,
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
        """CN 独有：龙虎榜上榜次数（最近 30 天）+ 机构调研次数（90 天）。非 CN 返回 {}。

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
            if self._research_batch is not None:
                # run 级批量已预取（pipeline 注入）：直接查表，省每股 90 次 API
                research = self._research_batch.get(symbol, [])
            else:
                # fallback：单股路径（analyze_one/测试）
                research = self._ak.get_institutional_research(symbol, days=90) or []
            return {
                "dragon_tiger_count": dt_count,
                "institution_research_count": len(research or []),
            }
        except Exception as e:
            logger.warning(f"cn_activity fetch failed for {symbol}: {e}")
            return None

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
        """CN 分析师评级(季频,TTL=7d 缓存原始 API 响应;最终结构 fresh build)。

        CN 无 current 依赖。raw fetch 任一源失败 → _build_cn_rating 内部优雅降级。
        current 参数保留兼容签名(忽略)。
        """
        key = f"rating:{market}:{symbol}"
        raw = self._cached(key, _SEASONAL_TTL, lambda: self._fetch_rating_raw(symbol, market))
        raw = raw or {}
        return self._build_cn_rating(raw.get("summary"), raw.get("reports"))

    def _fetch_rating_raw(self, symbol: str, market: str) -> dict:
        """拉 CN 评级原始 API 响应(akshare)。返回可 JSON 序列化的 bundle。

        stock_research_report_em 只拉一次:get_research_report_df 取 df 后共享给
        get_analyst_rating_summary / get_research_reports(解析逻辑不变,只去重数据源)。
        """
        df = self._ak.get_research_report_df(symbol)
        d = self._parallel({
            "summary": lambda: self._ak.get_analyst_rating_summary(symbol, df=df),
            "reports": lambda: self._ak.get_research_reports(symbol, limit=5, df=df),
        })
        return {"summary": d.get("summary"), "reports": d.get("reports")}

    def _collect_fundamentals(self, symbol: str, market: str):
        """CN 基本面季频源(akshare 财务指标),TTL=7d 缓存。

        返回原始 dict(get_financial_indicators 输出),由调用方构造最终 fundamentals dict
        (CN 的 pe 来自 live quote,不在此缓存)。
        """
        key = f"fund:{market}:{symbol}"
        return self._cached(key, _SEASONAL_TTL, lambda: self._fetch_fund_raw(symbol, market))

    def _fetch_fund_raw(self, symbol: str, market: str):
        return self._ak.get_financial_indicators(symbol)

    def _analyze_cn_stock(self, symbol: str, *, with_ai: bool = True) -> HoldingResult:
        # name 独立调(不进 _parallel)：避免被 em 行情 task 挤线程池饿死(name 走交易所
        # name_map 本来很快, 但并发池被慢 em task 占满时会排队→超时被 cancel→丢名)。
        # name_map 走 sh/sz/bse 交易所(非 em 不限流) + sqlite 持久缓存, 稳定拿到。
        name = self._ak._lookup_name(symbol)
        # 行情/维度并行（_pool 串行化 max_workers=1, 低频不触发 em IP 限流）
        data = self._parallel({
            "quote": lambda: self._ak.get_stock_quote(symbol),
            "flow": lambda: (self._cached(f"flow:cn:{symbol}", 1, lambda: self._ak.get_stock_fund_flow(symbol)) or {}),
            "history": lambda s=symbol: _history_db_first(
                "cn", s, days=180, db=_stock_db(),
                live_fetch=lambda sym, days=180: self._ak.get_stock_history(sym, days=days)),
            "news": lambda: self._ak.get_stock_news(symbol, limit=5),
            "events": lambda: self._collect_events(symbol, "cn"),
            "insider": lambda: self._collect_insider(symbol, "cn"),
            "cn_activity": lambda: self._collect_cn_activity(symbol, "cn"),
            "fund": lambda: self._collect_fundamentals(symbol, "cn") or {},
        })
        quote = data.get("quote") or {}
        flow = data.get("flow") or {}
        fin = data.get("fund") or {}
        name = name or quote.get("name") or symbol
        result = HoldingResult(
            symbol=symbol, market="cn", type="stock",
            name=name,
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
            news=_extract_news(data.get("news"), symbol=symbol, name=name),
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
        try:
            for f in as_completed(futures, timeout=_PARALLEL_TIMEOUT):
                k = futures[f]
                try:
                    results[k] = f.result(timeout=5)
                except Exception as e:
                    logger.warning(f"holdings parallel fetch failed [{k}]: {e}")
                    results[k] = None
        except TimeoutError:
            not_done = [f for f in futures if not f.done()]
            logger.warning(f"_parallel total timeout ({_PARALLEL_TIMEOUT}s), "
                           f"{len(not_done)} task(s) not done: {[futures[f] for f in not_done]}")
            for f in not_done:
                f.cancel()
                results.setdefault(futures[f], None)
        return results


def _extract_technicals(hist) -> dict:
    """从历史 DataFrame 提取关键技术指标（均线/RSI/MACD/区间位置/近期收益）。"""
    if hist is None or (hasattr(hist, "empty") and hist.empty):
        return {}
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


def _normalize_title(t: str) -> str:
    """标题归一化用于去重:去空格/标点(保留中文+字母+数字),取前 15 字。"""
    import re
    return re.sub(r"[^一-龥A-Za-z0-9]", "", str(t))[:15]


def _extract_news(items, symbol="", name="", limit=3, max_days=7) -> list:
    """标准化新闻列表,带三重过滤:相关性(标题含 symbol/name)+ 去重 + 时效(近 max_days 天)。

    全部过期则放宽 window(避免空)。date 兼容 Unix 时间戳与日期字符串。
    """
    if not items:
        return []
    from datetime import datetime as _dt
    today = _dt.now().date()
    seen = set()
    in_window, all_kept = [], []
    for n in items:
        title = str(n.get("title") or n.get("headline", ""))
        if not title:
            continue
        # 相关性:标题需含 symbol 或 name(给定任一时;都空则跳过该过滤)
        if (symbol or name) and (symbol not in title) and (name not in title):
            continue
        # 去重:归一化标题前 15 字比对
        key = _normalize_title(title)
        if key in seen:
            continue
        seen.add(key)
        # date(兼容时间戳/字符串)
        raw = n.get("date") or n.get("datetime")
        date_obj, date_str = None, ""
        if raw:
            if isinstance(raw, (int, float)):
                try:
                    d = _dt.fromtimestamp(int(raw))
                    date_obj, date_str = d.date(), d.strftime("%Y-%m-%d")
                except (ValueError, OSError):
                    date_str = str(raw)[:10]
            else:
                date_str = str(raw)[:10]
                try:
                    date_obj = _dt.strptime(date_str, "%Y-%m-%d").date()
                except ValueError:
                    pass
        rec = {"title": title, "date": date_str, "source": str(n.get("source", ""))}
        all_kept.append((date_obj, rec))
        if date_obj is None or (today - date_obj).days <= max_days:
            in_window.append((date_obj, rec))
    pool = in_window if in_window else all_kept  # 全过期则放宽
    pool.sort(key=lambda x: x[0] or _dt.min.date(), reverse=True)
    return [r for _, r in pool][:limit]
