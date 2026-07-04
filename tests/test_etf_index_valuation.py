"""get_index_valuation: 510300 命中；未映射/不支持的不 warning 只返回 None。"""
import logging
from unittest.mock import patch

import pandas as pd

from investbrief.datasources.akshare import AKShareClient


def test_510300_mapped_returns_valuation():
    a = AKShareClient()
    fake_df = pd.DataFrame(
        {"滚动市盈率": [10.0, 12.0], "静态市盈率": [11.0, 13.0], "指数": [3500.0, 3600.0]}
    )
    with patch("investbrief.datasources.akshare.ak.stock_index_pe_lg", return_value=fake_df):
        v = a.get_index_valuation("510300")
    assert v is not None
    assert v["index_name"] == "沪深300"
    assert v["symbol"] == "510300"
    assert v["pe_ttm"] == 12.0


def test_unmapped_etf_returns_none_silently(caplog):
    a = AKShareClient()
    with caplog.at_level(logging.DEBUG):
        v = a.get_index_valuation("588200")  # not in _ETF_INDEX_MAP / not supported
    assert v is None
    # No WARNING-or-above "No index mapping" log (it's debug now)
    assert not any(
        "No index mapping" in r.message for r in caplog.records if r.levelno >= logging.WARNING
    )
