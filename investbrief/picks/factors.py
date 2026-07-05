# investbrief/picks/factors.py
"""picks 因子库:统一签名 fn(hist_df, fundamentals, valuation) → float|None。

FACTOR_REGISTRY 的 key 与 strategies/pick_profiles.yaml 的 factors 名对齐。
数据不足返回 None(由 engine 在截面标准化时降级)。
"""
from __future__ import annotations
import logging

import pandas as pd

from investbrief.core import ta

logger = logging.getLogger(__name__)


# ---- swing(技术面) ----

def _trend_strength(hist, _fund, _val) -> float | None:
    if len(hist) < 60:
        return None
    close = hist["close"]
    ma60 = ta.sma(close, 60).iloc[-1]
    if pd.isna(ma60) or ma60 == 0:
        return None
    raw = close.iloc[-1] / ma60 - 1
    mas = ta.ma_set(close, (20, 60, 120))
    m20, m60, m120 = mas.get("ma20"), mas.get("ma60"), mas.get("ma120")
    aligned = bool(m20 and m60 and m120 and m20 > m60 > m120)
    return float(raw * (1.2 if aligned else 0.8))


def _momentum_60d_ex5(hist, _fund, _val) -> float | None:
    if len(hist) < 65:
        return None
    c = hist["close"]
    return float(c.iloc[-5] / c.iloc[-65] - 1)


def _ma20_deviation(hist, _fund, _val) -> float | None:
    if len(hist) < 20:
        return None
    c = hist["close"]
    ma20 = ta.sma(c, 20).iloc[-1]
    if pd.isna(ma20) or ma20 == 0:
        return None
    return abs(float(c.iloc[-1] / ma20 - 1))   # invert 由 engine 处理


def _volume_price(hist, _fund, _val) -> float | None:
    """放量上涨日均量 / 缩量回调日均量(近10日)。"""
    if len(hist) < 11:
        return None
    recent = hist.iloc[-10:]
    up = recent[recent["close"].diff() > 0]
    dn = recent[recent["close"].diff() < 0]
    up_v = up["volume"].mean() if len(up) else None
    dn_v = dn["volume"].mean() if len(dn) else None
    if not up_v or not dn_v or dn_v == 0:
        return None
    return float(up_v / dn_v)


def _low_volatility_20d(hist, _fund, _val) -> float | None:
    """20 日日收益 std(invert 由 engine 处理:越小越好)。"""
    return ta.volatility(hist["close"], 20)


FACTOR_REGISTRY: dict[str, callable] = {
    "trend_strength": _trend_strength,
    "momentum_60d_ex5": _momentum_60d_ex5,
    "ma20_deviation": _ma20_deviation,
    "volume_price": _volume_price,
    "low_volatility_20d": _low_volatility_20d,
    # medium/long 在 Task 6 追加
}
