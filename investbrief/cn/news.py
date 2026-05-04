"""A股新闻获取模块。"""

import logging
from typing import Any

from .client import AKShareClient

logger = logging.getLogger(__name__)


def fetch_cn_news(tickers: list[str], industries: list[str], limit: int = 20) -> list[dict[str, Any]]:
    """获取 A 股相关新闻。"""
    client = AKShareClient()
    all_news = []
    seen_titles = set()

    for symbol in tickers:
        stock_news = client.get_stock_news(symbol, limit=5)
        for n in stock_news:
            title = n.get("title", "")
            if title and title not in seen_titles:
                seen_titles.add(title)
                all_news.append({
                    "title": title,
                    "summary": n.get("content", "")[:200],
                    "url": n.get("url", ""),
                    "date": n.get("date", ""),
                    "source": n.get("source", ""),
                    "symbol": symbol,
                })

    all_news.sort(key=lambda x: x.get("date", ""), reverse=True)
    return all_news[:limit]
