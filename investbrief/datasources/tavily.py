"""Tavily Search API Client."""
import logging
import time
from typing import Any

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

    def __init__(self, api_key: str | None = None):
        self.api_key = _resolve_api_key(api_key, ENV_KEYS["tavily"])
        self.enabled = bool(self.api_key)

    def _request(self, payload: dict) -> dict | None:
        """Make authenticated request to Tavily API"""
        if not self.enabled:
            return None

        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }
            t0 = time.perf_counter()
            response = requests.post(
                f"{self.BASE_URL}/search",
                json=payload,
                headers=headers,
                timeout=30
            )
            response.raise_for_status()
            data = response.json()
            n_results = len(data.get("results", [])) if isinstance(data, dict) else 0
            logger.info(
                f"tavily ok query={str(payload.get('query', ''))[:40]!r} "
                f"results={n_results} elapsed={(time.perf_counter() - t0) * 1000:.0f}ms"
            )
            return data
        except requests.exceptions.RequestException as e:
            logger.warning(f"Tavily API error: {e}", exc_info=True)
            return None

    def search_news(self, query: str, max_results: int = 10, days: int = 7) -> list[dict[str, Any]] | None:
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
