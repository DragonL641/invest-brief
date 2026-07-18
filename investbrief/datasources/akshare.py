"""A股数据客户端，基于 AKShare。"""
import atexit
import json
import logging
import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

os.environ["TQDM_DISABLE"] = "1"

import akshare as ak
import pandas as pd
import random
import requests

from investbrief.core.config import DB_PATH

# eastmoney 反爬：默认 UA 是 python-requests 几乎必拦。注入浏览器 UA + Referer。
# 只对 eastmoney 域名生效，不影响 tavily（它自设 headers 会覆盖）。
_DEFAULT_EM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
}
_orig_session_request = requests.Session.request


def _patched_session_request(self, method, url, **kwargs):
    if "eastmoney.com" in url:
        if _is_em_banned():
            _bump_stat("em_banned_short_circuit")
            raise _EMBanned("eastmoney banned (negative cache window)")
        _throttle()
        headers = kwargs.get("headers") or {}
        for k, v in _DEFAULT_EM_HEADERS.items():
            headers.setdefault(k, v)
        headers.setdefault("Connection", "close")
        kwargs["headers"] = headers
        # em 请求 8s 超时：防连接挂起无限等 + 慢响应(限流典型表现)超时计入失败，
        # 连续 3 次失败(断连/超时)触发封禁短路(300s)，后续 em 请求秒级跳过。
        kwargs.setdefault("timeout", 8)
        try:
            resp = _orig_session_request(self, method, url, **kwargs)
        except Exception as e:
            est = str(e)
            if "RemoteDisconnected" in est or "Connection aborted" in est or "timed out" in est.lower():
                _record_em_outcome(success=False)
            raise
        _record_em_outcome(success=True)
        return resp
    return _orig_session_request(self, method, url, **kwargs)


requests.Session.request = _patched_session_request

logger = logging.getLogger(__name__)


# O1: 进程级请求计数器(按接口类别聚合,剥离 symbol),供 pipeline 末尾 INFO 汇总。
# 成功(_with_retry) / 封禁短路(_patched_session_request) / 最终失败 各自分项计数。
# 生产 INFO 即可看到请求画像,不再依赖 DEBUG。
_req_stats_lock = threading.Lock()
_req_stats: dict[str, int] = {}


def _bump_stat(kind: str):
    with _req_stats_lock:
        _req_stats[kind] = _req_stats.get(kind, 0) + 1


def _stat_kind(label: str) -> str:
    """label(含 symbol 括号) → 聚合类别(剥离 symbol)。"""
    return label.split("(", 1)[0]


def get_request_stats() -> dict[str, int]:
    """返回累计请求统计快照(线程安全拷贝)。"""
    with _req_stats_lock:
        return dict(_req_stats)


def format_request_stats() -> str:
    stats = get_request_stats()
    if not stats:
        return "akshare stats: (no requests)"
    total = sum(stats.values())
    parts = [f"{k}={v}" for k, v in sorted(stats.items(), key=lambda kv: (-kv[1], kv[0]))]
    return f"akshare stats (total={total}): " + ", ".join(parts)


class _DataFrameCache:
    """Thread-safe TTL cache for AKShare full-universe DataFrames + 负缓存。"""

    def __init__(self):
        self._store: dict[str, tuple[float, pd.DataFrame]] = {}
        self._negative: dict[str, tuple[float, float]] = {}  # key -> (失败时刻, ttl)
        self._lock = threading.Lock()

    def get(self, key: str, ttl: int) -> pd.DataFrame | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            ts, df = entry
            if time.monotonic() - ts > ttl:
                del self._store[key]
                return None
            return df

    def set(self, key: str, df: pd.DataFrame):
        with self._lock:
            self._store[key] = (time.monotonic(), df)

    def mark_failed(self, key: str, neg_ttl: float = 60.0):
        """标记 key 短期内失败，neg_ttl 内不再重试（避免限流窗口反复打）。"""
        with self._lock:
            self._negative[key] = (time.monotonic(), neg_ttl)

    def is_recently_failed(self, key: str) -> bool:
        with self._lock:
            entry = self._negative.get(key)
            if entry is None:
                return False
            ts, ttl = entry
            if time.monotonic() - ts > ttl:
                del self._negative[key]
                return False
            return True


_df_cache = _DataFrameCache()


class _PersistentCache:
    """sqlite 持久缓存(跨进程)：存 JSON 序列化对象 + TTL。

    用于 name_map(代码↔名称映射，静态)等不需要每次 run 重拉的数据 —— 进程退出
    不丢，下次 run 直接读磁盘(毫秒)，彻底脱离实时接口限流/波动。线程安全。
    用 JSON 而非 pickle（pickle 反序列化有任意代码执行风险）。存 DataFrame 时
    调用方转 list[dict]（to_dict('records')）再存。
    """

    def __init__(self, path):
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT, ts REAL)"
        )
        self._conn.commit()
        self._lock = threading.Lock()

    def get(self, key: str, ttl: float):
        with self._lock:
            row = self._conn.execute(
                "SELECT value, ts FROM cache WHERE key=?", (key,)
            ).fetchone()
            if row is None:
                return None
            value, ts = row
            if time.time() - ts > ttl:
                return None
            try:
                return json.loads(value)
            except Exception:
                return None

    def set(self, key: str, value):
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO cache(key, value, ts) VALUES(?,?,?)",
                (key, json.dumps(value), time.time()),
            )
            self._conn.commit()

    def close(self):
        with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None


# 持久缓存文件 data/akshare_persist.db（与 macro_data.db 同目录，gitignored）
_persist = _PersistentCache(Path(DB_PATH).parent / "akshare_persist.db")
atexit.register(_persist.close)  # 进程退出时关闭，避免 scheduler 长跑下连接终生持有


# —— 全局节流：akshare 历史无全局 QPS 限制，eastmoney 高频请求触发 RemoteDisconnected/限流。
# 模块级 Lock + _last_request，所有 akshare 网络调用经此。
_throttle_lock = threading.Lock()
_last_request = 0.0
_MIN_INTERVAL = 2.5  # 1.5→2.5: 10 股批量深拉仍触发 eastmoney IP 级限流,加大间隔换稳定。全局 Lock 保证并发下仍守此速率。


def _throttle():
    """Block until enough time has passed since the last akshare request."""
    global _last_request
    with _throttle_lock:
        now = time.monotonic()
        wait = _MIN_INTERVAL - (now - _last_request)
        if wait > 0:
            time.sleep(wait)
        _last_request = time.monotonic()


# eastmoney IP 级反爬(RemoteDisconnected)的 negative cache: 连续 N 次断连 → 判定封禁,
# 封禁期内所有 eastmoney 请求直接 _EMBanned(不连接、不节流、不重试), 省每次 1-2s 连接 hang。
# history 有 sina fallback 兜底(封禁期照常取数); flow/quote/news/rating 封禁期降级为 None。
# 实测: 一旦 IP 被 eastmoney 反爬识别, 连续请求几乎 100% RemoteDisconnected,
# 节流间隔再大也无用 —— 必须短路避免几百次"连接→被断→重试退避"的纯浪费。
_EM_BAN_THRESHOLD = 3      # 连续 3 次 RemoteDisconnected → 封禁
_EM_BAN_DURATION = 300     # 封禁 5min(到期探活: 下次请求实连, 仍断则续封)
_em_ban_lock = threading.Lock()
_em_ban_until = 0.0
_em_consecutive_fail = 0


class _EMBanned(Exception):
    """eastmoney 处于封禁 negative-cache 窗口, 请求被短路(不连接)。"""


def _is_em_banned() -> bool:
    with _em_ban_lock:
        return time.monotonic() < _em_ban_until


def _record_em_outcome(success: bool):
    """记录 eastmoney 请求结果: 成功清零, 连续失败达阈值则触发封禁窗口。"""
    global _em_ban_until, _em_consecutive_fail
    with _em_ban_lock:
        if success:
            _em_consecutive_fail = 0
            return
        _em_consecutive_fail += 1
        if _em_consecutive_fail >= _EM_BAN_THRESHOLD:
            # 连续失败期间每次都会进此分支; 用「当前未处于封禁窗口」判据,
            # 只在「新进入封禁」时 INFO 一次, 避免重复刷屏。
            newly_banned = time.monotonic() >= _em_ban_until
            _em_ban_until = time.monotonic() + _EM_BAN_DURATION
            if newly_banned:
                logger.info(
                    f"eastmoney banned: {_em_consecutive_fail} consecutive failures, "
                    f"short-circuiting all eastmoney requests for {_EM_BAN_DURATION}s"
                )


def _with_retry(fn, *, label: str, attempts: int = 3, base_delay: float = 2.0):
    """运行 akshare 调用，带随机退避 + 最后一次长退避。

    主动节流由 _patched_session_request 在 HTTP 层统一处理(eastmoney 域名);
    这里只管失败恢复: 随机延时(uniform base_delay~2x × attempt)规避 eastmoney 节奏识别,
    最后一次重试前 max(delay, 10s) 给限流窗口冷却。
    成功返回 fn() 结果(可能为 None/空 df);全部失败返回 None 并记录 warning。
    _EMBanned(eastmoney 封禁窗口)→ 立即返回 None, 不重试(连接注定失败, 省退避)。
    """
    for attempt in range(attempts):
        t0 = time.perf_counter()
        try:
            result = fn()
            logger.debug(
                f"akshare ok label={label} "
                f"elapsed={(time.perf_counter() - t0) * 1000:.0f}ms"
            )
            _bump_stat(_stat_kind(label))
            return result
        except _EMBanned:
            # 封禁短路已在 _patched_session_request 计数,此处不重复
            return None
        except Exception as e:
            if attempt < attempts - 1:
                delay = random.uniform(base_delay, base_delay * 2) * (attempt + 1)
                if attempt == attempts - 2:
                    delay = max(delay, 10.0)
                logger.debug(
                    f"akshare retry label={label} attempt={attempt + 1}/{attempts} "
                    f"delay={delay:.1f}s: {e}"
                )
                time.sleep(delay)
                continue
            logger.warning(
                f"AKShare {label} failed after {attempts} attempts: {e}",
                exc_info=True,
            )
            _bump_stat(f"failed_{_stat_kind(label)}")
            return None


def _safe_float(val) -> float | None:
    """安全转换为 float。"""
    if val is None or val == "-" or val == "":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _to_sina_symbol(code: str) -> str:
    """bare A股 code → 新浪源格式(sh/sz/bj 前缀)。

    stock_zh_a_daily(新浪)需要交易所前缀:6 开头上交所(sh),0/3 深交所(sz),
    8/4 北交所(bj)。用于 eastmoney(stock_zh_a_hist)被限流时的 fallback。
    """
    if not code:
        return code
    head = str(code)[0]
    if head == "6":
        return f"sh{code}"
    if head in ("0", "3"):
        return f"sz{code}"
    if head in ("8", "4"):
        return f"bj{code}"
    return code


def _to_sina_etf_symbol(code: str) -> str:
    """bare ETF code → 新浪源格式。

    fund_etf_hist_sina 需交易所前缀: 沪市 ETF(5开头:510xxx/512xxx/588xxx/56x)→sh,
    深市 ETF(1开头:159xxx/15x/16x/18x)→sz。em(fund_etf_hist_em)限流时的非 em fallback。
    """
    if not code:
        return code
    head = str(code)[0]
    if head == "5":
        return f"sh{code}"
    if head == "1":
        return f"sz{code}"
    return code


class AKShareClient:
    """封装 AKShare 接口，提供统一的 A 股数据获取方法。

    每个方法内部做异常处理和空值兜底，单个接口失败不影响整体。
    """

    # ---- 指数 ----

    def _get_all_indices_df(self) -> pd.DataFrame | None:
        """获取全量指数 DataFrame（带缓存，TTL 5 分钟）。"""
        df = _df_cache.get("zh_index_spot", 300)
        if df is not None:
            return df
        df = ak.stock_zh_index_spot_em()
        if df is not None and not df.empty:
            _df_cache.set("zh_index_spot", df)
        return df

    def get_index_quote(self, symbol: str) -> dict[str, Any] | None:
        """获取指数实时行情。symbol: 如 "000001"（上证指数）。"""
        try:
            df = self._get_all_indices_df()
            if df is None or df.empty:
                return None
            row = df[df["代码"] == symbol]
            if row.empty:
                return None
            r = row.iloc[0]
            return {
                "symbol": symbol,
                "name": str(r.get("名称", "")),
                "price": self._safe_float(r.get("最新价")),
                "change": self._safe_float(r.get("涨跌额")),
                "change_pct": self._safe_float(r.get("涨跌幅")),
                "volume": self._safe_float(r.get("成交量")),
                "amount": self._safe_float(r.get("成交额")),
            }
        except Exception as e:
            logger.warning(f"AKShare get_index_quote failed for {symbol}: {e}")
            return None

    def get_index_quotes(self, symbols: list[str]) -> list[dict[str, Any]]:
        """批量获取指数实时行情。"""
        try:
            df = self._get_all_indices_df()
            if df is None or df.empty:
                return []
            results = []
            for symbol in symbols:
                row = df[df["代码"] == symbol]
                if row.empty:
                    continue
                r = row.iloc[0]
                results.append({
                    "symbol": symbol,
                    "name": str(r.get("名称", "")),
                    "price": self._safe_float(r.get("最新价")),
                    "change": self._safe_float(r.get("涨跌额")),
                    "change_pct": self._safe_float(r.get("涨跌幅")),
                    "volume": self._safe_float(r.get("成交量")),
                    "amount": self._safe_float(r.get("成交额")),
                })
            return results
        except Exception as e:
            logger.warning(f"AKShare get_index_quotes failed: {e}")
            return []

    # ---- 个股行情 ----

    def _get_all_stocks_df(self) -> pd.DataFrame | None:
        """获取全量 A 股 DataFrame（持久日级 + 进程内 5min 双层缓存；失败 60s 负缓存）。

        持久层(_persist, 1d)是跨 run 的收盘快照: em 限流日 picks 读昨日全市场快照,
        coarse_filter 仍能出候选, 不再 'no candidates'。mirror _get_all_etf_df 双层模式。
        优先级: 持久(跨run) > 进程内(5min) > 负缓存短路 > live。
        """
        cached = _persist.get("zh_a_spot", 86400)
        if cached is not None:
            return pd.DataFrame(cached)
        df = _df_cache.get("zh_a_spot", 300)
        if df is not None:
            return df
        if _df_cache.is_recently_failed("zh_a_spot"):
            return None
        df = _with_retry(lambda: ak.stock_zh_a_spot_em(), label="stock_zh_a_spot_em")
        if df is not None and not df.empty:
            _df_cache.set("zh_a_spot", df)
            _persist.set("zh_a_spot", df.to_dict("records"))  # 持久(日级)
        else:
            _df_cache.mark_failed("zh_a_spot", 60)
        return df

    # ---- 全市场 spot(picks 用) ----

    def get_cn_spot_df(self) -> "pd.DataFrame | None":
        """全量 A 股 spot 快照(5min TTL+负缓存)。picks 粗筛用。"""
        return self._get_all_stocks_df()

    def _get_name_map_df(self) -> "pd.DataFrame | None":
        """全 A 代码-名称映射（stock_info_a_code_name，走交易所 sh/sz/bse，非 em 不限流）。

        三级缓存：1. sqlite 持久(跨进程, 30d) 2. 进程内(1d) 3. 请求交易所。
        name 是静态映射 → 持久缓存跨 run 复用，holdings run 读磁盘(毫秒)不再请求
        交易所，彻底脱离接口波动。30d 自动刷新(股票改名/上市是少数)。
        """
        # 1. 持久 sqlite（跨进程，30d；存 list[dict]，读时转 DataFrame）
        cached = _persist.get("a_code_name", 30 * 86400)
        if cached is not None:
            return pd.DataFrame(cached)
        # 2. 进程内（1d，本次 run 内复用）
        df = _df_cache.get("a_code_name", 86400)
        if df is not None:
            return df
        if _df_cache.is_recently_failed("a_code_name"):
            return None
        # 3. 请求交易所（sh/sz/bse，非 em 不限流）
        df = _with_retry(lambda: ak.stock_info_a_code_name(), label="stock_info_a_code_name")
        if df is not None and not df.empty:
            _df_cache.set("a_code_name", df)
            _persist.set("a_code_name", df.to_dict("records"))  # 持久化(JSON list, 跨 run)
        else:
            _df_cache.mark_failed("a_code_name", 60)
        return df

    def _lookup_name(self, symbol: str) -> str | None:
        """查个股 name：优先静态 name_map(stock_info_a_code_name, 1d 缓存, 稳),
        fallback 实时 spot_em df(5min, em 限流可能部分缺失)。

        stock_bid_ask_em 不返回名称、stock_individual_info_em 接口漂移失败，
        故 name 必须从全市场映射查。name_map 是轻量静态源(首选)；spot_em 作
        兜底(name_map 首次拉失败/缺 symbol 时)。
        """
        nm = self._get_name_map_df()
        if nm is not None and not nm.empty:
            row = nm[nm["code"].astype(str) == symbol]
            if not row.empty:
                name = str(row.iloc[0].get("name", "")).strip()
                if name:
                    return name
        df = self._get_all_stocks_df()
        if df is None or df.empty:
            return None
        row = df[df["代码"].astype(str) == symbol]
        if row.empty:
            return None
        name = str(row.iloc[0].get("名称", "")).strip()
        return name or None

    def get_stock_quote(self, symbol: str) -> dict[str, Any] | None:
        """获取个股实时行情。用 stock_bid_ask_em 单股接口（<1s），替代全量 spot_em。"""
        df = _with_retry(
            lambda: ak.stock_bid_ask_em(symbol=symbol),
            label=f"stock_bid_ask_em({symbol})",
        )
        if df is None or df.empty:
            return None
        data = {row["item"]: row["value"] for _, row in df.iterrows()}
        return {
            "symbol": symbol,
            "name": self._lookup_name(symbol),  # bid_ask 无 name，从 cached 全量 df 补
            "price": _safe_float(data.get("最新")),
            "change": _safe_float(data.get("涨跌")),
            "change_pct": _safe_float(data.get("涨幅")),
            "open": _safe_float(data.get("今开")),
            "high": _safe_float(data.get("最高")),
            "low": _safe_float(data.get("最低")),
            "volume": _safe_float(data.get("总手")),
            "amount": _safe_float(data.get("金额")),
            "market_cap": None,  # bid_ask 无市值；individual_info_em 接口漂移失败
            "pe": None,  # PE 来自 get_financial_indicators
            "turnover_rate": _safe_float(data.get("换手")),
        }

    def get_stock_quotes(self, symbols: list[str]) -> list[dict[str, Any]]:
        """批量获取个股实时行情。"""
        try:
            df = self._get_all_stocks_df()
            if df is None or df.empty:
                return []
            symbol_set = set(symbols)
            filtered = df[df["代码"].isin(symbol_set)]
            results = []
            for _, r in filtered.iterrows():
                results.append(self._parse_stock_row(r))
            return results
        except Exception as e:
            logger.warning(f"AKShare get_stock_quotes failed: {e}")
            return []

    def _parse_stock_row(self, r: "pd.Series") -> dict[str, Any]:
        """解析单行个股数据为标准 dict。"""
        return {
            "symbol": str(r.get("代码", "")),
            "name": str(r.get("名称", "")),
            "price": self._safe_float(r.get("最新价")),
            "change": self._safe_float(r.get("涨跌额")),
            "change_pct": self._safe_float(r.get("涨跌幅")),
            "open": self._safe_float(r.get("今开")),
            "high": self._safe_float(r.get("最高")),
            "low": self._safe_float(r.get("最低")),
            "volume": self._safe_float(r.get("成交量")),
            "amount": self._safe_float(r.get("成交额")),
            "market_cap": self._safe_float(r.get("总市值")),
            "pe": self._safe_float(r.get("市盈率-动态")),
            "turnover_rate": self._safe_float(r.get("换手率")),
        }

    # ---- 历史K线 ----

    def get_stock_history(self, symbol: str, days: int = 180, start_date: str | None = None) -> pd.DataFrame | None:
        """获取个股日K线（前复权）。start_date 传 "19900101" 可拉全历史(从上市, 量化回测用)。

        eastmoney(stock_zh_a_hist)失败时 fallback 到新浪源；新浪源不支持 start_date,
        全历史请求降级为近期 days(新浪 fallback 只兜底, 不保证全历史)。
        """
        end_date = datetime.now().strftime("%Y%m%d")
        if start_date is None:
            start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
        # eastmoney 限流时 3 次重试耗 ~13s/标的;只试 1 次,失败立即转新浪 fallback。
        df = _with_retry(
            lambda: ak.stock_zh_a_hist(
                symbol=symbol, period="daily",
                start_date=start_date, end_date=end_date, adjust="qfq",
            ),
            label=f"stock_zh_a_hist({symbol})",
            attempts=1,
        )
        if df is not None and not df.empty:
            df = df.rename(columns={
                "日期": "date", "股票代码": "symbol",
                "开盘": "open", "收盘": "close",
                "最高": "high", "最低": "low",
                "成交量": "volume", "成交额": "amount",
                "振幅": "amplitude", "涨跌幅": "change_pct",
                "涨跌额": "change", "换手率": "turnover",
            })
            df["date"] = pd.to_datetime(df["date"])
            return df.set_index("date")
        # eastmoney 失败/空 → 新浪源 fallback(不走 eastmoney,绕开限流阻断)
        sina_sym = _to_sina_symbol(symbol)
        sdf = _with_retry(
            lambda: ak.stock_zh_a_daily(symbol=sina_sym, adjust="qfq"),
            label=f"stock_zh_a_daily({sina_sym})",
        )
        if sdf is None or sdf.empty:
            return None
        sdf["date"] = pd.to_datetime(sdf["date"])
        sdf = sdf.set_index("date")
        if start_date is None:
            sdf = sdf.tail(days)  # days 模式取近期; start_date 全历史模式不 tail(返回从上市全部)
        keep = [c for c in ("open", "high", "low", "close", "volume", "amount")
                if c in sdf.columns]
        return sdf[keep]

    # ---- 研报与财务 ----

    def get_research_report_df(self, symbol: str) -> pd.DataFrame | None:
        """单次拉取个股研报 DataFrame(ak.stock_research_report_em,带 retry)。

        供 get_research_reports / get_analyst_rating_summary 共享同一份 df,
        避免两个方法各自拉同一 API(经 throttle 各 ~1.5s)。
        """
        df = _with_retry(
            lambda: ak.stock_research_report_em(symbol=symbol),
            label=f"stock_research_report_em({symbol})",
        )
        if df is None or df.empty:
            return None
        return df

    def get_research_reports(
        self, symbol: str, limit: int = 10, *, df: pd.DataFrame | None = None,
    ) -> list[dict[str, Any]]:
        """获取个股研报列表。

        df: 可选预取的 stock_research_report_em DataFrame(来自 get_research_report_df)。
        传入则直接解析、不再拉 API; 不传则自行调 get_research_report_df(向后兼容)。
        """
        try:
            if df is None:
                df = self.get_research_report_df(symbol)
            if df is None or df.empty:
                return []
            df = df.head(limit)
            results = []
            for _, r in df.iterrows():
                results.append({
                    "title": str(r.get("报告名称", "")),
                    "rating": str(r.get("东财评级", "")),
                    "target_price": None,  # 东财研报接口无直接目标价字段
                    "institution": str(r.get("机构", "")),
                    "analyst": "",  # 接口不提供分析师姓名
                    "date": str(r.get("日期", "")),
                })
            return results
        except Exception as e:
            logger.warning(f"AKShare get_research_reports failed for {symbol}: {e}")
            return []

    _RATING_MAP: dict[str, str] = {
        "买入": "buy", "强烈推荐": "buy", "推荐": "buy",
        "增持": "outperform", "优于大市": "outperform",
        "中性": "neutral", "持有": "neutral", "观望": "neutral",
        "减持": "underperform", "落后大市": "underperform",
        "卖出": "sell",
    }

    def _count_rating_distribution(self, df: "pd.DataFrame") -> dict[str, int]:
        """统计给定 DataFrame 的研报评级分布（东财评级 → 标准桶）。"""
        counts = {"buy": 0, "outperform": 0, "neutral": 0, "underperform": 0, "sell": 0}
        for _, r in df.iterrows():
            en = self._RATING_MAP.get(str(r.get("东财评级", "")), "")
            if en:
                counts[en] += 1
        return counts

    def get_analyst_rating_summary(
        self, symbol: str, days: int = 90, *, df: pd.DataFrame | None = None,
    ) -> dict[str, Any] | None:
        """汇总近 `days` 天研报评级分布 + 盈利预测一致预期 + 评级变化（vs 上一 `days` 周期）。

        akshare 帧顺序不稳定，先解析日期+排序。`change` 是各评级桶占比的 pct-point
        变化（正=近期更偏多）。盈利预测一致预期仍用全量数据。

        df: 可选预取的 stock_research_report_em DataFrame(来自 get_research_report_df)。
        传入则直接解析、不再拉 API; 不传则自行调 get_research_report_df(向后兼容)。
        """
        try:
            if df is None:
                df = self.get_research_report_df(symbol)
            if df is None or df.empty:
                return None

            df = df.copy()
            df["_dt"] = pd.to_datetime(df.get("日期"), errors="coerce")
            df = df.sort_values("_dt", ascending=False)

            now = pd.Timestamp.now()
            recent_cutoff = now - pd.Timedelta(days=days)
            prev_cutoff = recent_cutoff - pd.Timedelta(days=days)
            df_recent = df[df["_dt"] >= recent_cutoff]
            df_prev = df[(df["_dt"] >= prev_cutoff) & (df["_dt"] < recent_cutoff)]

            recent_counts = self._count_rating_distribution(df_recent)
            prev_counts = self._count_rating_distribution(df_prev)

            all_buckets = ("buy", "outperform", "neutral", "underperform", "sell")
            r_tot = sum(recent_counts.values()) or 1
            p_tot = sum(prev_counts.values()) or 1
            change = {k: round(recent_counts[k] / r_tot * 100 - prev_counts[k] / p_tot * 100, 1)
                      for k in all_buckets}

            # 盈利预测一致预期（用全量数据，按年份聚合 EPS 和 PE）
            eps_forecasts: dict[str, list[float]] = {}
            pe_forecasts: dict[str, list[float]] = {}
            institutions: set[str] = set()
            import re as _re
            for _, r in df.iterrows():
                inst = str(r.get("机构", ""))
                if inst:
                    institutions.add(inst)
                for col in df.columns:
                    val = pd.to_numeric(r.get(col), errors="coerce")
                    if pd.isna(val):
                        continue
                    if "盈利预测-收益" in col:
                        m = _re.match(r"(\d{4})", col)
                        year = m.group(1) if m else col.split("-")[0][:4]
                        eps_forecasts.setdefault(year, []).append(float(val))
                    elif "盈利预测-市盈率" in col:
                        m = _re.match(r"(\d{4})", col)
                        year = m.group(1) if m else col.split("-")[0][:4]
                        pe_forecasts.setdefault(year, []).append(float(val))

            consensus: list[dict] = []
            for year in sorted(set(eps_forecasts) | set(pe_forecasts)):
                eps_vals = eps_forecasts.get(year, [])
                pe_vals = pe_forecasts.get(year, [])
                entry: dict[str, Any] = {"year": year}
                if eps_vals:
                    entry["eps_avg"] = round(sum(eps_vals) / len(eps_vals), 2)
                if pe_vals:
                    entry["pe_avg"] = round(sum(pe_vals) / len(pe_vals), 1)
                if len(eps_vals) >= 2:
                    entry["eps_growth"] = round(
                        (max(eps_vals) - min(eps_vals)) / entry["eps_avg"] * 100, 1
                    )
                consensus.append(entry)

            growth_rates: list[float] = []
            for i in range(1, len(consensus)):
                prev = consensus[i - 1].get("eps_avg")
                curr = consensus[i].get("eps_avg")
                if prev and curr and prev > 0:
                    growth_rates.append(round((curr - prev) / prev * 100, 1))

            return {
                **recent_counts,
                "total_reports": len(df_recent),
                "total_reports_all": len(df),
                "institutions": len(institutions),
                "change": change,
                "consensus": consensus,
                "eps_growth_rates": growth_rates,
                "days": days,
            }
        except Exception as e:
            logger.warning(f"AKShare get_analyst_rating_summary failed for {symbol}: {e}")
            return None

    def get_financial_indicators(self, symbol: str) -> dict[str, Any] | None:
        """获取个股最新财务指标（来自同花顺）。

        含 `每股经营现金流`（additive：picks TODO C 用，holdings/analyzer 只读旧 keys 不受影响）。
        """
        try:
            df = ak.stock_financial_abstract_ths(symbol=symbol)
            if df is None or df.empty:
                return None
            # 取最近一期报告（DataFrame 按时间升序排列，最后一条最新）
            r = df.iloc[-1]
            return {
                "eps": self._safe_float(r.get("基本每股收益")),
                "roe": self._parse_pct(r.get("净资产收益率")),
                "revenue_growth": self._parse_pct(r.get("营业总收入同比增长率")),
                "profit_growth": self._parse_pct(r.get("净利润同比增长率")),
                "gross_margin": self._parse_pct(r.get("销售毛利率")),
                "net_margin": self._parse_pct(r.get("销售净利率")),
                "debt_ratio": self._parse_pct(r.get("资产负债率")),
                "operating_cashflow_per_share": self._safe_float(r.get("每股经营现金流")),
                "report_date": str(r.get("报告期", "")),
            }
        except Exception as e:
            logger.warning(f"AKShare get_financial_indicators failed for {symbol}: {e}")
            return None

    @staticmethod
    def _parse_pct(val) -> float | None:
        """将 '23.38%' 或纯数字转为 float（去掉百分号）。"""
        if val is None or val == "-" or val == "" or val is False:
            return None
        try:
            s = str(val).replace("%", "").strip()
            return float(s)
        except (ValueError, TypeError):
            return None

    def get_financial_abstract_df(self, symbol: str) -> pd.DataFrame | None:
        """获取同花顺财务摘要多期 DataFrame（含报告期/净利润/每股经营现金流/...）。

        返回的 DataFrame 按报告期升序。picks TODO A/B 用此 df 推算:
        - earliest 报告期(listing-time proxy,TODO A)
        - annual(12-31)且 净利润>0 的年数(profitable years,TODO B)
        失败返回 None;调用方各自 try/except 降级。
        """
        try:
            df = ak.stock_financial_abstract_ths(symbol=symbol)
            if df is None or df.empty:
                return None
            return df
        except Exception as e:
            logger.warning(f"AKShare get_financial_abstract_df failed for {symbol}: {e}")
            return None

    # ---- 高管与股东变动 ----

    def _get_all_insider_trades_df(self) -> pd.DataFrame | None:
        """获取全量高管持股变动 DataFrame（带缓存，TTL 30 分钟）。"""
        df = _df_cache.get("insider_trades", 1800)
        if df is not None:
            return df
        df = ak.stock_ggcg_em(symbol="全部")
        if df is not None and not df.empty:
            _df_cache.set("insider_trades", df)
        return df

    def get_insider_trades(self, symbol: str, days: int = 30) -> list[dict[str, Any]]:
        """获取高管持股变动（东方财富）。

        调用 stock_ggcg_em() 拿全量数据，按代码和日期过滤。
        """
        try:
            df = self._get_all_insider_trades_df()
            if df is None or df.empty:
                return []
            cutoff = (datetime.now() - timedelta(days=days)).date()
            df = df[df["代码"] == symbol]
            df = df[df["公告日"].apply(lambda x: x.date() if hasattr(x, "date") else x) >= cutoff]
            results = []
            for _, r in df.iterrows():
                action = str(r.get("持股变动信息-增减", ""))
                if "增" not in action:
                    continue
                results.append({
                    "name": str(r.get("名称", "")),
                    "position": str(r.get("股东名称", "")),
                    "action": action,
                    "shares": self._safe_float(r.get("持股变动信息-变动数量")),
                    "amount": None,
                    "date": str(r.get("公告日", "")),
                })
            return results
        except Exception as e:
            logger.warning(f"AKShare get_insider_trades failed for {symbol}: {e}")
            return []

    def get_major_shareholder_trades(self, symbol: str, days: int = 90) -> list[dict[str, Any]]:
        """获取大股东增减持变动（同花顺）。

        调用 stock_shareholder_change_ths()，返回历史全量数据，按日期过滤。
        """
        try:
            df = ak.stock_shareholder_change_ths(symbol=symbol)
            if df is None or df.empty:
                return []
            cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            df["公告日期"] = df["公告日期"].astype(str)
            df = df[df["公告日期"] >= cutoff]
            results = []
            for _, r in df.iterrows():
                results.append({
                    "shareholder": str(r.get("变动股东", "")),
                    "action": str(r.get("变动数量", "")),
                    "shares": None,  # 同花顺返回的是 "增持4.16万" 文本，不是数值
                    "amount": None,
                    "date": str(r.get("公告日期", "")),
                })
            return results
        except Exception as e:
            logger.warning(
                f"AKShare get_major_shareholder_trades failed for {symbol}: {e}"
            )
            return []

    # ---- 龙虎榜 ----

    def get_dragon_tiger_list(self, days: int = 5) -> list[dict[str, Any]]:
        """获取龙虎榜数据(最近 days 自然日,一次范围查询)。

        stock_lhb_detail_em 支持 start_date+end_date,一次拉区间替代逐日循环
        (原 days 次 throttle 调用 → 1 次;days=30 时 ~45s → ~2s)。
        """
        try:
            end = datetime.now()
            start = end - timedelta(days=days)
            try:
                df = ak.stock_lhb_detail_em(
                    start_date=start.strftime("%Y%m%d"),
                    end_date=end.strftime("%Y%m%d"),
                )
            except Exception:
                return []
            if df is None or df.empty:
                return []
            results = []
            for _, r in df.iterrows():
                results.append({
                    "symbol": str(r.get("代码", "")),
                    "name": str(r.get("名称", "")),
                    "change_pct": self._safe_float(r.get("涨跌幅")),
                    "buy_amount": self._safe_float(r.get("龙虎榜买入额")),
                    "sell_amount": self._safe_float(r.get("龙虎榜卖出额")),
                    "net_buy": self._safe_float(r.get("龙虎榜净买额")),
                    "reason": str(r.get("上榜原因", "")),
                    "date": str(r.get("上榜日", "")),
                })
            return results
        except Exception as e:
            logger.warning(f"AKShare get_dragon_tiger_list failed: {e}")
            return []

    # ---- 机构调研 ----

    def get_institutional_research_batch(
        self, symbols: list[str], days: int = 90
    ) -> dict[str, list[dict[str, Any]]]:
        """批量获取机构调研统计，遍历 days 天窗口（默认 90 天）。

        增量缓存：每天 stock_jgdy_tj_em(date) 结果按日独立缓存（_persist sqlite,
        TTL 90d —— 历史调研数据是既成事实，不会变）。今天(i=0)总是请求拿最新，
        历史 89 天读缓存，miss 才请求 + 缓存（空日也缓存 [] 避免重拉）。
        冷启动后每 run 只拉今天 1 次，不再每次重拉 90 天。
        """
        # em 封禁期整体跳过:jgdy 走 eastmoney,封禁时 N 次请求注定全败(被短路),
        # 且失败不写 persist 缓存 → 死循环(每次跑重试全量)。封禁窗口直接返回空,
        # 省无谓请求。机构调研是当天事件型增量,缺失不阻塞(rating 维度另有 research_report 兜底)。
        if _is_em_banned():
            logger.info("institutional research batch skipped (eastmoney banned)")
            _bump_stat("jgdy_skipped_em_banned")
            return {s: [] for s in symbols}
        symbol_set = set(symbols)
        all_results: dict[str, list[dict[str, Any]]] = {s: [] for s in symbols}
        seen: set[str] = set()
        end = datetime.now()
        for i in range(days):
            d = end - timedelta(days=i)
            date_str = d.strftime("%Y%m%d")
            is_today = (i == 0)
            cache_key = f"jgdy:{date_str}"
            # 今天拿最新(不读缓存, 盘后可能更新); 历史读缓存(90d, 调研数据不变)
            records = None if is_today else _persist.get(cache_key, 90 * 86400)
            if records is None:
                try:
                    df = ak.stock_jgdy_tj_em(date=date_str)
                    _bump_stat("stock_jgdy_tj_em")
                except Exception:
                    _bump_stat("failed_stock_jgdy_tj_em")
                    continue
                records = [] if (df is None or df.empty) else df.to_dict("records")
                if not is_today:
                    _persist.set(cache_key, records)  # 缓存历史(含空日, 避免重拉)
            # 过滤目标 symbols + 收集（records 来自缓存或新拉, 统一 list[dict]）
            for r in records:
                sym = str(r.get("代码", ""))
                if sym not in symbol_set:
                    continue
                date_val = str(r.get("接待日期", ""))
                key = f"{sym}_{date_val}"
                if key in seen:
                    continue
                seen.add(key)
                all_results.setdefault(sym, []).append({
                    "institution": str(r.get("接待机构数量", "")),
                    "date": date_val,
                    "type": str(r.get("接待方式", "")),
                    "researchers": str(r.get("接待人员", "")),
                })
        return all_results

    def get_institutional_research(
        self, symbol: str, days: int = 7
    ) -> list[dict[str, Any]]:
        """获取个股机构调研统计（东方财富）。

        调用 stock_jgdy_tj_em() 按日期拉取，过滤指定代码。
        注意：该接口按日期分页，需要遍历多个日期。
        """
        try:
            results = []
            seen_dates: set[str] = set()
            end = datetime.now()
            # 遍历最近 days 天，逐日查询
            for i in range(days):
                d = end - timedelta(days=i)
                date_str = d.strftime("%Y%m%d")
                try:
                    df = ak.stock_jgdy_tj_em(date=date_str)
                    if df is None or df.empty:
                        continue
                except Exception:
                    continue
                df = df[df["代码"] == symbol]
                for _, r in df.iterrows():
                    date_val = str(r.get("接待日期", ""))
                    key = f"{symbol}_{date_val}"
                    if key in seen_dates:
                        continue
                    seen_dates.add(key)
                    results.append({
                        "institution": str(r.get("接待机构数量", "")),
                        "date": date_val,
                        "type": str(r.get("接待方式", "")),
                        "researchers": str(r.get("接待人员", "")),
                    })
            return results
        except Exception as e:
            logger.warning(
                f"AKShare get_institutional_research failed for {symbol}: {e}"
            )
            return []

    # ---- 个股新闻 ----

    def get_stock_news(self, symbol: str, limit: int = 20) -> list[dict[str, Any]]:
        """获取个股新闻（东方财富，日级持久缓存）。

        当天新闻缓存 _persist(1d TTL)，同日多次 run 命中跳过 em。
        """
        today = datetime.now().strftime("%Y-%m-%d")
        cache_key = f"news:{symbol}:{today}"
        cached = _persist.get(cache_key, 86400)
        if cached is not None:
            return cached[:limit]
        try:
            df = ak.stock_news_em(symbol=symbol)
            if df is None or df.empty:
                return []
            results = []
            for _, r in df.iterrows():
                results.append({
                    "title": str(r.get("新闻标题", "")),
                    "content": str(r.get("新闻内容", "")),
                    "url": str(r.get("新闻链接", "")),
                    "date": str(r.get("发布时间", "")),
                    "source": str(r.get("文章来源", "")),
                })
            _persist.set(cache_key, results)  # 持久(跨 run, 1d)
            return results[:limit]
        except Exception as e:
            logger.warning(f"AKShare get_stock_news failed for {symbol}: {e}")
            return []

    # ---- 主力资金 ----

    def get_stock_fund_flow(self, symbol: str) -> dict[str, Any] | None:
        """获取个股最新主力资金流向(日级持久缓存, 跨 run 复用)。

        当天 flow 缓存 _persist(1d TTL), 同日多次 run 命中跳过 em 请求。
        market 从代码推断: 6 开头=sh, 其他=sz。
        """
        today = datetime.now().strftime("%Y-%m-%d")
        cache_key = f"flow:{symbol}:{today}"
        cached = _persist.get(cache_key, 86400)
        if cached is not None:
            return cached
        try:
            market = "sh" if symbol.startswith("6") else "sz"
            df = _with_retry(
                lambda: ak.stock_individual_fund_flow(stock=symbol, market=market),
                label=f"fund_flow({symbol})",
            )
            if df is None or df.empty:
                return None
            r = df.iloc[-1]
            flow = {
                "date": str(r.get("日期", "")),
                "main_net": self._safe_float(r.get("主力净流入-净额")),
                "main_pct": self._safe_float(r.get("主力净流入-净占比")),
                "huge_net": self._safe_float(r.get("超大单净流入-净额")),
                "huge_pct": self._safe_float(r.get("超大单净流入-净占比")),
                "big_net": self._safe_float(r.get("大单净流入-净额")),
                "big_pct": self._safe_float(r.get("大单净流入-净占比")),
            }
            _persist.set(cache_key, flow)  # 持久(跨 run, 1d)
            return flow
        except Exception as e:
            logger.warning(f"AKShare get_stock_fund_flow failed for {symbol}: {e}")
            return None

    def get_stock_fund_flow_history(self, symbol: str, days: int = 5) -> "pd.DataFrame | None":
        """获取个股近 N 日主力资金流向全量帧(picks 资金流因子用)。

        与 get_stock_fund_flow 同源(stock_individual_fund_flow),但返回最后 N 行 DataFrame
        而非单日 dict,供调用方计算多日均值。失败返回 None。
        """
        try:
            market = "sh" if symbol.startswith("6") else "sz"
            df = _with_retry(
                lambda: ak.stock_individual_fund_flow(stock=symbol, market=market),
                label=f"fund_flow_history({symbol})",
                attempts=1,  # picks 资金流因子:限流时失败立即降级(main_flow→None),不等 3 次重试(~23s/股)
            )
            if df is None or df.empty:
                return None
            return df.tail(days).reset_index(drop=True)
        except Exception as e:
            logger.warning(f"AKShare get_stock_fund_flow_history failed for {symbol}: {e}")
            return None

    def get_sector_performance(self, sector_names: list[str]) -> list[dict[str, Any]]:
        """获取指定行业板块的涨跌幅表现。"""
        try:
            df = ak.stock_board_industry_name_em()
            if df is None or df.empty:
                return []
            results = []
            for name in sector_names:
                matched = df[df["板块名称"] == name]
                if matched.empty:
                    continue
                r = matched.iloc[0]
                results.append({
                    "name": name,
                    "change_pct": self._safe_float(r.get("涨跌幅")),
                    "up_count": self._safe_float(r.get("上涨家数")),
                    "down_count": self._safe_float(r.get("下跌家数")),
                    "leader": str(r.get("领涨股票", "")),
                    "leader_change": self._safe_float(r.get("领涨股票-涨跌幅")),
                })
            return results
        except Exception as e:
            logger.warning(f"AKShare get_sector_performance failed: {e}")
            return []

    def get_industry_stocks(self, board_name: str) -> list[dict[str, Any]]:
        """获取行业板块成分股列表。"""
        try:
            df = ak.stock_board_industry_cons_em(symbol=board_name)
            if df is None or df.empty:
                return []
            results = []
            for _, r in df.iterrows():
                results.append({
                    "symbol": str(r.get("代码", "")),
                    "name": str(r.get("名称", "")),
                    "price": self._safe_float(r.get("最新价")),
                    "change_pct": self._safe_float(r.get("涨跌幅")),
                    "change_amt": self._safe_float(r.get("涨跌额")),
                    "turnover_rate": self._safe_float(r.get("换手率")),
                    "pe": self._safe_float(r.get("市盈率-动态")),
                    "pb": self._safe_float(r.get("市净率")),
                    "volume": self._safe_float(r.get("成交量")),
                    "amount": self._safe_float(r.get("成交额")),
                })
            return results
        except Exception as e:
            logger.warning(f"AKShare get_industry_stocks failed for {board_name}: {e}")
            return []

    def get_all_fund_flow(self) -> dict[str, dict[str, Any]]:
        """获取全 A 股资金流向排名（今日）。"""
        try:
            df = ak.stock_individual_fund_flow_rank(indicator="今日")
            if df is None or df.empty:
                return {}
            results: dict[str, dict[str, Any]] = {}
            for _, r in df.iterrows():
                symbol = str(r.get("代码", ""))
                results[symbol] = {
                    "main_net": self._safe_float(r.get("今日主力净流入-净额")),
                    "main_pct": self._safe_float(r.get("今日主力净流入-净占比")),
                    "huge_net": self._safe_float(r.get("今日超大单净流入-净额")),
                    "huge_pct": self._safe_float(r.get("今日超大单净流入-净占比")),
                    "big_net": self._safe_float(r.get("今日大单净流入-净额")),
                    "big_pct": self._safe_float(r.get("今日大单净流入-净占比")),
                }
            return results
        except Exception as e:
            logger.warning(f"AKShare get_all_fund_flow failed: {e}")
            return {}

    # ---- ETF ----

    def _get_all_etf_df(self) -> pd.DataFrame | None:
        """获取全量 ETF DataFrame（持久日级 + 进程内 5min 双层缓存）。

        日级 _persist 缓存（跨 run，收盘快照路线），em 限流时读缓存不致 ETF name 丢成"未知"。
        """
        cached = _persist.get("etf_spot", 86400)
        if cached is not None:
            return pd.DataFrame(cached)
        df = _df_cache.get("etf_spot", 300)
        if df is not None:
            return df
        df = ak.fund_etf_spot_em()
        if df is not None and not df.empty:
            _df_cache.set("etf_spot", df)
            _persist.set("etf_spot", df.to_dict("records"))  # 持久(日级)
        return df

    def _get_etf_name_map(self) -> dict:
        """全市场 ETF 代码-名称映射（fund_etf_category_ths，同花顺非 em 不限流）。

        持久缓存 7d（ETF 名称极少变）。ETF name 不依赖 em spot，解耦限流。
        """
        cached = _persist.get("etf_name_map", 7 * 86400)
        if cached is not None:
            return cached
        try:
            df = ak.fund_etf_category_ths(symbol="ETF")
            if df is None or df.empty:
                return {}
            m = {str(r["基金代码"]): str(r["基金名称"]) for _, r in df.iterrows()}
            if m:
                _persist.set("etf_name_map", m)
            return m
        except Exception as e:
            logger.warning(f"etf name map failed: {e}")
            return {}

    def get_etf_name(self, symbol: str) -> str | None:
        """ETF 名称（同花顺非 em，持久缓存）。"""
        return self._get_etf_name_map().get(str(symbol))

    def _recent_periods(self) -> list[str]:
        """最近 2 个已完成报告期（stock_report_disclosure period 格式）。

        返回披露窗口已过的报告期（确保披露表已公布，避免未到期 period 返回空/格式错）。
        窗口截止日：一季4/30、半年报8/31、三季10/31、年报次年4/30。
        """
        now = datetime.now()
        y, m = now.year, now.month
        if m <= 4: return [f"{y - 1}年报"]
        if m <= 8: return [f"{y}一季", f"{y - 1}年报"]
        if m <= 10: return [f"{y}半年报", f"{y}一季"]
        return [f"{y}三季", f"{y}半年报"]

    def _recent_report_dates(self) -> list[str]:
        """最近 2 个报告期的 date 格式（yjyg/yjkb：YYYYMMDD 季度末）。"""
        now = datetime.now()
        y, m = now.year, now.month
        if m <= 3: return [f"{y - 1}1231", f"{y}0331"]
        if m <= 6: return [f"{y}0331", f"{y}0630"]
        if m <= 9: return [f"{y}0630", f"{y}0930"]
        return [f"{y}0930", f"{y}1231"]

    def get_stock_events(self, symbol: str) -> list[dict]:
        """个股事件列表（6 源合并，每源 7d _persist 缓存）。

        返回 list[{type, date, desc}]，调用方排序取最近 5。
        源：财报披露(巨潮非em) / 业绩预告+快报(em) / 解禁(em) / 分红(em) / 回购(em)。
        """
        def _cached(key, fetch):
            cached = _persist.get(key, 7 * 86400)
            if cached is not None:
                return cached
            try:
                r = fetch() or []
                if r:
                    _persist.set(key, r)
                return r
            except Exception as e:
                logger.warning(f"event source {key} failed: {e}")
                return []

        events: list[dict] = []

        # 1. 财报披露（巨潮非 em）
        def _disclosure():
            out = []
            for p in self._recent_periods():
                df = ak.stock_report_disclosure(market="沪深京", period=p)
                if df is None or df.empty: continue
                row = df[df["股票代码"] == symbol]
                if row.empty: continue
                r = row.iloc[0]
                d = r.get("实际披露") or r.get("首次预约")
                if pd.notna(d):
                    out.append({"type": "财报", "date": str(d), "desc": f"{p}披露"})
            return out
        events += _cached(f"evt:disclosure:{symbol}", _disclosure)

        # 2-3. 业绩预告 / 业绩快报（em）
        for src_name, ak_fn, label in [
            ("yjyg", ak.stock_yjyg_em, "业绩预告"),
            ("yjkb", ak.stock_yjkb_em, "业绩快报"),
        ]:
            def _yj(_ak_fn=ak_fn, _label=label):
                out = []
                for d in self._recent_report_dates():
                    df = _ak_fn(date=d)
                    if df is None or df.empty: continue
                    row = df[df["股票代码"] == symbol]
                    if row.empty: continue
                    r = row.iloc[0]
                    pub = r.get("公告日期")
                    if pd.notna(pub):
                        extra = str(r.get("预告类型", "")) if "预告" in _label else ""
                        out.append({"type": _label, "date": str(pub),
                                    "desc": f"{extra} {str(r.get('业绩变动', ''))[:30]}".strip()})
                return out
            events += _cached(f"evt:{src_name}:{symbol}", _yj)

        # 4. 解禁（em 单股）
        def _restricted():
            df = ak.stock_restricted_release_queue_em(symbol=symbol)
            if df is None or df.empty: return []
            out = []
            for _, r in df.iterrows():
                d = r.get("解禁时间")
                if pd.notna(d):
                    out.append({"type": "解禁", "date": str(d),
                                "desc": f"解禁{r.get('解禁数量', '')}股"})
            return out
        events += _cached(f"evt:restricted:{symbol}", _restricted)

        # 5. 分红（em 单股）
        def _fhps():
            df = ak.stock_fhps_detail_em(symbol=symbol)
            if df is None or df.empty: return []
            out = []
            for _, r in df.iterrows():
                d = r.get("除权除息日")
                if pd.notna(d):
                    out.append({"type": "分红", "date": str(d),
                                "desc": str(r.get("现金分红-现金分红比例描述", ""))[:30]})
            return out
        events += _cached(f"evt:fhps:{symbol}", _fhps)

        # 6. 回购（em 全市场）
        def _repurchase():
            df = ak.stock_repurchase_em()
            if df is None or df.empty: return []
            row = df[df["股票代码"] == symbol]
            if row.empty: return []
            r = row.iloc[0]
            d = r.get("最新公告日期") or r.get("回购起始时间")
            if pd.notna(d):
                return [{"type": "回购", "date": str(d),
                         "desc": f"回购{r.get('已回购金额', '')}元"}]
            return []
        events += _cached(f"evt:repurchase:{symbol}", _repurchase)

        return events

    def get_etf_spot(self, symbol: str) -> dict[str, Any] | None:
        """获取单只 ETF 实时行情。symbol: 6位代码如 "510300"。"""
        try:
            df = self._get_all_etf_df()
            if df is None or df.empty:
                return None
            row = df[df["代码"] == symbol]
            if row.empty:
                return None
            r = row.iloc[0]
            return {
                "symbol": symbol,
                "name": str(r.get("名称", "")),
                "price": self._safe_float(r.get("最新价")),
                "change": self._safe_float(r.get("涨跌额")),
                "change_pct": self._safe_float(r.get("涨跌幅")),
                "open": self._safe_float(r.get("今开")),
                "high": self._safe_float(r.get("最高")),
                "low": self._safe_float(r.get("最低")),
                "volume": self._safe_float(r.get("成交量")),
                "amount": self._safe_float(r.get("成交额")),
                "turnover_rate": self._safe_float(r.get("换手率")),
                "pe": self._safe_float(r.get("市盈率-动态")),
                "iopv": self._safe_float(r.get("IOPV实时估值")),
                "premium_rate": self._safe_float(r.get("基金折价率")),
                "main_net_flow": self._safe_float(r.get("主力净流入-净额")),
                "main_net_pct": self._safe_float(r.get("主力净流入-净占比")),
                "huge_net_flow": self._safe_float(r.get("超大单净流入-净额")),
                "big_net_flow": self._safe_float(r.get("大单净流入-净额")),
                "medium_net_flow": self._safe_float(r.get("中单净流入-净额")),
                "small_net_flow": self._safe_float(r.get("小单净流入-净额")),
                "shares_outstanding": self._safe_float(r.get("流通市值")),
                "total_market_cap": self._safe_float(r.get("总市值")),
            }
        except Exception as e:
            logger.warning(f"AKShare get_etf_spot failed for {symbol}: {e}")
            return None

    def get_etf_spot_batch(self, symbols: list[str]) -> list[dict[str, Any]]:
        """批量获取 ETF 实时行情（一次调用，多次过滤）。"""
        try:
            df = self._get_all_etf_df()
            if df is None or df.empty:
                return []
            symbol_set = set(symbols)
            filtered = df[df["代码"].isin(symbol_set)]
            results = []
            for _, r in filtered.iterrows():
                sym = str(r.get("代码", ""))
                results.append({
                    "symbol": sym,
                    "name": str(r.get("名称", "")),
                    "price": self._safe_float(r.get("最新价")),
                    "change": self._safe_float(r.get("涨跌额")),
                    "change_pct": self._safe_float(r.get("涨跌幅")),
                    "turnover_rate": self._safe_float(r.get("换手率")),
                    "iopv": self._safe_float(r.get("IOPV实时估值")),
                    "premium_rate": self._safe_float(r.get("基金折价率")),
                    "main_net_flow": self._safe_float(r.get("主力净流入-净额")),
                    "main_net_pct": self._safe_float(r.get("主力净流入-净占比")),
                    "amount": self._safe_float(r.get("成交额")),
                    "total_market_cap": self._safe_float(r.get("总市值")),
                })
            return results
        except Exception as e:
            logger.warning(f"AKShare get_etf_spot_batch failed: {e}")
            return []

    def get_etf_hist(self, symbol: str, days: int = 120, start_date: str | None = None) -> pd.DataFrame | None:
        """获取 ETF 历史日K线（前复权）。

        三级源: fund_etf_hist_em(OHLCV, em) → fund_etf_hist_sina(OHLCV, 新浪非 em 不限流)
        → fund_etf_fund_info_em(NAV, 构造平线 df)。em 限流时 sina 兜底, 保证 hist 不空。
        start_date 给定 → 全历史模式(DB-First 铺底用), 忽略 days; 否则 days 模式取近期。
        """
        end_date = datetime.now().strftime("%Y%m%d")
        sd = start_date or (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
        # 1. em 主源(OHLCV)
        try:
            df = ak.fund_etf_hist_em(
                symbol=symbol,
                period="daily",
                start_date=sd,
                end_date=end_date,
                adjust="qfq",
            )
            if df is not None and not df.empty:
                df = df.rename(columns={
                    "日期": "date", "开盘": "open", "收盘": "close",
                    "最高": "high", "最低": "low",
                    "成交量": "volume", "成交额": "amount",
                    "振幅": "amplitude", "涨跌幅": "change_pct",
                    "涨跌额": "change", "换手率": "turnover",
                })
                df["date"] = pd.to_datetime(df["date"])
                df = df.set_index("date")
                return df
        except Exception as e:
            logger.warning(f"AKShare get_etf_hist em failed for {symbol}: {e}, falling back to sina")
        # 2. sina fallback(非 em, OHLCV 全历史)
        sina_sym = _to_sina_etf_symbol(symbol)
        sdf = _with_retry(
            lambda: ak.fund_etf_hist_sina(symbol=sina_sym),
            label=f"fund_etf_hist_sina({sina_sym})",
        )
        if sdf is not None and not sdf.empty:
            sdf["date"] = pd.to_datetime(sdf["date"])
            sdf = sdf.set_index("date")
            if start_date is None:
                sdf = sdf.tail(days)  # days 模式取近期; 全历史模式(start_date)返回上市至今
            keep = [c for c in ("open", "high", "low", "close", "volume", "amount") if c in sdf.columns]
            return sdf[keep]
        # 3. NAV fallback(简化平线 df)
        nav_df = self.get_etf_nav_history(symbol, days=days)
        if nav_df is not None and not nav_df.empty:
            result = nav_df.rename(columns={"nav": "close"}).copy()
            result["open"] = result["close"]
            result["high"] = result["close"]
            result["low"] = result["close"]
            result["volume"] = 0
            result["amount"] = 0
            result["change_pct"] = result["close"].pct_change() * 100
            result["change"] = result["close"].diff()
            return result[["open", "close", "high", "low", "volume", "amount", "change_pct", "change"]]
        return None

    def get_etf_nav_history(self, fund: str, days: int = 60) -> pd.DataFrame | None:
        """获取 ETF 净值历史。fund: 基金代码如 "510300"。

        返回 DataFrame: date, nav, acc_nav。
        """
        try:
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
            df = ak.fund_etf_fund_info_em(
                fund=fund,
                start_date=start_date,
                end_date=end_date,
            )
            if df is None or df.empty:
                return None
            df = df.rename(columns={
                "净值日期": "date", "单位净值": "nav",
                "累计净值": "acc_nav",
            })
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date")
            return df[["nav", "acc_nav"]]
        except Exception as e:
            logger.warning(f"AKShare get_etf_nav_history failed for {fund}: {e}")
            return None

    def get_open_fund_nav(self, symbol: str) -> dict[str, Any] | None:
        """获取场外（开放式）基金最新净值 + 近期收益。

        场外基金按 T 日净值、T+1 公布，无实时价格/资金流/IOPV。
        返回近 1 周/1 月/3 月收益（基于单位净值序列计算）。
        """
        try:
            df = ak.fund_open_fund_info_em(symbol=symbol, indicator="单位净值走势")
            if df is None or df.empty:
                return None
            df = df.sort_values("净值日期", ascending=False)
            latest = df.iloc[0]
            nav = self._safe_float(latest.get("单位净值"))

            def _ret(n: int) -> float | None:
                if len(df) > n and nav:
                    old = self._safe_float(df.iloc[n].get("单位净值"))
                    if old:
                        return round((nav - old) / old * 100, 2)
                return None

            return {
                "symbol": symbol,
                "nav": nav,
                "acc_nav": self._safe_float(latest.get("累计净值")),
                "date": str(latest.get("净值日期", "")),
                "daily_change": self._safe_float(latest.get("日增长率")),
                "return_1w": _ret(7),
                "return_1m": _ret(30),
                "return_3m": _ret(90),
            }
        except Exception as e:
            logger.warning(f"AKShare get_open_fund_nav failed for {symbol}: {e}")
            return None

    # ETF 跟踪指数 → 乐咕乐股指数名称映射
    _ETF_INDEX_MAP: dict[str, str] = {
        "510050": "上证50", "510300": "沪深300", "510500": "中证500",
        "159915": "创业板50", "512100": "中证1000", "510880": "上证红利",
        "159901": "深证100", "510180": "上证180",
    }
    _LG_INDEX_NAMES: list[str] = [
        "上证50", "沪深300", "上证380", "创业板50", "中证500",
        "上证180", "深证红利", "深证100", "中证1000", "上证红利",
        "中证100", "中证800",
    ]

    def get_index_valuation(self, symbol: str, index_name: str | None = None) -> dict[str, Any] | None:
        """获取指数估值数据（PE/PB 及历史百分位）。

        symbol: ETF 代码或指数代码。index_name: 乐咕乐股指数名称（可选，不传则自动映射）。
        """
        if index_name is None:
            index_name = self._ETF_INDEX_MAP.get(symbol)
        if index_name is None or index_name not in self._LG_INDEX_NAMES:
            logger.debug(f"No index mapping for ETF {symbol}")
            return None
        try:
            df = ak.stock_index_pe_lg(symbol=index_name)
            if df is None or df.empty:
                return None
            r = df.iloc[-1]
            pe = self._safe_float(r.get("滚动市盈率"))
            pe_static = self._safe_float(r.get("静态市盈率"))
            # 计算历史百分位
            pe_col = pd.to_numeric(df["滚动市盈率"], errors="coerce")
            pe_pct = None
            if pe is not None and pe_col.notna().sum() > 0:
                pe_pct = round(float((pe_col.dropna() < pe).sum() / pe_col.dropna().shape[0] * 100), 1)
            return {
                "symbol": symbol,
                "index_name": index_name,
                "date": str(r.get("日期", "")),
                "index_value": self._safe_float(r.get("指数")),
                "pe_ttm": pe,
                "pe_static": pe_static,
                "pe_percentile": pe_pct,
                "pe_median": round(float(pe_col.median()), 2) if pe_col.notna().sum() > 0 else None,
            }
        except Exception as e:
            logger.warning(f"AKShare get_index_valuation failed for {symbol}: {e}")
            return None

    def search_etf(self, keyword: str) -> list[dict[str, Any]]:
        """搜索 ETF（按代码或名称模糊匹配）。"""
        try:
            df = self._get_all_etf_df()
            if df is None or df.empty:
                return []
            mask = df["代码"].str.contains(keyword, na=False) | df["名称"].str.contains(keyword, na=False)
            filtered = df[mask].head(20)
            results = []
            for _, r in filtered.iterrows():
                results.append({
                    "symbol": str(r.get("代码", "")),
                    "name": str(r.get("名称", "")),
                    "price": self._safe_float(r.get("最新价")),
                    "change_pct": self._safe_float(r.get("涨跌幅")),
                })
            return results
        except Exception as e:
            logger.warning(f"AKShare search_etf failed for {keyword}: {e}")
            return []

    # ---- 宏观货币与汇率 ----

    def get_cn_monetary_policy(self) -> dict[str, Any]:
        """最新一期宏观货币数据：LPR / M2 / M1 / 社融 / 中国10Y国债收益率。

        每个数据源独立 try/except，单点失败仅置 None，不影响其它字段。
        akshare 返回的 DataFrame 排序方向不一致，统一按日期/月份降序取首行。
        """
        result: dict[str, Any] = {
            "lpr_1y": None, "lpr_5y": None, "m2_yoy": None,
            "m1_yoy": None, "social_financing": None, "cn_10y_yield": None,
        }
        # LPR
        try:
            df = ak.macro_china_lpr()
            if df is not None and not df.empty:
                latest = df.sort_values("TRADE_DATE", ascending=False).iloc[0]
                result["lpr_1y"] = self._safe_float(latest.get("LPR1Y"))
                result["lpr_5y"] = self._safe_float(latest.get("LPR5Y"))
        except Exception as e:
            logger.warning(f"macro_china_lpr failed: {e}")
        # M2 / M1 同比
        try:
            df = ak.macro_china_money_supply()
            if df is not None and not df.empty:
                # "月份" 形如 "2008年01月份"，归一为 "2008-01" 以便排序
                df = df.copy()
                df["_m"] = (
                    df["月份"].astype(str)
                    .str.replace("年", "-", regex=False)
                    .str.replace("月份", "", regex=False)
                )
                latest = df.sort_values("_m", ascending=False).iloc[0]
                result["m2_yoy"] = self._safe_float(latest.get("货币和准货币(M2)-同比增长"))
                result["m1_yoy"] = self._safe_float(latest.get("货币(M1)-同比增长"))
        except Exception as e:
            logger.warning(f"macro_china_money_supply failed: {e}")
        # 社融增量
        try:
            df = ak.macro_china_shrzgm()
            if df is not None and not df.empty:
                latest = df.sort_values("月份", ascending=False).iloc[0]
                result["social_financing"] = self._safe_float(latest.get("社会融资规模增量"))
        except Exception as e:
            logger.warning(f"macro_china_shrzgm failed: {e}")
        # 中国 10Y 国债收益率
        try:
            end = datetime.now().strftime("%Y%m%d")
            start = (datetime.now() - timedelta(days=60)).strftime("%Y%m%d")
            df = ak.bond_china_yield(start_date=start, end_date=end)
            if df is not None and not df.empty:
                cn = df[df["曲线名称"] == "中债国债收益率曲线"]
                if not cn.empty:
                    latest = cn.sort_values("日期", ascending=False).iloc[0]
                    result["cn_10y_yield"] = self._safe_float(latest.get("10年"))
        except Exception as e:
            logger.warning(f"bond_china_yield failed: {e}")
        return result

    def get_fx_rate_usdcny(self) -> dict[str, Any] | None:
        """USDCNY 即期汇率（akshare forex_spot_em，委托 get_fx_usdcny_realtime）。"""
        try:
            price = self.get_fx_usdcny_realtime()
            if price is None:
                return None
            return {
                "pair": "USDCNY",
                "price": round(price, 4),
                "change_pct": None,  # akshare 实时接口无前收, change 由 DB 两期算
            }
        except Exception as e:
            logger.warning(f"get_fx_rate_usdcny failed: {e}")
            return None

    # ---- 外围环境数据(美债/标普/USDCNY 实时) ----

    def get_us_treasury_10y(self) -> float | None:
        """美债10Y 收益率(akshare bond_zh_us_rate,最新一行'美国国债收益率10年')。失败返回 None。"""
        try:
            df = _with_retry(lambda: ak.bond_zh_us_rate(), label="us_treasury_10y")
            if df is None or df.empty:
                return None
            val = df.iloc[-1]["美国国债收益率10年"]
            return float(val) if pd.notna(val) else None
        except Exception as e:
            logger.warning(f"get_us_treasury_10y failed: {e}")
            return None

    def get_us_index_quote(self, symbol: str) -> dict | None:
        """美股指数(Sina):最新点数 + 前日涨跌幅%。symbol 如 '.INX'(标普)/'.IXIC'(纳指)。失败 None。"""
        try:
            df = _with_retry(
                lambda: ak.index_us_stock_sina(symbol=symbol), label=f"us_index_{symbol}"
            )
            if df is None or len(df) < 1:
                return None
            point = float(df.iloc[-1]["close"])
            change = 0.0
            if len(df) >= 2:
                prev = float(df.iloc[-2]["close"])
                change = round((point - prev) / prev * 100, 2) if prev else 0.0
            return {"point": point, "change": change}
        except Exception as e:
            logger.warning(f"get_us_index_quote[{symbol}] failed: {e}")
            return None

    def get_sp500_quote(self) -> dict | None:
        """标普500(委托 get_us_index_quote '.INX')。失败 None。"""
        return self.get_us_index_quote(".INX")

    def get_nasdaq_quote(self) -> dict | None:
        """纳斯达克综合(委托 get_us_index_quote '.IXIC')。失败 None。"""
        return self.get_us_index_quote(".IXIC")

    def get_fx_usdcny_realtime(self) -> float | None:
        """USDCNY 即期汇率(akshare forex_spot_em,代码 USDCNYC 美元人民币中间价)。失败返回 None。

        实测:fx_spot_quote 返回值全 NaN(不可用);forex_spot_em 返回 代码/名称/最新价,
        USDCNY 对应 代码='USDCNYC'(名称'美元人民币中间价')。
        """
        try:
            df = _with_retry(lambda: ak.forex_spot_em(), label="fx_usdcny_realtime")
            if df is None or df.empty:
                return None
            row = df[df["代码"].str.contains("USDCNY", case=False, na=False)]
            if row.empty:
                return None
            val = row.iloc[0]["最新价"]
            return float(val) if pd.notna(val) else None
        except Exception as e:
            logger.warning(f"get_fx_usdcny_realtime failed: {e}")
            return None

    def get_wti_quote(self) -> dict | None:
        """WTI 原油连续(NYMEX CL):最新价 + 前日涨跌幅%。akshare futures_foreign_hist。失败 None。"""
        try:
            df = _with_retry(lambda: ak.futures_foreign_hist(symbol="CL"), label="wti")
            if df is None or len(df) < 1:
                return None
            point = float(df.iloc[-1]["close"])
            change = 0.0
            if len(df) >= 2:
                prev = float(df.iloc[-2]["close"])
                change = round((point - prev) / prev * 100, 2) if prev else 0.0
            return {"point": point, "change": change}
        except Exception as e:
            logger.warning(f"get_wti_quote failed: {e}")
            return None

    def get_us_10y_quote(self) -> dict | None:
        """美债10Y 收益率 + 前期变动(百分点差)。akshare bond_zh_us_rate。
        最新行可能 nan(当日未更新), dropna 后取最近两期有效值。失败 None。"""
        try:
            df = _with_retry(lambda: ak.bond_zh_us_rate(), label="us_10y_quote")
            if df is None or df.empty:
                return None
            series = df["美国国债收益率10年"].dropna()
            if series.empty:
                return None
            val = float(series.iloc[-1])
            change = None
            if len(series) >= 2:
                prev = float(series.iloc[-2])
                change = round(val - prev, 2)
            return {"value": val, "change": change}
        except Exception as e:
            logger.warning(f"get_us_10y_quote failed: {e}")
            return None

    def get_usdcny_quote(self) -> dict | None:
        """USDCNY 即期 + 涨跌。forex_spot_em 为快照无历史, change 恒 None(仅返回当前值)。失败 None。"""
        try:
            value = self.get_fx_usdcny_realtime()
            if value is None:
                return None
            return {"value": round(value, 4), "change": None}
        except Exception as e:
            logger.warning(f"get_usdcny_quote failed: {e}")
            return None

    def get_cn_qvix(self) -> dict:
        """A 股 QVIX 恐慌指数(50ETF / 300ETF 期权隐含波动率)。任一失败该键为 None。"""
        out = {"qvix_50": None, "qvix_300": None}
        for key, fn in (("qvix_50", "index_option_50etf_qvix"),
                        ("qvix_300", "index_option_300etf_qvix")):
            try:
                df = _with_retry(lambda f=fn: getattr(ak, f)(), label=f"qvix_{key}")
                if df is not None and not df.empty:
                    out[key] = float(df.iloc[-1]["close"])
            except Exception as e:
                logger.warning(f"get_cn_qvix[{key}] failed: {e}")
        return out

    # ---- 工具方法 ----

    _safe_float = staticmethod(_safe_float)
