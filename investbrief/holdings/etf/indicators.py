"""ETF 技术指标计算层。

从历史价格 DataFrame 计算各类技术指标，输出扁平化 dict 供规则引擎消费。
"""

import logging

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


def compute_indicators(hist_df: pd.DataFrame) -> dict:
    """从历史 OHLCV 数据计算全部技术指标。

    hist_df 需包含: close, volume 列（date 为 index）。
    返回扁平化 dict，键名直接对应规则引擎的 condition 变量。
    """
    if hist_df is None or hist_df.empty or len(hist_df) < 5:
        return {}

    close = hist_df["close"]
    volume = hist_df["volume"] if "volume" in hist_df.columns else pd.Series(dtype=float)
    result: dict = {}

    try:
        _calc_ma(close, result)
    except Exception as e:
        logger.warning(f"MA calculation failed: {e}")

    try:
        _calc_macd(close, result)
    except Exception as e:
        logger.warning(f"MACD calculation failed: {e}")

    try:
        _calc_rsi(close, result)
    except Exception as e:
        logger.warning(f"RSI calculation failed: {e}")

    try:
        _calc_bollinger(close, result)
    except Exception as e:
        logger.warning(f"Bollinger calculation failed: {e}")

    try:
        _calc_returns(close, result)
    except Exception as e:
        logger.warning(f"Returns calculation failed: {e}")

    try:
        _calc_volume_stats(volume, result)
    except Exception as e:
        logger.warning(f"Volume stats calculation failed: {e}")

    try:
        _calc_high_low(close, result)
    except Exception as e:
        logger.warning(f"High/Low calculation failed: {e}")

    try:
        _calc_regime(result)
    except Exception as e:
        logger.warning(f"Regime inference failed: {e}")

    return result


def _calc_ma(close: pd.Series, out: dict):
    """移动平均线 + 前一日值（用于判断交叉）。"""
    for w in (5, 10, 20, 60):
        ma = close.rolling(w).mean()
        out[f"ma{w}"] = _last(ma)
        out[f"ma{w}_prev"] = _prev(ma)

    # MA 排列判断
    ma5, ma10, ma20 = out.get("ma5"), out.get("ma10"), out.get("ma20")
    if ma5 and ma10 and ma20:
        if ma5 > ma10 > ma20:
            out["ma_alignment"] = "bullish"
        elif ma5 < ma10 < ma20:
            out["ma_alignment"] = "bearish"
        else:
            out["ma_alignment"] = "mixed"


def _calc_macd(close: pd.Series, out: dict):
    """MACD 指标（DIF, DEA, MACD 柱）。"""
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    macd_bar = (dif - dea) * 2

    out["macd_dif"] = _last(dif)
    out["macd_dea"] = _last(dea)
    out["macd_bar"] = _last(macd_bar)
    out["macd_dif_prev"] = _prev(dif)
    out["macd_dea_prev"] = _prev(dea)

    # 金叉/死叉
    dif_val, dea_val = out["macd_dif"], out["macd_dea"]
    dif_prev, dea_prev = out["macd_dif_prev"], out["macd_dea_prev"]
    if dif_val and dea_val and dif_prev and dea_prev:
        if dif_prev <= dea_prev and dif_val > dea_val:
            out["macd_cross"] = "golden"
        elif dif_prev >= dea_prev and dif_val < dea_val:
            out["macd_cross"] = "death"
        else:
            out["macd_cross"] = "none"


def _calc_rsi(close: pd.Series, out: dict):
    """RSI(14)。"""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    out["rsi"] = _last(rsi)


def _calc_bollinger(close: pd.Series, out: dict):
    """布林带（20日，2倍标准差）。"""
    ma20 = close.rolling(20).mean()
    std = close.rolling(20).std()
    out["boll_upper"] = _last(ma20 + 2 * std)
    out["boll_lower"] = _last(ma20 - 2 * std)
    out["boll_mid"] = _last(ma20)
    price = _last(close)
    if price and out["boll_upper"] and out["boll_lower"]:
        out["boll_position"] = round(
            (price - out["boll_lower"]) / (out["boll_upper"] - out["boll_lower"]) * 100, 1
        )


def _calc_returns(close: pd.Series, out: dict):
    """近 N 日涨跌幅。"""
    for n in (5, 10, 20, 60):
        if len(close) > n:
            out[f"return_{n}d"] = round(float((close.iloc[-1] / close.iloc[-n - 1] - 1) * 100), 2)
        else:
            out[f"return_{n}d"] = None


def _calc_volume_stats(volume: pd.Series, out: dict):
    """成交量统计（当前 vs 20 日均值）。"""
    if volume.empty or volume.sum() == 0:
        out["volume_ratio"] = None
        return
    vol_ma20 = volume.rolling(20).mean()
    cur_vol = _last(volume)
    avg_vol = _last(vol_ma20)
    if cur_vol and avg_vol and avg_vol > 0:
        out["volume_ratio"] = round(cur_vol / avg_vol, 2)
    else:
        out["volume_ratio"] = None


def _calc_high_low(close: pd.Series, out: dict):
    """近 20/60 日最高最低价及当前位置。"""
    if len(close) < 2:
        return
    price = _last(close)
    for n in (20, 60):
        if len(close) >= n:
            high_n = float(close.iloc[-n:].max())
            low_n = float(close.iloc[-n:].min())
            out[f"high_{n}d"] = round(high_n, 4)
            out[f"low_{n}d"] = round(low_n, 4)
            if high_n != low_n and price:
                out[f"position_{n}d"] = round((price - low_n) / (high_n - low_n) * 100, 1)
            # 是否创 N 日新高/新低
            if price:
                out[f"new_high_{n}d"] = price >= high_n
                out[f"new_low_{n}d"] = price <= low_n


def _calc_regime(out: dict):
    """从 ma_alignment + return_60d + volume_ratio 推断 4 档 regime。

    用于持仓 prompt 侧重注入（方案 A）。轻量启发式，非精确预测。
    """
    ma = out.get("ma_alignment")
    r60 = out.get("return_60d")
    if ma is None or r60 is None:
        return  # 数据不足，不设 regime
    vr = out.get("volume_ratio")

    if ma == "bullish" and r60 > 5:
        out["regime"] = "trending_up"
    elif ma == "bearish" and r60 < -5:
        out["regime"] = "trending_down"
    elif vr is not None and vr > 2.0 and -10 < r60 < 10:
        out["regime"] = "volatile"
    else:
        out["regime"] = "sideways"


def _last(series: pd.Series):
    """取最后一个非 NaN 值。"""
    val = series.dropna().iloc[-1] if not series.dropna().empty else None
    if val is not None and (pd.isna(val) or np.isnan(val)):
        return None
    return round(float(val), 4) if val is not None else None


def _prev(series: pd.Series):
    """取倒数第二个非 NaN 值。"""
    clean = series.dropna()
    if len(clean) < 2:
        return None
    val = clean.iloc[-2]
    if val is not None and (pd.isna(val) or np.isnan(val)):
        return None
    return round(float(val), 4) if val is not None else None
