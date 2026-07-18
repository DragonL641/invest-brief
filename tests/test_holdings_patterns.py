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


# ---------- Task 2: 吞没 ----------

def test_bullish_engulfing_hit():
    O, H, L, C = _arr([(105, 106, 96, 98), (95.5, 108, 95, 107)])
    assert patterns._bullish_engulfing(O, H, L, C, 1) == ("bullish_engulfing", "看涨吞没")


def test_bullish_engulfing_not_engulfing():
    O, H, L, C = _arr([(105, 106, 96, 98), (100, 101, 99, 100.5)])  # 未吞没
    assert patterns._bullish_engulfing(O, H, L, C, 1) is None


def test_bullish_engulfing_prev_not_bearish():
    O, H, L, C = _arr([(100, 106, 96, 102), (95.5, 108, 95, 107)])  # 前根阳
    assert patterns._bullish_engulfing(O, H, L, C, 1) is None


def test_bearish_engulfing_hit():
    O, H, L, C = _arr([(100, 109, 99, 108), (109.5, 110, 97, 98)])
    assert patterns._bearish_engulfing(O, H, L, C, 1) == ("bearish_engulfing", "看跌吞没")


def test_bearish_engulfing_not_engulfing():
    O, H, L, C = _arr([(100, 109, 99, 108), (105, 109, 100, 105)])  # 未吞没
    assert patterns._bearish_engulfing(O, H, L, C, 1) is None


# ---------- Task 3: 三线打击 ----------

def test_three_line_strike_hit():
    O, H, L, C = _arr([(110, 111, 105, 106), (106, 107, 101, 102),
                        (102, 103, 97, 98), (96.5, 112, 96, 111.5)])
    assert patterns._three_line_strike(O, H, L, C, 3) == ("three_line_strike", "三线打击")


def test_three_line_strike_current_not_bullish():
    # 第4根不是阳线(阴线)→ 不构成
    O, H, L, C = _arr([(110, 111, 105, 106), (106, 107, 101, 102),
                        (102, 103, 97, 98), (96.5, 100, 96, 95)])  # C=95 < O=96.5 → 阴
    assert patterns._three_line_strike(O, H, L, C, 3) is None


def test_three_line_strike_not_engulfing_all_three():
    # 第4根未吞没全部三根
    O, H, L, C = _arr([(110, 111, 105, 106), (106, 107, 101, 102),
                        (102, 103, 97, 98), (99, 103, 98, 102)])
    assert patterns._three_line_strike(O, H, L, C, 3) is None


def test_three_line_strike_i_too_small():
    O, H, L, C = _arr([(110, 111, 105, 106), (106, 107, 101, 102), (102, 103, 97, 98)])
    assert patterns._three_line_strike(O, H, L, C, 2) is None  # i<3 guard


def test_three_line_strike_prev_not_all_bearish():
    # 前3根非全阴(第2根阳)→ None
    O, H, L, C = _arr([(110, 111, 105, 106), (100, 107, 99, 105), (102, 103, 97, 98), (96.5, 112, 96, 111.5)])
    assert patterns._three_line_strike(O, H, L, C, 3) is None


def test_three_line_strike_not_declining():
    # 前3根均阴但非逐级走低 → None
    O, H, L, C = _arr([(110, 111, 105, 106), (108, 109, 100, 101), (105, 106, 99, 102), (96.5, 112, 96, 111.5)])
    assert patterns._three_line_strike(O, H, L, C, 3) is None


# ---------- Task 4: 三白兵 / 三只黑乌鸦 ----------

def test_three_white_soldiers_hit():
    O, H, L, C = _arr([(98, 104, 97, 103), (103, 109, 102, 108), (108, 114, 107, 113)])
    assert patterns._three_white_soldiers(O, H, L, C, 2) == ("three_white_soldiers", "三白兵")


def test_three_white_soldiers_small_body():
    # 实体太小(十字)→ 不算
    O, H, L, C = _arr([(100, 104, 96, 100.5), (100.5, 108, 95, 101), (101, 112, 94, 101.5)])
    assert patterns._three_white_soldiers(O, H, L, C, 2) is None


def test_three_white_soldiers_open_outside_body():
    # 第3根开盘不在第2根实体内(O108.5 > 第2根实体上沿 108)
    O, H, L, C = _arr([(98, 104, 97, 103), (103, 109, 102, 108), (108.5, 114, 107, 113)])
    assert patterns._three_white_soldiers(O, H, L, C, 2) is None


def test_three_black_crows_hit():
    O, H, L, C = _arr([(112, 113, 107, 108), (110, 111, 103, 104), (106, 107, 99, 100)])
    assert patterns._three_black_crows(O, H, L, C, 2) == ("three_black_crows", "三只黑乌鸦")


def test_three_black_crows_not_declining():
    # 三根均阴但非逐级走低(close 108>104, 104<104.5)→ None
    O, H, L, C = _arr([(112, 113, 107, 108), (110, 111, 103, 104), (109, 110, 104, 104.5)])
    assert patterns._three_black_crows(O, H, L, C, 2) is None
