# investbrief/picks/data.py
"""候选股深拉(历史/财报/估值)+ 归一化 + 缓存。

归一化是纯函数(可单测);拉取部分封装 akshare,经 FactorCache(TTL)
扛 eastmoney 限流。拉取失败返回 {} / 空 df,不抛。
"""
from __future__ import annotations
import logging

import pandas as pd

from investbrief.picks.cache import FactorCache

logger = logging.getLogger(__name__)

# 缓存单例(进程级);path 由 pipeline 注入,默认 data/picks_cache.db
_cache: FactorCache | None = None

# 日K 历史的进程内缓存(同一次运行内复用,如 _enrich 二次拉取)。
# 进 FactorCache 的 history 存储(TTL=1 天,CSV 编码)负责跨日复用;_hist_mem 只管单次运行。
_hist_mem: dict[str, pd.DataFrame] = {}


def init_cache(path: str):
    global _cache
    _cache = FactorCache(path)


def cache() -> FactorCache | None:
    return _cache


# ---- 归一化(纯函数) ----

_CN_FUND_FIELD_MAP = {
    "roe": ("净资产收益率(加权)", "净资产收益率", "ROE(加权)"),
    "gross_margin": ("销售毛利率", "毛利率"),
    "revenue_yoy": ("营业总收入同比增长率", "营业收入同比增长率"),
    "profit_yoy": ("净利润同比增长率", "归母净利润同比增长率"),
    "debt_ratio": ("资产负债率",),
}


def _pct_to_decimal(val):
    """akshare 财报百分比可能为 '20.5'(意为 20.5%)→ 0.205;已是小数则不变。"""
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    return f / 100 if abs(f) > 1.5 else f   # >1.5 视为百分数


def normalize_fundamentals(raw: dict) -> dict:
    out: dict = {}
    for key, aliases in _CN_FUND_FIELD_MAP.items():
        for a in aliases:
            if a in raw and raw[a] not in (None, "", "-"):
                out[key] = _pct_to_decimal(raw[a])
                break
    # 每股经营现金流 → fcf_positive(TODO C)。值非百分比,不走 _pct_to_decimal。
    # 兼容两种输入:raw 直接带中文 key(akshare df),或带归一化后英文 key(get_financial_indicators)。
    ocf = raw.get("每股经营现金流")
    if ocf is None or ocf in ("", "-"):
        ocf = raw.get("operating_cashflow_per_share")
    if ocf not in (None, "", "-"):
        try:
            out["fcf_positive"] = float(ocf) > 0
        except (TypeError, ValueError):
            pass
    return out


def normalize_valuation(pe, pb, pe_hist: list[float] | None, pb_hist: list[float] | None) -> dict:
    """构造 valuation dict + 3 年分位(若给历史)。"""
    def _pct(cur, hist):
        if cur is None or not hist:
            return None
        rank = sum(1 for x in hist if x <= cur)
        return round(rank / len(hist) * 100, 1)
    return {
        "pe": pe, "pb": pb,
        "pe_pct_3y": _pct(pe, pe_hist),
        "pb_pct_3y": _pct(pb, pb_hist),
        "peg": None,   # PEG 需 growth,由调用方按需补
    }


# ---- 深拉(带缓存,失败返回空) ----

def fetch_history(symbol: str, market: str, days: int = 250) -> pd.DataFrame:
    """候选股日 K 历史(CN akshare get_stock_history)。

    返回 DataFrame 列名统一为小写(close/volume/...),与 factors 读取约定一致。

    三级缓存:
    1. _hist_mem(进程内):同一次运行内复用(_enrich 二次拉取等)。
    2. FactorCache history(TTL=1 天,CSV 编码):跨日复用 —— 命中则增量补当天,
       未命中全量拉。daily scheduler 首次拉全量后,当日再跑只补最新 bar。
    3. 全量拉取:_do_fetch_history(akshare,带限流重试)。
    """
    key = f"hist:{market}:{symbol}"
    cached = _hist_mem.get(key)
    if cached is not None and not cached.empty:
        return cached
    c = cache()
    if c and c.fresh(key, ttl_days=1):
        df = c.get_history(key)
        if isinstance(df, pd.DataFrame) and not df.empty:
            df = _maybe_append_today(df, symbol, market)
            _hist_mem[key] = df
            return df
    df = _do_fetch_history(symbol, market, days)
    df = df if isinstance(df, pd.DataFrame) else pd.DataFrame()
    if not df.empty:
        _hist_mem[key] = df
        if c:
            c.set_history(key, df, ttl_days=1)
    return df


def _maybe_append_today(df: pd.DataFrame, symbol: str, market: str) -> pd.DataFrame:
    """跨日缓存命中后:若最新 bar 不是今天,拉近 10 天增量补齐(可能跨非交易日/停牌)。

    韧性:任何失败 → 返回原 df(略旧但可用,因子算 60-252 日窗口,1 日滞后可接受)。
    命中当天再次运行(df 最新 bar 已是今天)→ 直接返回,零网络调用。
    """
    try:
        if df is None or df.empty:
            return df
        idx = pd.to_datetime(df.index)
        last = idx.max()
        today = pd.Timestamp.now().normalize()
        if last >= today:
            return df   # 当天已更新过
        recent = _do_fetch_history(symbol, market, days=10)
        if recent is None or recent.empty:
            return df
        recent.index = pd.to_datetime(recent.index)
        new = recent[recent.index > last]
        if new.empty:
            return df   # 非交易日/停牌,无新 bar
        merged = pd.concat([df, new])
        merged = merged[~merged.index.duplicated(keep="last")].sort_index()
        return merged
    except Exception as e:
        logger.warning(f"_maybe_append_today {market}:{symbol} failed: {e}")
        return df


def _do_fetch_history(symbol: str, market: str, days: int) -> pd.DataFrame:
    try:
        from investbrief.datasources.akshare import AKShareClient
        df = AKShareClient().get_stock_history(symbol, days=days)
        return df if isinstance(df, pd.DataFrame) else pd.DataFrame()
    except Exception as e:
        logger.warning(f"fetch_history {market}:{symbol} failed: {e}")
        return pd.DataFrame()


def fetch_fundamentals(symbol: str, market: str) -> dict:
    """归一化后的基本面 dict。失败返回 {}。"""
    key = f"fund:{market}:{symbol}"
    c = cache()
    if c and c.fresh(key, ttl_days=7):
        return c.get(key) or {}
    raw = _do_fetch_fundamentals(symbol, market)
    out = _normalize_cn_fund(raw)
    if c and out:
        c.set(key, out, ttl_days=7)
    return out


def _do_fetch_fundamentals(symbol: str, market: str) -> dict:
    try:
        from investbrief.datasources.akshare import AKShareClient
        return AKShareClient().get_financial_indicators(symbol) or {}
    except Exception as e:
        logger.warning(f"fetch_fundamentals {market}:{symbol} failed: {e}")
        return {}


def _normalize_cn_fund(raw: dict) -> dict:
    """get_financial_indicators 输出 → 统一 fundamentals 键(小数)。

    get_financial_indicators 已把同花顺原始中文列解析成英文 key + 百分数
    (roe=10.35 表 10.35%, gross_margin, revenue_growth, profit_growth, debt_ratio,
    operating_cashflow_per_share)。这里映射到 factors 消费的统一键并转小数。
    注意:不能用 normalize_fundamentals(那个找中文 key)。
    """
    def _d(v):
        if v is None:
            return None
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return f / 100 if abs(f) > 1.5 else f
    ocf = raw.get("operating_cashflow_per_share")
    return {
        "roe": _d(raw.get("roe")),
        "gross_margin": _d(raw.get("gross_margin")),
        "revenue_yoy": _d(raw.get("revenue_growth")),
        "profit_yoy": _d(raw.get("profit_growth")),
        "debt_ratio": _d(raw.get("debt_ratio")),
        "fcf_positive": bool(ocf > 0) if ocf is not None else None,
        "capex_ratio": None,
    }


# ---- 主力资金流(CN only;US 无等价免费源) ----

def fetch_flow(symbol: str, market: str, days: int = 5) -> float | None:
    """近 N 日主力净流入占比均值(%)。正值=净流入(偏多)。

    CN: akshare stock_individual_fund_flow 取最后 N 日「主力净流入-净占比」均值。
        用 main_pct(净流入/成交额占比)而非绝对额,做截面可比归一化,避免大盘股绝对值碾压。
    US: 无等价免费源 → None(因子降级,engine 截面 rank 自动跳过)。
    cached ttl_days=1(日频变化);失败返回 None,不阻塞。
    """
    if market != "cn":
        return None
    key = f"flow:{market}:{symbol}:{days}"
    c = cache()
    if c and c.fresh(key, ttl_days=1):
        cached = c.get(key)
        if cached is not None:
            return cached
    try:
        from investbrief.datasources.akshare import AKShareClient
        df = AKShareClient().get_stock_fund_flow_history(symbol, days=days)
        if df is None or df.empty or "主力净流入-净占比" not in df.columns:
            return None
        vals = pd.to_numeric(df["主力净流入-净占比"], errors="coerce").dropna()
        if vals.empty:
            return None
        avg = float(vals.mean())
        if c:
            c.set(key, avg, ttl_days=1)
        return avg
    except Exception as e:
        logger.warning(f"fetch_flow {market}:{symbol} failed: {e}")
        return None


# ---- 多期财报(TODO B profitable_years / TODO A earliest_period) ----

def count_profitable_years(net_income_by_year: dict) -> int:
    """纯函数:从 {年份:净利润} dict 统计 > 0 的年数(单测入口)。

    年份 key 用 str(如 '2023');值为负/0/None/NaN 不计入。
    """
    if not net_income_by_year:
        return 0
    count = 0
    for _year, val in net_income_by_year.items():
        try:
            if val is not None and float(val) > 0:
                count += 1
        except (TypeError, ValueError):
            continue
    return count


def fetch_profitable_years(symbol: str, market: str) -> int | None:
    """统计盈利年数(年化报告期 12-31 且 净利润>0)。cached ttl_days=30。

    CN: stock_financial_abstract_ths(年度末报告期 + 净利润列)
    失败/数据不足 → None(gate 跳过,不静默过滤)。
    """
    key = f"prof_years:{market}:{symbol}"
    c = cache()
    if c and c.fresh(key, ttl_days=30):
        cached = c.get(key)
        if cached is not None:
            return cached
    try:
        years_dict = _cn_net_income_by_year(symbol)
    except Exception as e:
        logger.warning(f"fetch_profitable_years {market}:{symbol} failed: {e}")
        return None
    if not years_dict:
        return None
    years = count_profitable_years(years_dict)
    if c and years:
        c.set(key, years, ttl_days=30)
    return years


def _cn_amount_to_float(val) -> float:
    """解析 CN 财报金额字符串(如 '1.47亿' / '5000万' / '123.45')。

    akshare 同花顺财务摘要的 净利润 列用中文金额简写,需展开成实际数值。
    """
    if val is None or val == "" or val == "-":
        return float("nan")
    try:
        s = str(val).strip()
        multiplier = 1.0
        if s.endswith("亿"):
            multiplier = 1e8
            s = s[:-1]
        elif s.endswith("万"):
            multiplier = 1e4
            s = s[:-1]
        return float(s) * multiplier
    except (TypeError, ValueError):
        return float("nan")


def _df_empty(x) -> bool:
    """True if x is None / 不是 DataFrame / 空 DataFrame。

    akshare 在 ETF、限流或异常时可能返回 str(错误消息)而非 DataFrame,
    直接 .empty 会抛 'str' object has no attribute 'empty'。统一用它防御。
    """
    return not isinstance(x, pd.DataFrame) or x.empty


def _cn_net_income_by_year(symbol: str) -> dict[str, float]:
    """从 stock_financial_abstract_ths 取年度(12-31)报告期的净利润。

    akshare 帧顺序不稳定,显式按报告期排序后再过滤 12-31。
    净利润 列是中文金额简写('1.47亿'),用 _cn_amount_to_float 解析。
    """
    from investbrief.datasources.akshare import AKShareClient
    df = AKShareClient().get_financial_abstract_df(symbol)
    if _df_empty(df) or "报告期" not in df.columns or "净利润" not in df.columns:
        return {}
    df = df.copy()
    df["_period"] = df["报告期"].astype(str)
    df = df[df["_period"].str.endswith("12-31")]
    out: dict[str, float] = {}
    for _, r in df.iterrows():
        year = r["_period"][:4]
        out[year] = _cn_amount_to_float(r.get("净利润"))
    return out


# ---- TODO A 上市时间代理(earliest report period) ----

def fetch_earliest_report_period(symbol: str, market: str) -> str | None:
    """最早可得报告期(YYYY-MM-DD 字符串)。作为 listing-time 代理(cached 90d)。

    代理逻辑: stock_individual_info_em 已对全市场崩(Length mismatch);
    使用同花顺财务摘要的最早报告期作为"上市≥该时长"的下界代理。
    已经验证该代理有区分度: 老股(600519→1998, 000001→1989)远早于
    新股(688185→2016, 001308→2018, 300750→2014)。报告期通常早于上市日
    (含 pre-IPO 报告期),故本代理偏保守(高估上市时长)。

    CN: stock_financial_abstract_ths 第一行报告期(已按时间升序)
    失败 → None(gate 跳过)。
    """
    key = f"earliest_period:{market}:{symbol}"
    c = cache()
    if c and c.fresh(key, ttl_days=90):
        cached = c.get(key)
        if cached is not None:
            return cached
    try:
        from investbrief.datasources.akshare import AKShareClient
        df = AKShareClient().get_financial_abstract_df(symbol)
        if _df_empty(df) or "报告期" not in df.columns:
            return None
        first = str(df.iloc[0]["报告期"])
        if c and first:
            c.set(key, first, ttl_days=90)
        return first or None
    except Exception as e:
        logger.warning(f"fetch_earliest_report_period {market}:{symbol} failed: {e}")
        return None
