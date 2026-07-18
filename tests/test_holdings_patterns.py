"""holdings K 线形态识别测试。"""
import numpy as np
import pandas as pd

from investbrief.holdings import patterns


# ---------- fixture builders ----------

def _df_from_rows(rows, start="2026-05-01"):
    """rows: [(o,h,l,c,v), ...] → 升序 date 索引的 OHLCV DataFrame。"""
    dates = pd.date_range(start, periods=len(rows))
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=dates)


def _flat(n, price=100.0, vol=1000):
    """n 根平淡小波动根(close≈price),用于填充。"""
    out = []
    for k in range(n):
        c = price + (k % 2) * 0.1 - 0.05
        out.append((c, c + 0.2, c - 0.2, c, vol))
    return out


def _trend(n, start_price, step, vol=1000):
    """n 根单调趋势(close 每根 +step)。step>0 上涨,<0 下跌。"""
    out = []
    for k in range(n):
        c = start_price + step * k
        out.append((c, c + 0.3, c - 0.3, c, vol))
    return out


def _arr(rows):
    """rows: [(o,h,l,c), ...] → (O,H,L,C) numpy arrays(内部判定函数用)。"""
    a = np.array(rows, dtype=float)
    return a[:, 0], a[:, 1], a[:, 2], a[:, 3]


# ---------- Task 1: 兜底 ----------

def test_detect_patterns_empty_df():
    assert patterns.detect_patterns(pd.DataFrame()) == []


def test_detect_patterns_none():
    assert patterns.detect_patterns(None) == []


def test_detect_patterns_insufficient_data():
    df = _df_from_rows(_flat(4))
    assert patterns.detect_patterns(df) == []
