"""Datasources layer: low-level API clients (yfinance / akshare / finnhub / alphavantage / tavily)."""
from typing import Dict


def get_available_apis(config: Dict) -> Dict[str, bool]:
    """
    Check which APIs are configured and available.

    Returns:
        {
            "finnhub": bool,
            "alphavantage": bool,
            "tavily": bool,
            "yfinance": bool
        }
    """
    api_keys = config.get("api_keys", {})

    # yfinance doesn't need config, check import
    try:
        import yfinance
        has_yfinance = True
    except ImportError:
        has_yfinance = False

    return {
        "finnhub": bool(api_keys.get("finnhub")),
        "alphavantage": bool(api_keys.get("alphavantage")),
        "tavily": bool(api_keys.get("tavily")),
        "yfinance": has_yfinance,
    }


__all__ = ["get_available_apis"]
