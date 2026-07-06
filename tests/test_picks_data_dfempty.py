# tests/test_picks_data_dfempty.py
"""picks.data._df_empty: 回归 — akshare/yfinance 对 ETF/限流返回 str 时,
直接 .empty 会抛 'str' object has no attribute 'empty'(曾让所有候选崩溃、picks 全占位)。"""
import pandas as pd
from investbrief.picks.data import _df_empty


def test_none_is_empty():
    assert _df_empty(None) is True


def test_str_is_empty():  # yfinance 对 ETF(SPY)或限流返回 str,曾触发崩溃
    assert _df_empty("No financial data") is True
    assert _df_empty("") is True


def test_empty_dataframe_is_empty():
    assert _df_empty(pd.DataFrame()) is True


def test_real_dataframe_not_empty():
    assert _df_empty(pd.DataFrame({"close": [1.0, 2.0]})) is False
