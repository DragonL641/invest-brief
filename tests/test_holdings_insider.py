"""insider 采集：CN=akshare major+insider（仅增/减文本 + 可选 shares）；US=yfinance insider_transactions（仅 Buy + value）。"""
from unittest.mock import patch
from investbrief.holdings.analyzer import HoldingsAnalyzer


def test_cn_insider_aggregates_major_and_mgmt():
    """CN: major（减持，无数值）+ insider（增持，shares=200000）。
    两边都有记录但数值部分仅 insider 可量化 → 净额按可用数值合计。
    """
    a = HoldingsAnalyzer()
    major = [
        # 大股东减持：action 文本含「减」，无数值
        {"shareholder": "XX 控股", "action": "减持4.16万", "shares": None, "amount": None, "date": "2026-06-20"},
    ]
    insider = [
        # 高管增持：shares 可量化
        {"name": "张三", "position": "董事", "action": "增加", "shares": 200_000.0, "amount": None, "date": "2026-06-25"},
    ]
    with patch.object(a._ak, "get_major_shareholder_trades", return_value=major), \
         patch.object(a._ak, "get_insider_trades", return_value=insider):
        ins = a._collect_insider("002371", "cn")
    assert ins["count"] == 2
    assert ins["latest_date"] == "2026-06-25"
    # 减持方向占主导（major 减持 + insider 增持，仅按方向计数：sell=1, buy=1 → 平）
    # 但更合理：major 减持若无数值不参与净额；insider 增持 200000 → net=200000 → buy
    assert ins["direction"] == "buy"
    assert ins["net_amount"] == 200_000


def test_cn_insider_sell_dominant():
    """全部减持记录 → direction=sell。"""
    a = HoldingsAnalyzer()
    major = [
        {"shareholder": "A", "action": "减持100万", "shares": None, "amount": None, "date": "2026-06-10"},
        {"shareholder": "B", "action": "减持50万", "shares": None, "amount": None, "date": "2026-06-15"},
    ]
    insider = []
    with patch.object(a._ak, "get_major_shareholder_trades", return_value=major), \
         patch.object(a._ak, "get_insider_trades", return_value=insider):
        ins = a._collect_insider("002371", "cn")
    assert ins["direction"] == "sell"
    assert ins["count"] == 2
    assert ins["latest_date"] == "2026-06-15"


def test_us_insider_from_yfinance():
    """US: yfinance insider_transactions 全为 Buy，value 字段为交易金额。"""
    a = HoldingsAnalyzer()
    txns = [
        {"insider": "CEO", "position": "CEO", "shares": 1000, "value": 500_000.0,
         "transaction": "Buy", "date": "2026-06-20", "text": "Buy"},
        {"insider": "CFO", "position": "CFO", "shares": 500, "value": 250_000.0,
         "transaction": "Buy", "date": "2026-06-22", "text": "Buy"},
    ]
    with patch.object(a._yf, "get_insider_transactions", return_value=txns):
        ins = a._collect_insider("AAPL", "us")
    assert ins["direction"] == "buy"
    assert ins["net_amount"] == 750_000
    assert ins["count"] == 2
    assert ins["latest_date"] == "2026-06-22"


def test_insider_empty_when_no_data():
    a = HoldingsAnalyzer()
    with patch.object(a._ak, "get_major_shareholder_trades", return_value=[]), \
         patch.object(a._ak, "get_insider_trades", return_value=[]):
        ins = a._collect_insider("002371", "cn")
    assert ins == {}


def test_insider_empty_on_exception():
    a = HoldingsAnalyzer()
    with patch.object(a._yf, "get_insider_transactions", side_effect=Exception("net")):
        ins = a._collect_insider("AAPL", "us")
    assert ins == {}
