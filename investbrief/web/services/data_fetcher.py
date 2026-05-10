import logging
import math

from investbrief.web.services.cache import (
    get_cached, set_cached, invalidate, get_last_updated,
    set_last_updated, can_refresh, set_refresh_lock,
)

logger = logging.getLogger(__name__)


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
    if market == "us":
        return ["indices", "economic_calendar", "premarket_movers", "earnings_calendar", "congressional_trades"]
    return ["indices", "economic_calendar", "dragon_tiger", "sector_performance"]


def _private_keys(market: str) -> list[str]:
    return ["holdings", "recommendations"]


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


def _translate_news(items: list[dict], language: str, market: str) -> list[dict]:
    """Translate news title and summary via Claude API. Returns translated items."""
    source_lang = "Chinese" if market == "cn" else "English"
    target_lang = {"zh-CN": "简体中文", "ko-KR": "한국어", "en": "English"}.get(language, language)

    if source_lang == "Chinese" and language.startswith("zh"):
        return items

    import os
    import json
    try:
        import anthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        base_url = os.environ.get("ANTHROPIC_BASE_URL")
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        client = anthropic.Anthropic(**kwargs)
        model = os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL", "claude-sonnet-4-6")

        payload = json.dumps(
            [{"title": it.get("title", ""), "summary": it.get("summary", "")} for it in items],
            ensure_ascii=False,
        )

        prompt = (
            f"将以下新闻从{source_lang}翻译为{target_lang}。"
            f"返回 JSON 数组，每项含 title 和 summary 字段，顺序不变。"
            f"summary 要求：提炼为 2-3 个要点，每点一行，用换行符分隔，不要编号或前缀符号。"
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
        logger.warning(f"News translation failed: {e}", exc_info=True)
        return items


def get_market_data(redis_client, market: str, user: dict) -> dict:
    result = {}
    errors = []

    # Public data (shared across users)
    public_cache = get_cached(redis_client, f"market:{market}:public")
    if public_cache is None:
        public_cache, pub_errors = _fetch_and_cache_public(redis_client, market)
        errors.extend(pub_errors)
    for k in _public_keys(market):
        result[k] = public_cache.get(k, [])

    # User private data
    uid = user["id"]
    user_cache = get_cached(redis_client, f"market:{market}:user:{uid}:private")
    if user_cache is None:
        user_cache, usr_errors = _fetch_and_cache_user(redis_client, market, user)
        errors.extend(usr_errors)
    for k in _private_keys(market):
        result[k] = user_cache.get(k, [])

    # News (cached per market+language)
    language = user.get("language", "zh-CN")
    news_cache_key = f"market:{market}:news:{language}"
    news_cache = get_cached(redis_client, news_cache_key)
    if news_cache is None:
        market_cfg = user.get("markets", {}).get(market, {})
        symbols = [h.get("symbol", h) if isinstance(h, dict) else h
                   for h in market_cfg.get("holdings", [])]
        industries = market_cfg.get("industries", [])
        news_items, news_errors = _fetch_news(market, symbols, industries)
        errors.extend(news_errors)
        if news_items:
            translated = _translate_news(news_items[:5], language, market)
            set_cached(redis_client, news_cache_key, translated)
            news_cache = translated
        else:
            news_cache = news_items
    result["news"] = news_cache or []
    result["updated_at"] = get_last_updated(redis_client, market) or ""
    if errors:
        result["errors"] = errors

    return _sanitize_floats(result)


def _create_provider(market: str):
    if market == "us":
        from investbrief.us.provider import USMarketProvider
        return USMarketProvider()
    elif market == "cn":
        from investbrief.cn.provider import CNMarketProvider
        return CNMarketProvider()
    raise ValueError(f"Unknown market: {market}")


def _fetch_and_cache_public(redis_client, market: str) -> tuple[dict, list]:
    provider = _create_provider(market)
    try:
        all_data = provider.fetch_all([], [], 3)
        public = {k: all_data.get(k, []) for k in _public_keys(market)}
        set_cached(redis_client, f"market:{market}:public", public)
        return public, []
    except Exception as e:
        logger.warning(f"Public data fetch failed for {market}: {e}", exc_info=True)
        err = _classify_error(e)
        errors = [{"section": k, **err} for k in _public_keys(market)]
        return {k: [] for k in _public_keys(market)}, errors


def _fetch_and_cache_user(redis_client, market: str, user: dict) -> tuple[dict, list]:
    market_cfg = user.get("markets", {}).get(market, {})
    holdings = market_cfg.get("holdings", [])
    industries = market_cfg.get("industries", [])
    max_recs = market_cfg.get("max_recommendations", 3)

    provider = _create_provider(market)
    try:
        all_data = provider.fetch_all(holdings, industries, max_recs)
        private = {k: all_data.get(k, []) for k in _private_keys(market)}
        set_cached(redis_client, f"market:{market}:user:{user['id']}:private", private)
        return private, []
    except Exception as e:
        logger.warning(f"User data fetch failed for {market}: {e}", exc_info=True)
        err = _classify_error(e)
        errors = [{"section": k, **err} for k in _private_keys(market)]
        return {k: [] for k in _private_keys(market)}, errors


def refresh_market(redis_client, market: str, user: dict) -> dict:
    if not can_refresh(redis_client, market):
        return {"status": "rate_limited", "message": "请60秒后再试"}

    set_refresh_lock(redis_client, market)

    invalidate(redis_client, f"market:{market}:public")
    for key in redis_client.scan_iter(f"market:{market}:news:*"):
        invalidate(redis_client, key)
    for key in redis_client.scan_iter(f"market:{market}:user:*:private"):
        invalidate(redis_client, key)

    set_last_updated(redis_client, market)

    return get_market_data(redis_client, market, user)
