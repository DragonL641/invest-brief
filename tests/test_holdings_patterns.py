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


# ---------- Task 5: detect_patterns 端到端 ----------

def test_e2e_bullish_engulfing_at_downtrend():
    # 58 根下跌(100→71.5),末尾 阴+阳吞没(处于跌势,趋势收益<-2%)
    rows = _trend(58, 100.0, -0.5)
    rows.append((72.0, 73.0, 70.5, 71.0, 1500))       # i-1 阴
    rows.append((70.0, 74.0, 69.5, 73.5, 2200))       # i 阳吞没(O70<=70.5, C73.5>=73)
    res = patterns.detect_patterns(_df_from_rows(rows))
    assert len(res) == 1
    assert res[0]["name_cn"] == "看涨吞没"
    assert res[0]["direction"] == "bull"
    assert res[0]["volume_confirmed"] is True
    assert res[0]["status"] == "pending"              # 最后根无 i+1
    assert res[0]["tier"] == "B"


def test_e2e_bearish_engulfing_at_uptrend():
    # 58 根上涨(50→78.5),末尾 阳+阴吞没(处于涨势)
    rows = _trend(58, 50.0, 0.5)
    rows.append((78.0, 79.0, 77.5, 78.5, 1500))       # i-1 阳
    rows.append((79.5, 80.0, 77.0, 77.5, 2200))       # i 阴吞没
    res = patterns.detect_patterns(_df_from_rows(rows))
    assert len(res) == 1
    assert res[0]["name_cn"] == "看跌吞没"
    assert res[0]["direction"] == "bear"
    assert res[0]["status"] == "pending"


def test_e2e_position_filter_drops_ranging():
    # 58 根窄幅震荡(close 在 99/101 交替,|趋势收益|<2%),末尾看涨吞没 → 丢弃
    rows = []
    for k in range(58):
        c = 101 if k % 2 == 0 else 99
        rows.append((c, c + 0.5, c - 0.5, c, 1000))
    rows.append((100.0, 100.5, 98.5, 99.0, 1500))     # 阴
    rows.append((98.0, 101.0, 97.5, 100.5, 2200))     # 阳吞没
    assert patterns.detect_patterns(_df_from_rows(rows)) == []


def test_e2e_position_filter_wrong_direction():
    # 有效看跌吞没出现在下跌趋势(看跌需涨势,方向错位)→ 位置过滤丢弃
    rows = _trend(58, 100.0, -0.5)
    rows.append((70.0, 75.0, 69.5, 74.0, 1500))       # 阳 i-1
    rows.append((75.5, 76.0, 68.5, 69.0, 2200))       # 阴吞没 i(O75.5>=H75, C69<=L69.5)
    res = patterns.detect_patterns(_df_from_rows(rows))
    assert res == []


def test_e2e_confirm_states():
    base = _trend(58, 100.0, -0.5) + [(72.0, 73.0, 70.5, 71.0, 1500), (70.0, 74.0, 69.5, 73.5, 2200)]
    # confirmed: i+1 收阳更高
    rows_confirmed = base + [(73.0, 75.5, 72.5, 75.0, 1800)]
    assert patterns.detect_patterns(_df_from_rows(rows_confirmed))[0]["status"] == "confirmed"
    # unconfirmed: i+1 收阴更低
    rows_unconfirmed = base + [(73.0, 73.5, 71.0, 71.5, 1800)]
    assert patterns.detect_patterns(_df_from_rows(rows_unconfirmed))[0]["status"] == "unconfirmed"
    # pending: 形态在最后根(无 i+1)
    assert patterns.detect_patterns(_df_from_rows(base))[0]["status"] == "pending"


def test_e2e_volume_not_confirmed():
    rows = _trend(58, 100.0, -0.5)
    rows.append((72.0, 73.0, 70.5, 71.0, 1000))       # 阴
    rows.append((70.0, 74.0, 69.5, 73.5, 1000))       # 阳吞没但缩量(量比=1.0)
    res = patterns.detect_patterns(_df_from_rows(rows))
    assert len(res) == 1
    assert res[0]["volume_confirmed"] is False        # 仍触发,仅标缩量


def test_e2e_unsorted_index():
    rows = _trend(58, 100.0, -0.5) + [(72.0, 73.0, 70.5, 71.0, 1500), (70.0, 74.0, 69.5, 73.5, 2200)]
    df = _df_from_rows(rows).sort_index(ascending=False)   # 降序输入
    res = patterns.detect_patterns(df)
    assert len(res) == 1 and res[0]["name_cn"] == "看涨吞没"


def test_e2e_lookback_boundary():
    # 形态在倒数第 7 根,lookback=5 → 不报告
    rows = _trend(52, 100.0, -0.5)
    rows.append((74.0, 75.0, 72.5, 73.0, 1500))       # 阴
    rows.append((72.0, 77.0, 71.5, 76.0, 2200))       # 阳吞没(在 i=53)
    rows += _flat(6, 76.0)                            # 推到 lookback 之外
    assert patterns.detect_patterns(_df_from_rows(rows), lookback=5) == []


def test_e2e_no_false_positive_flat():
    rows = [(100.0, 100.3, 99.7, 100.0, 1000)] * 60   # 完全平淡
    assert patterns.detect_patterns(_df_from_rows(rows)) == []


def test_e2e_three_line_strike_at_downtrend():
    # 56 根下跌 + 末尾 3 阴逐级低 + 大阳吞没(三线打击,处于跌势)
    rows = _trend(56, 100.0, -0.5)
    rows.append((74.0, 75.0, 71.0, 72.0, 1500))   # i-3 阴
    rows.append((72.0, 73.0, 69.0, 70.0, 1500))   # i-2 阴
    rows.append((70.0, 71.0, 67.0, 68.0, 1500))   # i-1 阴
    rows.append((66.0, 76.0, 65.5, 75.5, 3000))   # i 大阳吞没三根
    res = patterns.detect_patterns(_df_from_rows(rows))
    assert len(res) == 1
    assert res[0]["name_cn"] == "三线打击"          # NOT 看涨吞没 — this is the bug proof
    assert res[0]["direction"] == "bull"
    assert res[0]["volume_confirmed"] is True
    assert res[0]["status"] == "pending"


# ---------- Task 6: analyzer 集成 ----------

def test_extract_technicals_has_candle_patterns():
    from investbrief.holdings.analyzer import _extract_technicals
    rows = _trend(58, 100.0, -0.5) + [(72.0, 73.0, 70.5, 71.0, 1500), (70.0, 74.0, 69.5, 73.5, 2200)]
    hist = _df_from_rows(rows)
    tech = _extract_technicals(hist)
    assert "candle_patterns" in tech
    assert isinstance(tech["candle_patterns"], list)
    assert tech["candle_patterns"][0]["name_cn"] == "看涨吞没"


def test_extract_technicals_candle_patterns_empty_on_flat():
    from investbrief.holdings.analyzer import _extract_technicals
    hist = _df_from_rows([(100.0, 100.3, 99.7, 100.0, 1000)] * 60)
    tech = _extract_technicals(hist)
    assert tech.get("candle_patterns") == []


# ---------- Task 7: brief 集成 ----------

def test_format_holding_with_pattern():
    from investbrief.holdings.analyzer import HoldingResult
    from investbrief.holdings.brief import _format_holding
    r = HoldingResult(
        symbol="000001", market="cn", type="stock", name="平安",
        technicals={"candle_patterns": [
            {"name_cn": "看跌吞没", "direction": "bear",
             "volume_confirmed": True, "status": "confirmed"}]})
    out = _format_holding(r)
    assert "K线信号" in out
    assert "看跌吞没" in out
    assert "放量" in out
    assert "已确认" in out
    assert "辅助择时" in out


def test_format_holding_without_pattern():
    from investbrief.holdings.analyzer import HoldingResult
    from investbrief.holdings.brief import _format_holding
    r = HoldingResult(symbol="000001", market="cn", type="stock", name="平安", technicals={})
    assert "K线信号" not in _format_holding(r)
