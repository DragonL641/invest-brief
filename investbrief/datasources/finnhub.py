"""Finnhub API Client."""
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import requests

from ._common import ENV_KEYS, _resolve_api_key

logger = logging.getLogger(__name__)


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

    def get_recommendation(self, symbol: str, periods: int = 3) -> Optional[Dict[str, Any]]:
        """Get analyst recommendation trend over recent monthly periods.

        Finnhub returns monthly buckets; we compare the latest two to surface
        rating drift (change is the pct-point delta of each bucket's share,
        positive = more bullish this month).

        Returns: {latest, previous, change, periods}
        """
        data = self._request("stock/recommendation", {"symbol": symbol})
        if not data or len(data) == 0:
            return None

        def norm(d):
            return {
                "period": d.get("period", ""),
                "strong_buy": d.get("strongBuy", 0), "buy": d.get("buy", 0),
                "hold": d.get("hold", 0),
                "sell": d.get("sell", 0), "strong_sell": d.get("strongSell", 0),
            }

        buckets = ("strong_buy", "buy", "hold", "sell", "strong_sell")
        normed = [norm(d) for d in data[:periods]]
        latest = normed[0] if normed else None
        previous = normed[1] if len(normed) > 1 else None

        change: Dict[str, float] = {}
        if latest and previous:
            lt_tot = sum(latest.get(k, 0) for k in buckets) or 1
            pv_tot = sum(previous.get(k, 0) for k in buckets) or 1
            for k in buckets:
                change[k] = round(latest.get(k, 0) / lt_tot * 100
                                  - previous.get(k, 0) / pv_tot * 100, 1)

        return {"latest": latest, "previous": previous, "change": change, "periods": normed}

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

    def search_symbol(self, query: str) -> list[dict]:
        """Search for stock symbols matching query."""
        data = self._request("search", {"q": query})
        if not data:
            return []
        return [
            {"symbol": r.get("displaySymbol", ""), "name": r.get("description", "")}
            for r in data.get("result", [])
            if r.get("type") == "Common Stock" and r.get("displaySymbol")
        ][:20]
