"""
Daily Report Library
"""

from .smtp_client import EmailSender, test_connection
from .api_clients import (
    FinnhubClient,
    AlphaVantageClient,
    TavilyClient,
    get_available_apis
)
from .data_provider import (
    DataProvider,
    create_provider
)

__all__ = [
    # Email
    'EmailSender',
    'test_connection',
    # API Clients
    'FinnhubClient',
    'AlphaVantageClient',
    'TavilyClient',
    'get_available_apis',
    # Data Provider
    'DataProvider',
    'create_provider',
]
