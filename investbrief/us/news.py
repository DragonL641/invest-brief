"""
Data Provider - Unified Data Fetching Layer

Provides a unified interface for fetching stock data with fallback priorities:
1. External APIs (Finnhub, Alpha Vantage, Tavily)
2. Claude WebSearch (fallback)
"""

import logging
from typing import Optional, Dict, List, Any
from datetime import datetime

from .clients import (
    FinnhubClient,
    AlphaVantageClient,
    TavilyClient,
    get_available_apis
)

logger = logging.getLogger(__name__)


class DataProvider:
    """
    Unified data provider with fallback support

    Priority for stock prices:
        Finnhub > Alpha Vantage > WebSearch

    Priority for news:
        Tavily > WebSearch

    Priority for analyst recommendations:
        Finnhub > WebSearch
    """

    def __init__(self, config: Dict):
        """
        Initialize DataProvider with configuration

        Args:
            config: Full config dict containing api_keys section
        """
        api_keys = config.get("api_keys", {})

        self.finnhub = FinnhubClient(api_keys.get("finnhub"))
        self.alphavantage = AlphaVantageClient(api_keys.get("alphavantage"))
        self.tavily = TavilyClient(api_keys.get("tavily"))

        # Track which APIs are available
        self.available_apis = get_available_apis(config)

        logger.info(f"DataProvider initialized. Available APIs: {self.available_apis}")

    # ==================== Stock Price Methods ====================

    def get_stock_price(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get stock price with fallback priority

        Priority: Finnhub > Alpha Vantage > None (caller should use WebSearch)

        Args:
            symbol: Stock symbol (e.g., "AMD", "NVDA")

        Returns:
            {
                "symbol": str,
                "price": float,
                "change": float,
                "change_percent": float,
                "source": str  # "finnhub", "alphavantage", or None
            }
        """
        # Try Finnhub first
        if self.finnhub.enabled:
            quote = self.finnhub.get_quote(symbol)
            if quote and quote.get("price", 0) > 0:
                return {
                    "symbol": symbol,
                    "price": quote["price"],
                    "change": quote["change"],
                    "change_percent": quote["change_percent"],
                    "high": quote.get("high"),
                    "low": quote.get("low"),
                    "open": quote.get("open"),
                    "previous_close": quote.get("previous_close"),
                    "source": "finnhub"
                }

        # Try Alpha Vantage
        if self.alphavantage.enabled:
            quote = self.alphavantage.get_quote(symbol)
            if quote and quote.get("price", 0) > 0:
                return {
                    "symbol": symbol,
                    "price": quote["price"],
                    "change": quote["change"],
                    "change_percent": float(quote.get("change_percent", "0").replace("%", "")),
                    "high": quote.get("high"),
                    "low": quote.get("low"),
                    "open": quote.get("open"),
                    "previous_close": quote.get("previous_close"),
                    "source": "alphavantage"
                }

        # No API available - caller should use WebSearch
        logger.info(f"No API available for stock price: {symbol}")
        return None

    def get_stock_prices(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Get prices for multiple stocks

        Args:
            symbols: List of stock symbols

        Returns:
            Dict mapping symbol to price data
        """
        results = {}
        for symbol in symbols:
            price_data = self.get_stock_price(symbol)
            if price_data:
                results[symbol] = price_data
        return results

    # ==================== Technical Indicators ====================

    def get_technical_indicators(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get technical indicators (SMA, RSI)

        Uses Alpha Vantage only

        Returns:
            {
                "symbol": str,
                "sma_20": float,
                "sma_50": float,
                "rsi_14": float,
                "source": str
            }
        """
        if not self.alphavantage.enabled:
            return None

        result = {"symbol": symbol, "source": "alphavantage"}

        # Get SMA 20
        sma_20 = self.alphavantage.get_sma(symbol, time_period=20)
        if sma_20 and sma_20.get("values"):
            result["sma_20"] = sma_20["values"][0]["sma"]

        # Get SMA 50
        sma_50 = self.alphavantage.get_sma(symbol, time_period=50)
        if sma_50 and sma_50.get("values"):
            result["sma_50"] = sma_50["values"][0]["sma"]

        # Get RSI
        rsi = self.alphavantage.get_rsi(symbol, time_period=14)
        if rsi and rsi.get("values"):
            result["rsi_14"] = rsi["values"][0]["rsi"]

        if len(result) > 2:  # Has at least one indicator
            return result

        return None

    # ==================== Analyst Recommendations ====================

    def get_analyst_recommendation(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get analyst recommendations

        Priority: Finnhub > None (caller should use WebSearch)

        Returns:
            {
                "symbol": str,
                "buy": int,
                "hold": int,
                "sell": int,
                "strong_buy": int,
                "strong_sell": int,
                "consensus": str,  # "buy", "hold", "sell"
                "source": str
            }
        """
        if not self.finnhub.enabled:
            return None

        rec = self.finnhub.get_recommendation(symbol)
        if not rec:
            return None

        # Calculate consensus
        total = rec["buy"] + rec["hold"] + rec["sell"] + rec["strong_buy"] + rec["strong_sell"]
        if total == 0:
            consensus = "hold"
        else:
            buy_score = rec["strong_buy"] * 2 + rec["buy"]
            sell_score = rec["strong_sell"] * 2 + rec["sell"]
            if buy_score > sell_score * 1.5:
                consensus = "buy"
            elif sell_score > buy_score * 1.5:
                consensus = "sell"
            else:
                consensus = "hold"

        return {
            "symbol": symbol,
            "buy": rec["buy"],
            "hold": rec["hold"],
            "sell": rec["sell"],
            "strong_buy": rec["strong_buy"],
            "strong_sell": rec["strong_sell"],
            "consensus": consensus,
            "period": rec.get("period"),
            "source": "finnhub"
        }

    def get_price_target(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get analyst price target

        Returns:
            {
                "symbol": str,
                "target_high": float,
                "target_low": float,
                "target_mean": float,
                "target_median": float,
                "number_of_analysts": int,
                "source": str
            }
        """
        if not self.finnhub.enabled:
            return None

        target = self.finnhub.get_price_target(symbol)
        if not target:
            return None

        return {
            "symbol": symbol,
            "target_high": target["target_high"],
            "target_low": target["target_low"],
            "target_mean": target["target_mean"],
            "target_median": target["target_median"],
            "number_of_analysts": target["number_of_analysts"],
            "source": "finnhub"
        }

    # ==================== News Methods ====================

    def get_market_news(self, market: str = "general", max_results: int = 10) -> Optional[List[Dict[str, Any]]]:
        """
        Get general market news

        Priority: Tavily > Finnhub > None

        Args:
            market: "general", "us", "cn", "kr"
            max_results: Maximum number of results

        Returns:
            List of news items
        """
        # Try Tavily first
        if self.tavily.enabled:
            market_queries = {
                "general": "stock market financial news",
                "us": "US stock market Wall Street news",
                "cn": "China stock market A-shares news",
                "kr": "Korea stock market KOSPI news"
            }
            query = market_queries.get(market, "stock market news")
            query += f" {datetime.now().strftime('%B %Y')}"

            news = self.tavily.search_news(query, max_results=max_results)
            if news:
                return news

        # Try Finnhub
        if self.finnhub.enabled:
            category_map = {
                "general": "general",
                "us": "general",
                "cn": "general",
                "kr": "general"
            }
            news = self.finnhub.get_market_news(category_map.get(market, "general"))
            if news:
                return news[:max_results]

        return None

    def get_company_news(self, symbol: str, days: int = 7) -> Optional[List[Dict[str, Any]]]:
        """
        Get news for a specific company

        Priority: Finnhub > Tavily > None

        Args:
            symbol: Stock symbol
            days: Number of days to look back

        Returns:
            List of news items
        """
        # Try Finnhub first for company-specific news
        if self.finnhub.enabled:
            news = self.finnhub.get_company_news(symbol, days)
            if news:
                return news

        # Try Tavily
        if self.tavily.enabled:
            query = f"{symbol} stock news {datetime.now().strftime('%B %Y')}"
            news = self.tavily.search_news(query, max_results=10, days=days)
            if news:
                return news

        return None

    def search_news(
        self,
        query: str,
        markets: List[str] = None,
        industries: List[str] = None,
        max_results: int = 10
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Search for news with custom query

        Priority: Tavily > None

        Args:
            query: Search query
            markets: List of markets to filter
            industries: List of industries to filter
            max_results: Maximum number of results

        Returns:
            List of news items
        """
        if not self.tavily.enabled:
            return None

        # If markets or industries specified, use specialized search
        if markets or industries:
            return self.tavily.search_market_news(
                markets=markets,
                industries=industries,
                max_results=max_results
            )

        # Otherwise use direct search
        return self.tavily.search_news(query, max_results=max_results)

    # ==================== Market Indices ====================

    def get_market_indices(self) -> Optional[Dict[str, Dict[str, Any]]]:
        """
        Get major market indices prices

        Returns:
            {
                "sp500": {"price": float, "change": float, ...},
                "nasdaq": {...},
                "dow": {...},
                "vix": {...},
                "shanghai": {...},
                "shenzhen": {...},
                "kospi": {...},
                "kosdaq": {...}
            }
        """
        indices_symbols = {
            "sp500": "^GSPC",
            "nasdaq": "^IXIC",
            "dow": "^DJI",
            "vix": "^VIX",
        }

        results = {}
        for name, symbol in indices_symbols.items():
            price = self.get_stock_price(symbol)
            if price:
                results[name] = price

        return results if results else None

    # ==================== News Methods (Unified) ====================

    def get_financial_news(self, tickers: List[str] = None, limit: int = 50,
                           user_tickers: List[str] = None, industries: List[str] = None) -> List[Dict[str, Any]]:
        """
        Get financial news with scoring and sorting.

        Priority: Tavily industry search → Alpha Vantage (with tickers) → Finnhub

        Args:
            tickers: Ticker symbols to filter news (from holdings union)
            limit: Maximum number of results
            user_tickers: User's actual holdings for relevance scoring
            industries: Industry list for topic-based filtering

        Returns:
            Sorted list of news items (within 7 days, scored)
        """
        news = []

        # 1. Tavily industry search (highest quality, industry-relevant)
        if self.tavily.enabled and industries:
            tavily_news = self.tavily.search_market_news(industries=industries, max_results=limit)
            if tavily_news:
                for item in tavily_news:
                    # Extract domain as source
                    url = item.get("url", "")
                    source = url.split("/")[2] if "/" in url else ""
                    news.append({
                        "title": item.get("title", ""),
                        "summary": item.get("content", ""),
                        "url": item.get("url", ""),
                        "source": source,
                        "time": "",
                        "published_at": self._parse_tavily_date(item.get("published_date")),
                        "sentiment": "Neutral",
                        "sentiment_score": 0.5,
                        "tickers": []
                    })

        # 2. Alpha Vantage with ticker filter (supplement)
        if len(news) < limit and self.alphavantage.enabled:
            result = self.alphavantage.get_news_sentiment(
                tickers=",".join(tickers) if tickers else None,
                limit=limit
            )
            if result:
                news.extend(result)

        # 3. Fallback to Finnhub
        if not news and self.finnhub.enabled:
            result = self.finnhub.get_market_news("general")
            if result:
                # Normalize Finnhub format to match Alpha Vantage format
                for item in result[:limit]:
                    news.append({
                        "title": item.get("headline", ""),
                        "summary": item.get("summary", ""),
                        "url": item.get("url", ""),
                        "source": item.get("source", ""),
                        "time": "",
                        "published_at": item.get("datetime"),
                        "sentiment": "Neutral",
                        "sentiment_score": 0.5,
                        "tickers": []
                    })

        # Filter to 7 days
        news = self._filter_recent(news, days=7)

        # Score and sort
        news = self._score_and_sort_news(news, user_tickers or [])

        return news[:limit]

    def _parse_tavily_date(self, date_str: str) -> Optional[datetime]:
        """Parse Tavily published_date string to datetime"""
        if not date_str:
            return None
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ",
                    "%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S"):
            try:
                return datetime.strptime(date_str, fmt)
            except (ValueError, TypeError):
                continue
        # Try stripping timezone suffix
        try:
            return datetime.strptime(date_str.split(" GMT")[0] if " GMT" in date_str else date_str,
                                     "%a, %d %b %Y %H:%M:%S")
        except (ValueError, TypeError):
            return None

    def _filter_recent(self, news: List[Dict], days: int = 7) -> List[Dict]:
        """Filter news to only include items within N days"""
        from datetime import timedelta
        cutoff = datetime.now() - timedelta(days=days)
        filtered = []
        for item in news:
            published = item.get("published_at")
            if published is None:
                continue
            # Handle both datetime objects and other types
            if isinstance(published, datetime) and published >= cutoff:
                filtered.append(item)
        return filtered

    def _score_and_sort_news(self, news: List[Dict], user_tickers: List[str]) -> List[Dict]:
        """
        Score each news item and sort by composite score.

        Score = time*0.25 + sentiment*0.1 + relevance*0.4 + source*0.25
        """
        now = datetime.now()
        user_ticker_set = set(user_tickers)

        # Related tickers in same industries
        related_tickers = {
            "AMD", "NVDA", "MU", "TSLA", "INTC", "AVGO", "QCOM", "ARM",
            "TSM", "ASML", "AMAT", "KLAC", "LRCX", "NXPI", "MRVL",
            "005930.KS", "000660.KS"  # Samsung, SK Hynix
        }

        # Source quality lists
        quality_sources = {"reuters", "bloomberg", "cnbc", "marketwatch", "wsj",
                           "barrons", "seeking alpha", "yahoo finance", "investing.com"}
        spam_sources = {"ad hoc news", "markets mojo"}

        for item in news:
            # === Time score ===
            published = item.get("published_at")
            if published and isinstance(published, datetime):
                hours_ago = (now - published).total_seconds() / 3600
                item["time_score"] = max(0, 1 - hours_ago / (7 * 24))
                # Generate relative time if missing
                if not item.get("time"):
                    if hours_ago < 1:
                        item["time"] = f"{int(hours_ago * 60)}分钟前"
                    elif hours_ago < 24:
                        item["time"] = f"{int(hours_ago)}小时前"
                    elif hours_ago < 48:
                        item["time"] = "昨天"
                    else:
                        item["time"] = f"{int(hours_ago / 24)}天前"
            else:
                item["time_score"] = 0

            # === Sentiment score ===
            sentiment = item.get("sentiment", "Neutral")
            sentiment_map = {
                "Bullish": 1.0,
                "Somewhat-Bullish": 0.75,
                "Neutral": 0.5,
                "Somewhat-Bearish": 0.25,
                "Bearish": 0.0
            }
            item["sentiment_score_norm"] = sentiment_map.get(sentiment, 0.5)

            # === Relevance score ===
            item_tickers = set(item.get("tickers", []))
            if item_tickers & user_ticker_set:
                item["relevance_score"] = 1.0
            elif item_tickers & related_tickers:
                item["relevance_score"] = 0.5
            else:
                item["relevance_score"] = 0.2

            # === Source quality score ===
            source_lower = (item.get("source", "") or "").lower()
            if any(s in source_lower for s in quality_sources):
                item["source_score"] = 1.0
            elif any(s in source_lower for s in spam_sources):
                item["source_score"] = 0.1
            else:
                item["source_score"] = 0.5

            # === Composite score ===
            item["score"] = (
                item["time_score"] * 0.25
                + item["sentiment_score_norm"] * 0.1
                + item["relevance_score"] * 0.4
                + item["source_score"] * 0.25
            )

        # Sort by score descending
        news.sort(key=lambda x: x.get("score", 0), reverse=True)
        return news

    # ==================== Status Methods ====================

    def get_status(self) -> Dict[str, Any]:
        """
        Get status of all data sources

        Returns:
            {
                "finnhub": {"enabled": bool, "status": str},
                "alphavantage": {"enabled": bool, "status": str},
                "tavily": {"enabled": bool, "status": str}
            }
        """
        status = {}

        # Check Finnhub
        if self.finnhub.enabled:
            try:
                # Test with a simple quote
                quote = self.finnhub.get_quote("AAPL")
                status["finnhub"] = {
                    "enabled": True,
                    "status": "ok" if quote and quote.get("price", 0) > 0 else "error"
                }
            except Exception as e:
                status["finnhub"] = {"enabled": True, "status": f"error: {str(e)}"}
        else:
            status["finnhub"] = {"enabled": False, "status": "not_configured"}

        # Check Alpha Vantage
        if self.alphavantage.enabled:
            try:
                quote = self.alphavantage.get_quote("IBM")
                status["alphavantage"] = {
                    "enabled": True,
                    "status": "ok" if quote and quote.get("price", 0) > 0 else "error"
                }
            except Exception as e:
                status["alphavantage"] = {"enabled": True, "status": f"error: {str(e)}"}
        else:
            status["alphavantage"] = {"enabled": False, "status": "not_configured"}

        # Check Tavily
        if self.tavily.enabled:
            try:
                news = self.tavily.search_news("test", max_results=1)
                status["tavily"] = {
                    "enabled": True,
                    "status": "ok" if news is not None else "error"
                }
            except Exception as e:
                status["tavily"] = {"enabled": True, "status": f"error: {str(e)}"}
        else:
            status["tavily"] = {"enabled": False, "status": "not_configured"}

        return status

    def should_use_websearch(self) -> Dict[str, bool]:
        """
        Determine which data types need WebSearch fallback

        Returns:
            {
                "stock_prices": bool,  # True if no API available
                "news": bool,          # True if no API available
                "analyst_recs": bool   # True if no API available
            }
        """
        return {
            "stock_prices": not (self.finnhub.enabled or self.alphavantage.enabled),
            "news": not (self.tavily.enabled or self.finnhub.enabled),
            "analyst_recs": not self.finnhub.enabled
        }


# Convenience function for quick setup
def create_provider(config_path: str = None, config_dict: Dict = None) -> DataProvider:
    """
    Create a DataProvider instance

    Args:
        config_path: Path to config.json
        config_dict: Direct config dict (alternative to config_path)

    Returns:
        DataProvider instance
    """
    if config_dict:
        return DataProvider(config_dict)

    if config_path:
        import json
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        return DataProvider(config)

    raise ValueError("Either config_path or config_dict must be provided")
