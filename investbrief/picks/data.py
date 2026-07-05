# investbrief/picks/data.py
"""候选股深拉(历史/财报/估值)+ 归一化 + 缓存。

归一化是纯函数(可单测);拉取部分封装 akshare/yfinance,经 FactorCache(TTL)
扛 eastmoney 限流。拉取失败返回 {} / 空 df,不抛。
"""
from __future__ import annotations
import logging

import pandas as pd

from investbrief.picks.cache import FactorCache

logger = logging.getLogger(__name__)

# 缓存单例(进程级);path 由 pipeline 注入,默认 data/picks_cache.db
_cache: FactorCache | None = None


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
    """候选股日 K 历史。A股 akshare get_stock_history;美股 yfinance。

    返回 DataFrame 列名统一为小写(close/volume/...),与 factors 读取约定一致。
    """
    key = f"hist:{market}:{symbol}"
    c = cache()
    if c and c.fresh(key, ttl_days=1):
        return c.get(key) or pd.DataFrame()
    df = _do_fetch_history(symbol, market, days)
    if c and not df.empty:
        c.set(key, df, ttl_days=1)
    return df


def _do_fetch_history(symbol: str, market: str, days: int) -> pd.DataFrame:
    try:
        if market == "cn":
            from investbrief.datasources.akshare import AKShareClient
            return AKShareClient().get_stock_history(symbol, days=days) or pd.DataFrame()
        from investbrief.datasources.yfinance import YFinanceClient
        df = YFinanceClient().get_history(symbol, period=f"{days}d")
        if df is None or df.empty:
            return pd.DataFrame()
        # yfinance 返回大写列名(Open/Close/Volume),归一化为小写以匹配 factors 约定
        df = df.rename(columns={
            "Open": "open", "High": "high", "Low": "low",
            "Close": "close", "Volume": "volume",
        })
        return df
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
    out = normalize_fundamentals(raw) if market == "cn" else _normalize_us_fund(raw)
    if c and out:
        c.set(key, out, ttl_days=7)
    return out


def _do_fetch_fundamentals(symbol: str, market: str) -> dict:
    try:
        if market == "cn":
            from investbrief.datasources.akshare import AKShareClient
            return AKShareClient().get_financial_indicators(symbol) or {}
        from investbrief.datasources.yfinance import YFinanceClient
        info = YFinanceClient().get_info(symbol) or {}
        return info
    except Exception as e:
        logger.warning(f"fetch_fundamentals {market}:{symbol} failed: {e}")
        return {}


def _normalize_us_fund(info: dict) -> dict:
    """yfinance .info → 统一 fundamentals 键(小数)。"""
    def _d(v):
        return None if v is None else (v / 100 if abs(v) > 1.5 else v)
    return {
        "roe": _d(info.get("returnOnEquity")),
        "gross_margin": _d(info.get("grossMargins")),
        "revenue_yoy": _d(info.get("revenueGrowth")),
        "profit_yoy": _d(info.get("earningsGrowth")),
        "debt_ratio": info.get("debtToEquity"),
        "fcf_positive": bool((info.get("freeCashflow") or 0) > 0),
        "capex_ratio": None,
    }


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
    US: yfinance Ticker.financials.loc['Net Income'](年度列,通常 ~4 年)
    失败/数据不足 → None(gate 跳过,不静默过滤)。
    """
    key = f"prof_years:{market}:{symbol}"
    c = cache()
    if c and c.fresh(key, ttl_days=30):
        cached = c.get(key)
        if cached is not None:
            return cached
    try:
        if market == "cn":
            years_dict = _cn_net_income_by_year(symbol)
        else:
            years_dict = _us_net_income_by_year(symbol)
    except Exception as e:
        logger.warning(f"fetch_profitable_years {market}:{symbol} failed: {e}")
        return None
    if not years_dict:
        return None
    years = count_profitable_years(years_dict)
    if c and years:
        c.set(key, years, ttl_days=30)
    return years


def _cn_net_income_by_year(symbol: str) -> dict[str, float]:
    """从 stock_financial_abstract_ths 取年度(12-31)报告期的净利润。

    akshare 帧顺序不稳定,显式按报告期排序后再过滤 12-31。
    """
    from investbrief.datasources.akshare import AKShareClient
    df = AKShareClient().get_financial_abstract_df(symbol)
    if df is None or df.empty or "报告期" not in df.columns or "净利润" not in df.columns:
        return {}
    df = df.copy()
    df["_period"] = df["报告期"].astype(str)
    df = df[df["_period"].str.endswith("12-31")]
    out: dict[str, float] = {}
    for _, r in df.iterrows():
        year = r["_period"][:4]
        v = r.get("净利润")
        try:
            out[year] = float(v) if v is not None and v != "" and v != "-" else float("nan")
        except (TypeError, ValueError):
            out[year] = float("nan")
    return out


def _us_net_income_by_year(symbol: str) -> dict[str, float]:
    """从 yfinance financials 取 Net Income(列是年度,通常 ~4 年)。"""
    from investbrief.datasources.yfinance import YFinanceClient
    client = YFinanceClient()
    # YFinanceClient 未暴露 financials,直接走 yfinance API(与 _normalize_us_fund 走 .info 对称)
    import yfinance as yf
    fin = yf.Ticker(symbol).financials
    if fin is None or fin.empty or "Net Income" not in fin.index:
        return {}
    row = fin.loc["Net Income"]
    out: dict[str, float] = {}
    for col in fin.columns:
        val = row.get(col)
        try:
            if val is None or pd.isna(val):
                continue
            year = str(col)[:4]
            out[year] = float(val)
        except (TypeError, ValueError):
            continue
    # 抑制未使用的 import 警告(保留 client 引用以表明该模块的归属)
    _ = client
    return out
