"""Import smoke for datasources package."""
from investbrief.datasources.yfinance import YFinanceClient
from investbrief.datasources.akshare import AKShareClient
from investbrief.datasources.finnhub import FinnhubClient
from investbrief.datasources.alphavantage import AlphaVantageClient
from investbrief.datasources.tavily import TavilyClient


def test_all_clients_importable():
    assert YFinanceClient is not None
    assert AKShareClient is not None
    assert FinnhubClient is not None
    assert AlphaVantageClient is not None
    assert TavilyClient is not None
