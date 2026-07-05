"""ETF 技术指标计算层 —— 复用 core.ta 原语,输出扁平化 dict 供规则引擎消费。"""
import logging

import pandas as pd

from investbrief.core import ta

logger = logging.getLogger(__name__)


def compute_indicators(hist_df: pd.DataFrame) -> dict:
    """从历史 OHLCV 计算全部技术指标。hist_df 需含 close/volume,date 为 index。"""
    if hist_df is None or hist_df.empty or len(hist_df) < 5:
        return {}
    close = hist_df["close"]
    volume = hist_df["volume"] if "volume" in hist_df.columns else pd.Series(dtype=float)
    result: dict = {}
    for fn, args in (
        (ta.ma_set, (close,)),
        (ta.macd, (close,)),
        (lambda c: {"rsi": ta.rsi(c)}, (close,)),
        (ta.bollinger, (close,)),
        (ta.returns, (close,)),
        (lambda v: {"volume_ratio": ta.volume_ratio(v)}, (volume,)),
        (ta.high_low, (close,)),
    ):
        try:
            result.update(fn(*args) or {})
        except Exception as e:
            logger.warning(f"TA calc failed: {e}")
    _calc_regime(result)
    return result


def _calc_regime(out: dict):
    """从 ma_alignment + return_60d + volume_ratio 推断 regime(持仓 prompt 用)。"""
    ma = out.get("ma_alignment")
    r60 = out.get("return_60d")
    if ma is None or r60 is None:
        return
    vr = out.get("volume_ratio")
    if ma == "bullish" and r60 > 5:
        out["regime"] = "trending_up"
    elif ma == "bearish" and r60 < -5:
        out["regime"] = "trending_down"
    elif vr is not None and vr > 2.0 and -10 < r60 < 10:
        out["regime"] = "volatile"
    else:
        out["regime"] = "sideways"
