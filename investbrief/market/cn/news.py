"""A股新闻获取模块。"""

import logging
from typing import Any
from urllib.parse import urlparse

from investbrief.datasources.tavily import TavilyClient

logger = logging.getLogger(__name__)


_MACRO_NEWS_QUERY = "中国 A股 股市 宏观经济 央行 货币政策"


def fetch_cn_macro_news(limit: int = 20) -> list[dict[str, Any]]:
    """宏观/市场头条新闻(宏观邮件「重要新闻」用)。复用 Tavily search_news。

    Tavily disabled / 失败 → [](render 降级为空,不阻塞)。返回字段对齐
    mail.render.build_news_html 的消费键:title / summary / url / time / source。
    """
    client = TavilyClient()
    if not client.enabled:
        return []
    try:
        results = client.search_news(query=_MACRO_NEWS_QUERY, max_results=limit, days=3)
    except Exception as e:
        logger.warning(f"cn macro news failed: {e}")
        return []
    if not results:
        return []
    out: list[dict[str, Any]] = []
    for r in results:
        url = r.get("url", "")
        out.append({
            "title": r.get("title", ""),
            "summary": (r.get("content") or "")[:200],
            "url": url,
            "time": (r.get("published_date") or "")[:10],
            "source": urlparse(url).netloc.replace("www.", "") or "综合",
        })
    return out[:limit]
