"""Tavily Search API Client."""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

from ._common import ENV_KEYS, _resolve_api_key

logger = logging.getLogger(__name__)


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
