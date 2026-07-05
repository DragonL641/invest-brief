# tests/test_picks_universe.py
"""picks.universe: spot 快照粗筛(纯函数,对 DataFrame 操作)。"""
import pandas as pd

from investbrief.picks import universe


def _cn_row(symbol, name, amount, cap, chg60, pe=15.0, pb=2.0):
    return {"代码": symbol, "名称": name, "成交额": amount, "总市值": cap,
            "60日涨跌幅": chg60, "市盈率-动态": pe, "市净率": pb}


def test_coarse_filter_cn_excludes_st_and_illiquid():
    df = pd.DataFrame([
        _cn_row("000001", "平安银行", 2e8, 3e11, 5.0),     # 通过
        _cn_row("000002", "ST万科", 3e8, 1e11, 8.0),        # ST 剔除
        _cn_row("000003", "小票", 5e7, 2e9, 12.0),          # 流动性不足
        _cn_row("000004", "下跌票", 2e8, 3e11, -5.0),       # 60日趋势向下
    ])
    profile = {"universe": {"exclude_st": True, "min_turnover_cn": 1.0e8,
                            "trend_60d_positive": True}}
    out = universe.coarse_filter(df, profile, market="cn")
    symbols = set(out["代码"].tolist())
    assert symbols == {"000001"}


def test_coarse_filter_empty_df_returns_empty():
    out = universe.coarse_filter(pd.DataFrame(), {"universe": {}}, market="cn")
    assert out.empty


def test_coarse_filter_market_cap_band_medium():
    df = pd.DataFrame([
        _cn_row("000001", "大盘", 2e8, 2e11, 5.0),
        _cn_row("000002", "中盘", 2e8, 3e10, 5.0),   # 50~1000亿 内
        _cn_row("000003", "小盘", 2e8, 3e9, 5.0),    # <50亿 外
    ])
    profile = {"universe": {"exclude_st": True, "min_turnover_cn": 1.0e8,
                            "trend_60d_positive": True, "market_cap_cn": [5.0e9, 1.0e11]}}
    out = universe.coarse_filter(df, profile, market="cn")
    assert set(out["代码"].tolist()) == {"000002"}
