"""Sell-side market-views aggregator for the email report.

Fetches the last 7 days' market commentary from a curated set of reputable
sell-side firms via Tavily news search (whitelisted outlets, title-based
attribution), dedups by URL, tags each item by market (美股 / A股·中国 /
全球其他), and returns structured items for Claude to synthesize into the
email section.

Design notes:
- Whitelist-only sourcing (Reuters/Bloomberg/CNBC/FT/WSJ/MarketWatch/Barron's +
  CN: 新浪/华尔街见闻/财新/第一财经 + KR: Korea Herald/Times): accuracy first.
- Title-based attribution: a firm is tagged only if it appears in the article
  TITLE (the subject), never just mentioned in body — filters roundup pages.
- CN brokers (中信/华泰/申万) are out of scope: their views aren't in any free
  feed (verified). Designated firms are all Western sell-side.
"""
from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger(__name__)

TAVILY_URL = "https://api.tavily.com/search"
DAYS = 7
MAX_RESULTS_PER_FIRM = 6

# Reputable financial outlets only (accuracy-first). Western + CN + KR.
INCLUDE_DOMAINS: list[str] = [
    # Western
    "reuters.com", "bloomberg.com", "cnbc.com", "ft.com",
    "wsj.com", "marketwatch.com", "barrons.com",
    # CN (authoritative financial media)
    "sina.com.cn", "wallstreetcn.com", "caixin.com", "yicai.com",
    # KR
    "koreaherald.com", "koreatimes.co.kr",
]

# Designated sell-side firms (reputable, frequent market-strategy commentary).
# Each: (canonical, [title-match name variants], Tavily search subject).
INSTITUTIONS: list[tuple[str, list[str], str]] = [
    ("JPMorgan", ["JPMorgan", "J.P. Morgan", "摩根大通"], "JPMorgan market outlook strategy stocks"),
    ("Morgan Stanley", ["Morgan Stanley", "摩根士丹利"], "Morgan Stanley market outlook strategy stocks"),
    ("Goldman Sachs", ["Goldman Sachs", "高盛"], "Goldman Sachs market outlook strategy stocks"),
    ("Citi", ["Citi", "Citigroup", "花旗"], "Citi market outlook strategy stocks"),
    ("Bank of America", ["Bank of America", "BofA", "美国银行"], "Bank of America market strategy stocks"),
    ("UBS", ["UBS", "瑞银"], "UBS market outlook strategy stocks"),
    ("Barclays", ["Barclays", "巴克莱"], "Barclays market outlook strategy stocks"),
    ("Jefferies", ["Jefferies"], "Jefferies market outlook strategy stocks"),
    ("Wells Fargo", ["Wells Fargo", "富国"], "Wells Fargo market outlook strategy stocks"),
    ("BMO Capital", ["BMO Capital", "BMO"], "BMO Capital Markets market outlook stocks"),
    ("Evercore ISI", ["Evercore"], "Evercore ISI market outlook strategy stocks"),
    ("Oppenheimer", ["Oppenheimer"], "Oppenheimer market outlook strategy stocks"),
    ("Yardeni Research", ["Yardeni"], "Yardeni Research market outlook stocks"),
]

# Market tagging from title + content. Items matching none -> "全球其他".
MARKET_KEYWORDS: dict[str, list[str]] = {
    "us": ["s&p 500", "s&p", "nasdaq", "dow jones", "dow jones", "us stock",
           "us equit", "美股", "标普", "纳指", "纳斯达克", "道指", "美国股市"],
    "cn": ["a-share", "a股", "上证", "沪深300", "沪深", "深证", "创业板", "科创板",
           "中国股市", "china stock", "china equit", "csi 300", "csi300"],
    "kr": ["kospi", "kosdaq", "korea stock", "korean stock", "korea equit",
           "韩股", "韩国股市"],
}


def _tag_market(blob_lower: str) -> list[str]:
    return [m for m, kws in MARKET_KEYWORDS.items() if any(k in blob_lower for k in kws)]


def _firms_in_title(title_lower: str) -> list[str]:
    return [c for c, aliases, _ in INSTITUTIONS
            if any(a.lower() in title_lower for a in aliases)]


def _default_search(subject: str, *, api_key: str, session: requests.Session,
                    days: int = DAYS, max_results: int = MAX_RESULTS_PER_FIRM,
                    retries: int = 2) -> list[dict]:
    """One Tavily news query. Returns raw Tavily `results` list. Raises on failure."""
    payload = {
        "api_key": api_key,
        "query": subject,
        "topic": "news",
        "search_depth": "basic",
        "include_answer": False,
        "days": days,
        "max_results": max_results,
        "include_domains": INCLUDE_DOMAINS,
    }
    last_exc: Exception | None = None
    for _ in range(retries + 1):
        try:
            resp = session.post(TAVILY_URL, json=payload, timeout=30)
            resp.raise_for_status()
            return resp.json().get("results", []) or []
        except Exception as e:  # noqa: BLE001 — retry transient net/SSL errors
            last_exc = e
    raise last_exc or RuntimeError("tavily returned no data")


def fetch_research_views(*, api_key: str | None = None) -> list[dict]:
    """Fetch last-7-day sell-side market views across designated firms.

    Resilient: per-firm failures are logged + skipped. Returns [] if no key.
    Items: {firms: [canonical...], markets: [us|cn|kr...], title, url, date, snippet}.
    Deduped by URL; a firm is tagged only if it appears in the title.
    """
    api_key = api_key or os.environ.get("TAVILY_KEY")
    if not api_key:
        logger.warning("TAVILY_KEY missing — research-views skipped")
        return []

    by_url: dict[str, dict] = {}
    session = requests.Session()
    try:
        for canonical, _aliases, subject in INSTITUTIONS:
            try:
                results = _default_search(subject, api_key=api_key, session=session)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"research-views: {canonical} failed: {e}")
                continue
            for r in results:
                url = r.get("url", "")
                if url and url not in by_url:
                    by_url[url] = r
    finally:
        session.close()

    items: list[dict] = []
    for url, r in by_url.items():
        title = r.get("title", "")
        firms = _firms_in_title(title.lower())
        if not firms:
            continue  # no designated firm in title -> drop (attribution accuracy)
        content = r.get("content", "")
        items.append({
            "firms": firms,
            "markets": _tag_market(f"{title} {content}".lower()),
            "title": title,
            "url": url,
            "date": (r.get("published_date") or "")[:16],
            "snippet": (content or "")[:300],
        })
    return items
