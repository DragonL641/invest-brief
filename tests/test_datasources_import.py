"""Import smoke for datasources package."""
from investbrief.datasources.akshare import AKShareClient
from investbrief.datasources.tavily import TavilyClient


def test_all_clients_importable():
    assert AKShareClient is not None
    assert TavilyClient is not None
