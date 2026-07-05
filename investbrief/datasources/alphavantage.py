"""Alpha Vantage API Client."""
import logging
from datetime import datetime
from typing import Any

import requests

from ._common import ENV_KEYS, _resolve_api_key

logger = logging.getLogger(__name__)


class AlphaVantageClient:
    """
    Alpha Vantage API Client
    Docs: https://www.alphavantage.co/documentation/

    Free tier: 25 calls/day, 5 calls/minute
    """

    BASE_URL = "https://www.alphavantage.co/query"

    def __init__(self, api_key: str | None = None):
        self.api_key = _resolve_api_key(api_key, ENV_KEYS["alphavantage"])
        self.enabled = bool(self.api_key)

    def _request(self, params: dict) -> dict | None:
        """Make authenticated request to Alpha Vantage API"""
        if not self.enabled:
            return None

        try:
            params["apikey"] = self.api_key
            response = requests.get(self.BASE_URL, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()

            # Check for API error messages
            if "Error Message" in data or "Note" in data:
                logger.warning(f"Alpha Vantage API error: {data}")
                return None

            return data
        except requests.exceptions.RequestException as e:
            logger.warning(f"Alpha Vantage API error: {e}")
            return None

    def get_daily_prices(self, symbol: str, outputsize: str = "compact") -> dict[str, Any] | None:
        """
        Get daily price data

        Args:
            symbol: Stock symbol
            outputsize: "compact" (100 days) or "full"

        Returns:
            {
                "symbol": str,
                "prices": [
                    {
                        "date": str,
                        "open": float,
                        "high": float,
                        "low": float,
                        "close": float,
                        "volume": int
                    },
                    ...
                ]
            }
        """
        data = self._request({
            "function": "TIME_SERIES_DAILY",
            "symbol": symbol,
            "outputsize": outputsize
        })

        if not data or "Time Series (Daily)" not in data:
            return None

        prices = []
        time_series = data["Time Series (Daily)"]

        for date, values in sorted(time_series.items(), reverse=True)[:30]:
            prices.append({
                "date": date,
                "open": float(values.get("1. open", 0)),
                "high": float(values.get("2. high", 0)),
                "low": float(values.get("3. low", 0)),
                "close": float(values.get("4. close", 0)),
                "volume": int(values.get("5. volume", 0))
            })

        return {
            "symbol": symbol,
            "prices": prices
        }

    def get_quote(self, symbol: str) -> dict[str, Any] | None:
        """
        Get real-time quote (Global Quote)

        Returns:
            {
                "symbol": str,
                "open": float,
                "high": float,
                "low": float,
                "price": float,
                "volume": int,
                "latest_trading_day": str,
                "previous_close": float,
                "change": float,
                "change_percent": str
            }
        """
        data = self._request({
            "function": "GLOBAL_QUOTE",
            "symbol": symbol
        })

        if not data or "Global Quote" not in data:
            return None

        quote = data["Global Quote"]
        return {
            "symbol": quote.get("01. symbol", symbol),
            "open": float(quote.get("02. open", 0)),
            "high": float(quote.get("03. high", 0)),
            "low": float(quote.get("04. low", 0)),
            "price": float(quote.get("05. price", 0)),
            "volume": int(quote.get("06. volume", 0)),
            "latest_trading_day": quote.get("07. latest trading day", ""),
            "previous_close": float(quote.get("08. previous close", 0)),
            "change": float(quote.get("09. change", 0)),
            "change_percent": quote.get("10. change percent", "0%").replace("%", "")
        }

    def get_sma(self, symbol: str, interval: str = "daily", time_period: int = 20) -> dict[str, Any] | None:
        """
        Get Simple Moving Average

        Returns:
            {
                "symbol": str,
                "interval": str,
                "period": int,
                "values": [{"date": str, "sma": float}, ...]
            }
        """
        data = self._request({
            "function": "SMA",
            "symbol": symbol,
            "interval": interval,
            "time_period": time_period,
            "series_type": "close"
        })

        if not data or "Technical Analysis: SMA" not in data:
            return None

        values = []
        for date, values_dict in sorted(data["Technical Analysis: SMA"].items(), reverse=True)[:10]:
            values.append({
                "date": date,
                "sma": float(values_dict.get("SMA", 0))
            })

        return {
            "symbol": symbol,
            "interval": interval,
            "period": time_period,
            "values": values
        }

    def get_rsi(self, symbol: str, interval: str = "daily", time_period: int = 14) -> dict[str, Any] | None:
        """
        Get Relative Strength Index

        Returns:
            {
                "symbol": str,
                "interval": str,
                "period": int,
                "values": [{"date": str, "rsi": float}, ...]
            }
        """
        data = self._request({
            "function": "RSI",
            "symbol": symbol,
            "interval": interval,
            "time_period": time_period,
            "series_type": "close"
        })

        if not data or "Technical Analysis: RSI" not in data:
            return None

        values = []
        for date, values_dict in sorted(data["Technical Analysis: RSI"].items(), reverse=True)[:10]:
            values.append({
                "date": date,
                "rsi": float(values_dict.get("RSI", 0))
            })

        return {
            "symbol": symbol,
            "interval": interval,
            "period": time_period,
            "values": values
        }

    def get_news_sentiment(self, tickers: str = None, limit: int = 50) -> list[dict[str, Any]] | None:
        """
        Get news with sentiment analysis

        Args:
            tickers: Comma-separated ticker symbols (e.g., "NVDA,AMD,MU")
            limit: Maximum number of results (max 50 for free tier)

        Returns:
            List of news items with sentiment:
            [{
                "title": str,
                "summary": str,
                "source": str,
                "time": str (relative),
                "published_at": datetime,
                "sentiment": str ("Bullish", "Bearish", "Neutral", etc.),
                "sentiment_score": float,
                "tickers": [str]
            }]
        """
        params = {
            "function": "NEWS_SENTIMENT",
            "apikey": self.api_key,
            "limit": limit
        }
        if tickers:
            params["tickers"] = tickers

        data = self._request(params)
        if not data or "feed" not in data:
            return None

        news_items = []
        now = datetime.now()
        for item in data.get("feed", []):
            # Parse publication time
            time_published = item.get("time_published", "")
            published_at = None
            if time_published:
                try:
                    published_at = datetime.strptime(time_published, "%Y%m%dT%H%M%S")
                except ValueError:
                    pass

            # Calculate relative time
            time_str = ""
            if published_at:
                delta = now - published_at
                hours = delta.total_seconds() / 3600
                if hours < 1:
                    time_str = f"{int(hours * 60)}分钟前"
                elif hours < 24:
                    time_str = f"{int(hours)}小时前"
                elif hours < 48:
                    time_str = "昨天"
                else:
                    time_str = f"{int(hours / 24)}天前"

            # Extract ticker list
            ticker_sentiments = item.get("ticker_sentiment", [])
            item_tickers = [ts.get("ticker", "") for ts in ticker_sentiments if ts.get("ticker")]

            news_items.append({
                "title": item.get("title", ""),
                "summary": item.get("summary", ""),
                "url": item.get("url", ""),
                "source": item.get("source", ""),
                "time": time_str,
                "published_at": published_at,
                "sentiment": item.get("overall_sentiment_label", "Neutral"),
                "sentiment_score": float(item.get("overall_sentiment_score", 0)),
                "tickers": item_tickers
            })

        return news_items
