"""纯技术分析原语(从 holdings/etf/indicators.py 抽取,跨域共享)。

每个函数接收 pd.Series/DataFrame,返回 dict 或标量,无副作用。
holdings/picks 都从这里 import,避免重复实现。
"""
from __future__ import annotations
import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _last(series: pd.Series):
    s = series.dropna()
    if s.empty:
        return None
    val = s.iloc[-1]
    if pd.isna(val):
        return None
    return round(float(val), 4)


def _prev(series: pd.Series):
    s = series.dropna()
    if len(s) < 2:
        return None
    val = s.iloc[-2]
    if pd.isna(val):
        return None
    return round(float(val), 4)


def sma(close: pd.Series, window: int) -> pd.Series:
    return close.rolling(window).mean()


def ma_set(close: pd.Series, windows=(5, 10, 20, 60)) -> dict:
    """返回 {maN: last, maN_prev: prev} + ma_alignment(bullish/bearish/mixed)。"""
    out: dict = {}
    for w in windows:
        m = sma(close, w)
        out[f"ma{w}"] = _last(m)
        out[f"ma{w}_prev"] = _prev(m)
    ma5, ma10, ma20 = out.get("ma5"), out.get("ma10"), out.get("ma20")
    if ma5 and ma10 and ma20:
        if ma5 > ma10 > ma20:
            out["ma_alignment"] = "bullish"
        elif ma5 < ma10 < ma20:
            out["ma_alignment"] = "bearish"
        else:
            out["ma_alignment"] = "mixed"
    return out


def macd(close: pd.Series) -> dict:
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    bar = (dif - dea) * 2
    out = {
        "macd_dif": _last(dif), "macd_dea": _last(dea), "macd_bar": _last(bar),
        "macd_dif_prev": _prev(dif), "macd_dea_prev": _prev(dea),
    }
    dv, ev = out["macd_dif"], out["macd_dea"]
    dp, ep = out["macd_dif_prev"], out["macd_dea_prev"]
    if dv and ev and dp and ep:
        if dp <= ep and dv > ev:
            out["macd_cross"] = "golden"
        elif dp >= ep and dv < ev:
            out["macd_cross"] = "death"
        else:
            out["macd_cross"] = "none"
    return out


def rsi(close: pd.Series, window: int = 14) -> float | None:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.rolling(window).mean()
    avg_loss = loss.rolling(window).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return _last(100 - (100 / (1 + rs)))


def bollinger(close: pd.Series, window: int = 20, k: float = 2.0) -> dict:
    m = close.rolling(window).mean()
    std = close.rolling(window).std()
    upper = _last(m + k * std)
    lower = _last(m - k * std)
    price = _last(close)
    pos = None
    if price and upper and lower and upper != lower:
        pos = round((price - lower) / (upper - lower) * 100, 1)
    return {"boll_upper": upper, "boll_lower": lower, "boll_mid": _last(m), "boll_position": pos}


def returns(close: pd.Series, windows=(5, 10, 20, 60)) -> dict:
    out: dict = {}
    for n in windows:
        if len(close) > n:
            out[f"return_{n}d"] = round(float((close.iloc[-1] / close.iloc[-n - 1] - 1) * 100), 2)
        else:
            out[f"return_{n}d"] = None
    return out


def volatility(close: pd.Series, window: int = 20) -> float | None:
    """window 期日收益率标准差。"""
    if len(close) <= window:
        return None
    ret = close.pct_change().rolling(window).std()
    return _last(ret)


def volume_ratio(volume: pd.Series, window: int = 20) -> float | None:
    if volume is None or volume.empty or volume.sum() == 0:
        return None
    avg = _last(volume.rolling(window).mean())
    cur = _last(volume)
    if cur and avg and avg > 0:
        return round(cur / avg, 2)
    return None


def high_low(close: pd.Series, windows=(20, 60)) -> dict:
    out: dict = {}
    if len(close) < 2:
        return out
    price = _last(close)
    for n in windows:
        if len(close) >= n:
            hi = float(close.iloc[-n:].max())
            lo = float(close.iloc[-n:].min())
            out[f"high_{n}d"] = round(hi, 4)
            out[f"low_{n}d"] = round(lo, 4)
            if hi != lo and price:
                out[f"position_{n}d"] = round((price - lo) / (hi - lo) * 100, 1)
                out[f"new_high_{n}d"] = price >= hi
                out[f"new_low_{n}d"] = price <= lo
    return out
