import logging
import math
import time as _time

from investbrief.web.services.cache import (
    get_cached, set_cached, invalidate, get_last_updated,
    set_last_updated, can_refresh, set_refresh_lock,
    get_section_cached, set_section_cached, invalidate_section,
    can_section_refresh, set_section_refresh_lock,
)
from investbrief.us.industries import US_INDUSTRIES_MIGRATION
from investbrief.cn.industries import CN_INDUSTRIES_MIGRATION

logger = logging.getLogger(__name__)

_MIGRATION_MAP = {**US_INDUSTRIES_MIGRATION, **CN_INDUSTRIES_MIGRATION}


def _migrate_industries(industries: list[str]) -> list[str]:
    """Map old custom industry keys to new official keys."""
    result = []
    for key in industries:
        if key in _MIGRATION_MAP:
            mapped = _MIGRATION_MAP[key]
            if mapped not in result:
                result.append(mapped)
        else:
            result.append(key)
    return result


def _sanitize_floats(obj):
    """Replace NaN/Infinity floats with None so Starlette can serialize to JSON."""
    if isinstance(obj, dict):
        return {k: _sanitize_floats(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_floats(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


def _classify_error(exc: Exception) -> dict:
    """Map an exception to a structured error reason."""
    import asyncio
    if isinstance(exc, asyncio.TimeoutError):
        return {"reason": "timeout", "detail": str(exc)[:200]}
    if isinstance(exc, (ConnectionError, OSError)):
        return {"reason": "network", "detail": str(exc)[:200]}
    msg = str(exc).lower()
    if "rate" in msg and "limit" in msg:
        return {"reason": "rate_limited", "detail": str(exc)[:200]}
    if "401" in msg or "403" in msg or "api key" in msg:
        return {"reason": "auth", "detail": str(exc)[:200]}
    if "429" in msg:
        return {"reason": "rate_limited", "detail": str(exc)[:200]}
    if "api" in msg or "500" in msg or "503" in msg:
        return {"reason": "api_error", "detail": str(exc)[:200]}
    return {"reason": "unknown", "detail": str(exc)[:200]}


def _public_keys(market: str) -> list[str]:
    return list(SECTION_CONFIG.get(market, {}).get("public", {}).keys())


def _private_keys(market: str) -> list[str]:
    return list(SECTION_CONFIG.get(market, {}).get("private", {}).keys())


SECTION_CONFIG = {
    "us": {
        "public": {
            "indices":              {"ttl": 300,   "method": "get_indices"},
            "economic_calendar":    {"ttl": 14400, "method": "get_economic_calendar"},
            "premarket_movers":     {"ttl": 300,   "method": "get_premarket_movers"},
            "earnings_calendar":    {"ttl": 14400, "method": "get_earnings_calendar"},
            "congressional_trades": {"ttl": 14400, "method": "get_congressional_trades"},
        },
        "private": {
            "holdings":             {"ttl": 600,   "method": "get_holdings_data"},
            "recommendations":      {"ttl": 1800,  "method": "get_recommendations"},
        },
    },
    "cn": {
        "public": {
            "indices":              {"ttl": 300,   "method": "get_indices"},
            "economic_calendar":    {"ttl": 14400, "method": "get_economic_calendar"},
            "dragon_tiger":         {"ttl": 3600,  "method": "get_dragon_tiger"},
            "sector_performance":   {"ttl": 1800,  "method": "get_sector_performance"},
        },
        "private": {
            "holdings":             {"ttl": 600,   "method": "get_holdings_data"},
            "recommendations":      {"ttl": 1800,  "method": "get_recommendations"},
        },
    },
}


def _fetch_news(market: str, symbols: list[str], industries: list[str]) -> tuple[list, list]:
    """Fetch news for the given market. Returns (items, errors)."""
    try:
        if market == "cn":
            from investbrief.cn.news import fetch_cn_news
            items = fetch_cn_news(symbols, industries, limit=20)
            for item in items:
                if "date" in item and "time" not in item:
                    item["time"] = item["date"]
            return items, []
        elif market == "us":
            from investbrief.web.config import get_config
            from investbrief.us.news import DataProvider
            config = get_config()
            dp = DataProvider(config)
            items = dp.get_financial_news(
                tickers=symbols, limit=20,
                user_tickers=symbols, industries=industries,
            )
            return items, []
    except Exception as e:
        logger.warning(f"News fetch failed for {market}: {e}", exc_info=True)
        return [], [{"section": "news", **_classify_error(e)}]


def _summarize_news(items: list[dict], language: str, market: str) -> list[dict]:
    """Translate and format news summaries via Claude API.

    Always processes items to produce structured markdown bullet summaries.
    Skips Claude call only if summaries are already in markdown list format.
    """
    source_lang = "Chinese" if market == "cn" else "English"
    target_lang = {"zh-CN": "简体中文", "ko-KR": "한국어", "en": "English"}.get(language, language)
    need_translate = not (source_lang == "Chinese" and language.startswith("zh"))

    import os
    import json
    try:
        from investbrief.web.services.ai_chat import _get_client
        client = _get_client()
        model = os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL", "claude-sonnet-4-6")

        payload = json.dumps(
            [{"title": it.get("title", ""), "summary": it.get("summary", "")} for it in items],
            ensure_ascii=False,
        )

        translate_part = f"将以下新闻从{source_lang}翻译为{target_lang}，并" if need_translate else ""
        prompt = (
            f"{translate_part}将以下新闻摘要提炼为结构化要点。"
            f"返回 JSON 数组，每项含 title 和 summary 字段，顺序不变。"
            f"summary 要求：提炼为 2-3 个要点，用 Markdown 无序列表格式（每行以 \"- \" 开头），"
            f"每个要点简洁（不超过 40 字），避免冗长叙述。"
            f"只输出 JSON 数组，不要其他内容。\n\n{payload}"
        )

        resp = client.messages.create(
            model=model,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )

        translated = json.loads(resp.content[0].text.strip())
        for i, item in enumerate(items):
            if i < len(translated):
                if translated[i].get("title"):
                    item["title"] = translated[i]["title"]
                if translated[i].get("summary"):
                    item["summary"] = translated[i]["summary"]
        return items
    except Exception as e:
        logger.warning(f"News summarization failed: {e}", exc_info=True)
        return items


def _create_provider(market: str):
    if market == "us":
        from investbrief.us.provider import USMarketProvider
        return USMarketProvider()
    elif market == "cn":
        from investbrief.cn.provider import CNMarketProvider
        return CNMarketProvider()
    raise ValueError(f"Unknown market: {market}")


def _fetch_section(redis_client, market: str, section_name: str,
                   provider, uid: str | None = None, **kwargs) -> dict:
    """Fetch one section: check cache -> fetch -> cache result."""
    config = SECTION_CONFIG[market]
    is_private = section_name in config.get("private", {})
    section_cfg = config["private" if is_private else "public"][section_name]
    ttl = section_cfg["ttl"]

    cached = get_section_cached(redis_client, market, section_name, uid)
    if cached is not None:
        return {"data": cached["data"], "status": "cached",
                "updated_at": cached["updated_at"]}

    try:
        data = provider.get_section_data(section_name, **kwargs)
        data = _sanitize_floats(data)
        now = _time.strftime("%Y-%m-%dT%H:%M:%S%z")
        result = {"data": data, "updated_at": now}
        # Only cache if data is non-empty
        if data and data != [] and data != {}:
            set_section_cached(redis_client, market, section_name, result, ttl, uid)
        return {"data": data, "status": "ok", "updated_at": now}
    except Exception as e:
        logger.warning(f"Section {section_name} failed for {market}: {e}", exc_info=True)
        err = _classify_error(e)
        err["section"] = section_name
        err["retryable"] = err["reason"] not in ("auth",)
        err["suggestion_key"] = f"error.suggestion.{err['reason']}"
        return {"data": None, "status": "error", "error": err, "updated_at": None}


def _fetch_news_section(redis_client, market: str, language: str,
                        symbols: list[str], industries: list[str]) -> dict:
    """Fetch, translate, and cache news for a section."""
    try:
        news_items, news_errors = _fetch_news(market, symbols, industries)
        if news_items:
            translated = _summarize_news(news_items[:5], language, market)
            now = _time.strftime("%Y-%m-%dT%H:%M:%S%z")
            cache_data = {"data": _sanitize_floats(translated), "updated_at": now}
            news_cache_key = f"market:{market}:section:news:{language}"
            set_cached(redis_client, news_cache_key, cache_data, ttl_seconds=3600)
            return {"data": _sanitize_floats(translated), "status": "ok",
                    "updated_at": now}
        now = _time.strftime("%Y-%m-%dT%H:%M:%S%z")
        return {"data": [], "status": "ok", "updated_at": now}
    except Exception as e:
        logger.warning(f"News section failed for {market}: {e}", exc_info=True)
        err = _classify_error(e)
        err["section"] = "news"
        err["retryable"] = True
        err["suggestion_key"] = f"error.suggestion.{err['reason']}"
        return {"data": None, "status": "error", "error": err, "updated_at": None}


def get_market_data(redis_client, market: str, user: dict) -> dict:
    provider = _create_provider(market)
    config = SECTION_CONFIG[market]
    uid = str(user["id"])
    market_cfg = user.get("markets", {}).get(market, {})
    holdings = market_cfg.get("holdings", [])
    industries = _migrate_industries(market_cfg.get("industries", []))
    holdings_symbols = [h["symbol"] if isinstance(h, dict) else h for h in holdings]

    section_kwargs = {
        "holdings": holdings,
        "holdings_symbols": holdings_symbols,
        "industries": industries,
        "recommendations": [],
    }

    sections = {}

    for name in config["public"]:
        sections[name] = _fetch_section(redis_client, market, name, provider, uid=None, **section_kwargs)

    for name in config["private"]:
        sections[name] = _fetch_section(redis_client, market, name, provider, uid=uid, **section_kwargs)

    # News (per-language cache)
    language = user.get("language", "zh-CN")
    news_cache_key = f"market:{market}:section:news:{language}"
    news_cached = get_cached(redis_client, news_cache_key)
    if news_cached is not None:
        sections["news"] = {"data": news_cached["data"], "status": "cached",
                            "updated_at": news_cached["updated_at"]}
    else:
        sections["news"] = _fetch_news_section(redis_client, market, language,
                                                holdings_symbols, industries)

    return {"sections": sections}


def fetch_single_section(redis_client, market: str, section_name: str, user: dict) -> dict:
    """Fetch a single section independently (for SSE streaming).

    Returns the section result dict (same shape as _fetch_section output).
    """
    config = SECTION_CONFIG[market]
    is_private = section_name in config.get("private", {})
    is_news = section_name == "news"
    uid = str(user["id"]) if is_private else None

    market_cfg = user.get("markets", {}).get(market, {})
    holdings = market_cfg.get("holdings", [])
    industries = _migrate_industries(market_cfg.get("industries", []))
    holdings_symbols = [h["symbol"] if isinstance(h, dict) else h for h in holdings]

    # For news, use dedicated path
    if is_news:
        language = user.get("language", "zh-CN")
        news_cache_key = f"market:{market}:section:news:{language}"
        news_cached = get_cached(redis_client, news_cache_key)
        if news_cached is not None:
            return {"data": news_cached["data"], "status": "cached",
                    "updated_at": news_cached["updated_at"]}
        return _fetch_news_section(redis_client, market, language,
                                   holdings_symbols, industries)

    if not is_private and section_name not in config.get("public", {}):
        return {"data": None, "status": "error",
                "error": {"reason": "invalid_section",
                          "detail": f"Unknown section: {section_name}",
                          "section": section_name, "retryable": False,
                          "suggestion_key": "error.suggestion.unknown"},
                "updated_at": None}

    provider = _create_provider(market)
    section_kwargs = {
        "holdings": holdings,
        "holdings_symbols": holdings_symbols,
        "industries": industries,
        "recommendations": [],
    }
    return _fetch_section(redis_client, market, section_name, provider,
                          uid=uid, **section_kwargs)


def refresh_market(redis_client, market: str, user: dict) -> dict:
    if not can_refresh(redis_client, market):
        return {"status": "rate_limited"}

    set_refresh_lock(redis_client, market)

    uid = str(user["id"])
    config = SECTION_CONFIG[market]

    try:
        for name in config["public"]:
            invalidate_section(redis_client, market, name)
        for name in config["private"]:
            invalidate_section(redis_client, market, name, uid=uid)
        # Invalidate news caches for all known languages
        for lang in ("zh-CN", "ko-KR", "en"):
            invalidate(redis_client, f"market:{market}:section:news:{lang}")
        # Invalidate analysis caches for all known sections and languages
        all_section_names = list(config.get("public", {}).keys()) + list(config.get("private", {}).keys())
        for lang in ("zh-CN", "ko-KR", "en"):
            for sname in all_section_names:
                invalidate(redis_client, f"market:{market}:analysis:{sname}:{lang}")

        return get_market_data(redis_client, market, user)
    except Exception:
        # Clear the refresh lock early on failure so user isn't blocked
        invalidate(redis_client, f"refresh_lock:{market}")
        raise


def refresh_section(redis_client, market: str, section_name: str, user: dict) -> dict:
    """Refresh a single section and return its result."""
    config = SECTION_CONFIG[market]
    is_private = section_name in config.get("private", {})
    is_public = section_name in config.get("public", {})
    is_news = section_name == "news"

    if not is_private and not is_public and not is_news:
        return {"status": "error", "error": {"reason": "invalid_section",
                "detail": f"Unknown section: {section_name}"}}

    uid = str(user["id"]) if is_private else None

    if not can_section_refresh(redis_client, market, section_name, uid):
        return {"status": "rate_limited"}

    set_section_refresh_lock(redis_client, market, section_name, uid)

    if is_news:
        language = user.get("language", "zh-CN")
        news_cache_key = f"market:{market}:section:news:{language}"
        invalidate(redis_client, news_cache_key)
    else:
        invalidate_section(redis_client, market, section_name, uid)

    # Invalidate analysis cache when underlying data sections change
    if section_name in ("indices", "economic_calendar"):
        invalidate(redis_client, f"market:{market}:analysis:{section_name}:{user.get('language', 'zh-CN')}")

    # Fetch only the single section, not all sections
    section_result = fetch_single_section(redis_client, market, section_name, user)
    return {"section": section_name, **section_result}
