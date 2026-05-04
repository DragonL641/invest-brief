"""
External API Clients for Daily Report

Provides clients for:
- Finnhub: Real-time stock prices, company info, analyst recommendations
- Alpha Vantage: Technical indicators, historical data
- Tavily: News search, market insights
"""

import os
import requests
from typing import Optional, Dict, List, Any
from datetime import datetime, timedelta
from pathlib import Path
import logging

from dotenv import load_dotenv

# Load credentials from project root .env
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)

logger = logging.getLogger(__name__)

# Environment variable names for API keys
ENV_KEYS = {
    "finnhub": "FINNHUB_KEY",
    "alphavantage": "ALPHAVANTAGE_KEY",
    "tavily": "TAVILY_KEY",
}


def _resolve_api_key(config_key: Optional[str], env_name: str) -> Optional[str]:
    """Resolve API key: env var takes priority over config value."""
    return os.environ.get(env_name) or config_key


class FinnhubClient:
    """
    Finnhub API Client
    Docs: https://finnhub.io/docs/api

    Free tier: 60 calls/minute
    """

    BASE_URL = "https://finnhub.io/api/v1"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = _resolve_api_key(api_key, ENV_KEYS["finnhub"])
        self.enabled = bool(self.api_key)

    def _request(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        """Make authenticated request to Finnhub API"""
        if not self.enabled:
            return None

        try:
            params = params or {}
            params["token"] = self.api_key
            response = requests.get(f"{self.BASE_URL}/{endpoint}", params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.warning(f"Finnhub API error ({endpoint}): {e}")
            return None

    def get_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get real-time quote for a stock

        Returns:
            {
                "price": float,
                "change": float,
                "change_percent": float,
                "high": float,
                "low": float,
                "open": float,
                "previous_close": float,
                "timestamp": int
            }
        """
        data = self._request("quote", {"symbol": symbol})
        if not data or data.get("c") == 0:
            return None

        return {
            "price": data.get("c", 0),  # Current price
            "change": data.get("d", 0),  # Change
            "change_percent": data.get("dp", 0),  # Percent change
            "high": data.get("h", 0),  # High price of the day
            "low": data.get("l", 0),  # Low price of the day
            "open": data.get("o", 0),  # Open price
            "previous_close": data.get("pc", 0),  # Previous close
            "timestamp": data.get("t", 0)  # Timestamp
        }

    def get_recommendation(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get analyst recommendation trends

        Returns latest recommendation:
            {
                "buy": int,
                "hold": int,
                "sell": int,
                "strong_buy": int,
                "strong_sell": int,
                "period": str
            }
        """
        data = self._request("stock/recommendation", {"symbol": symbol})
        if not data or len(data) == 0:
            return None

        # Get the latest recommendation
        latest = data[0]
        return {
            "buy": latest.get("buy", 0),
            "hold": latest.get("hold", 0),
            "sell": latest.get("sell", 0),
            "strong_buy": latest.get("strongBuy", 0),
            "strong_sell": latest.get("strongSell", 0),
            "period": latest.get("period", "")
        }

    def get_price_target(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get price target from analysts

        Returns:
            {
                "target_high": float,
                "target_low": float,
                "target_mean": float,
                "target_median": float,
                "number_of_analysts": int
            }
        """
        data = self._request("stock/price-target", {"symbol": symbol})
        if not data:
            return None

        return {
            "target_high": data.get("targetHigh", 0),
            "target_low": data.get("targetLow", 0),
            "target_mean": data.get("targetMean", 0),
            "target_median": data.get("targetMedian", 0),
            "number_of_analysts": data.get("numberOfAnalysts", 0)
        }

    def get_company_news(self, symbol: str, days: int = 7) -> Optional[List[Dict[str, Any]]]:
        """
        Get company news

        Returns list of:
            {
                "headline": str,
                "summary": str,
                "source": str,
                "url": str,
                "datetime": datetime,
                "image": str
            }
        """
        today = datetime.now()
        from_date = (today - timedelta(days=days)).strftime("%Y-%m-%d")
        to_date = today.strftime("%Y-%m-%d")

        data = self._request("company-news", {
            "symbol": symbol,
            "from": from_date,
            "to": to_date
        })

        if not data:
            return None

        news_items = []
        for item in data[:10]:  # Limit to 10 items
            news_items.append({
                "headline": item.get("headline", ""),
                "summary": item.get("summary", ""),
                "source": item.get("source", ""),
                "url": item.get("url", ""),
                "datetime": datetime.fromtimestamp(item.get("datetime", 0)),
                "image": item.get("image", "")
            })

        return news_items

    def get_market_news(self, category: str = "general") -> Optional[List[Dict[str, Any]]]:
        """
        Get market news by category

        Categories: general, forex, crypto, merger

        Returns list of news items
        """
        data = self._request("news", {"category": category})

        if not data:
            return None

        news_items = []
        for item in data[:10]:
            news_items.append({
                "headline": item.get("headline", ""),
                "summary": item.get("summary", ""),
                "source": item.get("source", ""),
                "url": item.get("url", ""),
                "datetime": datetime.fromtimestamp(item.get("datetime", 0)),
                "image": item.get("image", "")
            })

        return news_items


class AlphaVantageClient:
    """
    Alpha Vantage API Client
    Docs: https://www.alphavantage.co/documentation/

    Free tier: 25 calls/day, 5 calls/minute
    """

    BASE_URL = "https://www.alphavantage.co/query"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = _resolve_api_key(api_key, ENV_KEYS["alphavantage"])
        self.enabled = bool(self.api_key)

    def _request(self, params: Dict) -> Optional[Dict]:
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

    def get_daily_prices(self, symbol: str, outputsize: str = "compact") -> Optional[Dict[str, Any]]:
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

    def get_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
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

    def get_sma(self, symbol: str, interval: str = "daily", time_period: int = 20) -> Optional[Dict[str, Any]]:
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

    def get_rsi(self, symbol: str, interval: str = "daily", time_period: int = 14) -> Optional[Dict[str, Any]]:
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

    def get_news_sentiment(self, tickers: str = None, limit: int = 50) -> Optional[List[Dict[str, Any]]]:
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


class TavilyClient:
    """
    Tavily Search API Client
    Docs: https://docs.tavily.com/

    Free tier: 1000 calls/month
    """

    BASE_URL = "https://api.tavily.com"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = _resolve_api_key(api_key, ENV_KEYS["tavily"])
        self.enabled = bool(self.api_key)

    def _request(self, payload: Dict) -> Optional[Dict]:
        """Make authenticated request to Tavily API"""
        if not self.enabled:
            return None

        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }
            response = requests.post(
                f"{self.BASE_URL}/search",
                json=payload,
                headers=headers,
                timeout=30
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.warning(f"Tavily API error: {e}")
            return None

    def search_news(self, query: str, max_results: int = 10, days: int = 7) -> Optional[List[Dict[str, Any]]]:
        """
        Search for news articles

        Args:
            query: Search query
            max_results: Maximum number of results
            days: Number of days to look back

        Returns:
            [
                {
                    "title": str,
                    "url": str,
                    "content": str,
                    "score": float,
                    "published_date": str
                },
                ...
            ]
        """
        payload = {
            "query": query,
            "search_depth": "basic",
            "max_results": max_results,
            "include_raw_content": False,
            "topic": "news",
            "days": days
        }

        data = self._request(payload)

        if not data or "results" not in data:
            return None

        results = []
        for item in data["results"]:
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "content": item.get("content", ""),
                "score": item.get("score", 0),
                "published_date": item.get("published_date", "")
            })

        return results

    def search_market_news(
        self,
        markets: List[str] = None,
        industries: List[str] = None,
        max_results: int = 10
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Search for market and industry news

        Args:
            markets: List of markets (cn, us, kr)
            industries: List of industries to filter
            max_results: Maximum number of results

        Returns:
            List of news items with market/industry tags
        """
        # Build search query
        query_parts = []

        if industries:
            industry_map = {
                "semiconductor_ai": "semiconductor OR AI chip OR GPU",
                "aerospace_defense": "aerospace OR defense OR military",
                "machinery": "machinery OR manufacturing equipment",
                "education": "education OR edtech"
            }
            for ind in industries:
                if ind in industry_map:
                    query_parts.append(f"({industry_map[ind]})")

        if markets:
            market_map = {
                "cn": "China OR Chinese",
                "us": "US OR American OR Wall Street",
                "kr": "Korea OR Korean OR KOSPI"
            }
            market_terms = [market_map.get(m, "") for m in markets if m in market_map]
            if market_terms:
                query_parts.append(f"({' OR '.join(market_terms)})")

        query = " AND ".join(query_parts) if query_parts else "stock market news"

        # Add date for freshness
        today = datetime.now()
        query += f" {today.strftime('%B %Y')}"

        return self.search_news(query, max_results)


# Convenience function to check if any API is available
class YFinanceClient:
    """
    yfinance API Client

    No API key needed. Best for US stocks, partial support for KR (.KS/.KQ).
    Provides: prices, analyst targets, upgrades/downgrades, EPS, insider trades.
    """

    def __init__(self):
        try:
            import yfinance
            self._yf = yfinance
            self.enabled = True
        except ImportError:
            self._yf = None
            self.enabled = False

    def _ticker(self, symbol: str):
        return self._yf.Ticker(symbol)

    # ==================== Price ====================

    def get_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get current price and basic info via fast_info + history."""
        if not self.enabled:
            return None
        try:
            t = self._ticker(symbol)
            fi = t.fast_info
            current = float(fi.last_price) if fi.last_price else None
            if not current:
                return None
            prev = float(fi.previous_close) if fi.previous_close else current
            change_pct = ((current - prev) / prev) * 100 if prev else 0
            return {
                "price": current,
                "previous_close": prev,
                "change": round(current - prev, 4),
                "change_percent": round(change_pct, 2),
                "day_high": float(fi.day_high) if fi.day_high else None,
                "day_low": float(fi.day_low) if fi.day_low else None,
                "volume": int(fi.last_volume) if fi.last_volume else None,
                "market_cap": float(fi.market_cap) if fi.market_cap else None,
                "source": "yfinance",
            }
        except Exception as e:
            logger.warning(f"yfinance quote error ({symbol}): {e}")
            return None

    def get_index_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get index quote (e.g., ^GSPC, ^KS11)."""
        return self.get_quote(symbol)

    # ==================== Analyst ====================

    def get_price_targets(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get analyst price targets {current, low, high, mean, median}."""
        if not self.enabled:
            return None
        try:
            t = self._ticker(symbol)
            targets = t.analyst_price_targets
            if not targets or not targets.get("mean"):
                return None
            return {
                "current": targets.get("current"),
                "low": targets.get("low"),
                "high": targets.get("high"),
                "mean": targets.get("mean"),
                "median": targets.get("median"),
                "source": "yfinance",
            }
        except Exception as e:
            logger.warning(f"yfinance price_targets error ({symbol}): {e}")
            return None

    def get_upgrades_downgrades(self, symbol: str, limit: int = 10) -> Optional[List[Dict[str, Any]]]:
        """Get analyst upgrade/downgrade history (last 30 days)."""
        if not self.enabled:
            return None
        try:
            t = self._ticker(symbol)
            df = t.upgrades_downgrades
            if df is None or df.empty:
                return None
            # Filter to last 30 days
            cutoff = datetime.now() - timedelta(days=30)
            df = df[df.index >= cutoff]
            if df.empty:
                return None
            results = []
            for date, row in df.head(limit).iterrows():
                results.append({
                    "firm": row.get("Firm", ""),
                    "to_grade": row.get("ToGrade", ""),
                    "from_grade": row.get("FromGrade", ""),
                    "action": row.get("Action", ""),
                    "price_target": row.get("currentPriceTarget"),
                    "date": date.strftime("%Y-%m-%d"),
                })
            return results if results else None
        except Exception as e:
            logger.warning(f"yfinance upgrades_downgrades error ({symbol}): {e}")
            return None

    def get_recommendations(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get analyst recommendation distribution."""
        if not self.enabled:
            return None
        try:
            t = self._ticker(symbol)
            df = t.recommendations
            if df is None or df.empty:
                return None
            latest = df.iloc[0]
            return {
                "strong_buy": int(latest.get("strongBuy", 0)),
                "buy": int(latest.get("buy", 0)),
                "hold": int(latest.get("hold", 0)),
                "sell": int(latest.get("sell", 0)),
                "strong_sell": int(latest.get("strongSell", 0)),
                "source": "yfinance",
            }
        except Exception as e:
            logger.warning(f"yfinance recommendations error ({symbol}): {e}")
            return None

    # ==================== Fundamentals ====================

    def get_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get comprehensive stock info (PE, margins, growth, etc.)."""
        if not self.enabled:
            return None
        try:
            t = self._ticker(symbol)
            return t.info
        except Exception as e:
            logger.warning(f"yfinance info error ({symbol}): {e}")
            return None

    def get_earnings_estimate(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get EPS estimates for current/next quarter/year."""
        if not self.enabled:
            return None
        try:
            t = self._ticker(symbol)
            df = t.earnings_estimate
            if df is None or df.empty:
                return None
            result = {}
            for period, row in df.iterrows():
                result[period] = {
                    "avg": float(row.get("avg", 0)),
                    "low": float(row.get("low", 0)),
                    "high": float(row.get("high", 0)),
                    "growth": float(row.get("growth", 0)),
                    "num_analysts": int(row.get("numberOfAnalysts", 0)),
                }
            return result
        except Exception as e:
            logger.warning(f"yfinance earnings_estimate error ({symbol}): {e}")
            return None

    def get_earnings_history(self, symbol: str) -> Optional[List[Dict[str, Any]]]:
        """Get recent earnings history with actual vs estimate."""
        if not self.enabled:
            return None
        try:
            t = self._ticker(symbol)
            df = t.earnings_history
            if df is None or df.empty:
                return None
            results = []
            for date, row in df.iterrows():
                results.append({
                    "quarter": str(date.date()) if hasattr(date, "date") else str(date),
                    "eps_actual": float(row.get("epsActual", 0)),
                    "eps_estimate": float(row.get("epsEstimate", 0)),
                    "surprise_pct": float(row.get("surprisePercent", 0)),
                })
            return results
        except Exception as e:
            logger.warning(f"yfinance earnings_history error ({symbol}): {e}")
            return None

    def get_insider_transactions(self, symbol: str, limit: int = 10) -> Optional[List[Dict[str, Any]]]:
        """Get recent insider transactions (last 90 days)."""
        if not self.enabled:
            return None
        try:
            t = self._ticker(symbol)
            df = t.insider_transactions
            if df is None or df.empty:
                return None
            # Filter to last 90 days using Start Date column
            if 'Start Date' in df.columns:
                cutoff = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
                df['_date_str'] = df['Start Date'].astype(str).str[:10]
                df = df[df['_date_str'] >= cutoff]
                df = df.drop(columns=['_date_str'])
                if df.empty:
                    return None
            results = []
            for idx, row in df.head(limit * 2).iterrows():
                # Extract action from Text field (e.g. "Sale at price ...")
                text = row.get("Text", "")
                if "Buy" in str(text):
                    action = "Buy"
                elif "Sale" in str(text):
                    action = "Sale"
                else:
                    action = row.get("Transaction", "") or ""
                # Skip records with no action info
                if not action:
                    continue
                # Date: keep only date part
                date_str = str(row.get("Start Date", ""))[:10]
                results.append({
                    "insider": row.get("Insider", ""),
                    "position": row.get("Position", ""),
                    "shares": int(row.get("Shares", 0)),
                    "value": float(row.get("Value", 0)) if row.get("Value") else None,
                    "transaction": action,
                    "date": date_str,
                    "text": text,
                })
                if len(results) >= limit:
                    break
            return results if results else None
        except Exception as e:
            logger.warning(f"yfinance insider_transactions error ({symbol}): {e}")
            return None

    def get_history(self, symbol: str, period: str = "6mo") -> Optional[Any]:
        """
        Get historical OHLCV data.

        Args:
            symbol: Stock symbol
            period: "1d", "1mo", "3mo", "6mo", "1y", "2y", "3y"

        Returns:
            pandas DataFrame with columns: Open, High, Low, Close, Volume
        """
        if not self.enabled:
            return None
        try:
            t = self._ticker(symbol)
            df = t.history(period=period)
            if df is None or df.empty:
                return None
            return df
        except Exception as e:
            logger.warning(f"yfinance history error ({symbol}): {e}")
            return None


def get_available_apis(config: Dict) -> Dict[str, bool]:
    """
    Check which APIs are configured and available

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
