import logging

from investbrief.web.services.cache import (
    get_cached, set_cached, invalidate, get_last_updated,
    set_last_updated, can_refresh, set_refresh_lock,
)

logger = logging.getLogger(__name__)


def _public_keys(market: str) -> list[str]:
    if market == "us":
        return ["indices", "economic_calendar", "premarket_movers", "earnings_calendar", "congressional_trades"]
    return ["indices", "economic_calendar", "dragon_tiger", "sector_performance"]


def _private_keys(market: str) -> list[str]:
    return ["holdings", "recommendations"]


def get_market_data(redis_client, market: str, user: dict) -> dict:
    result = {}

    # Public data (shared across users)
    public_cache = get_cached(redis_client, f"market:{market}:public")
    if public_cache is None:
        public_cache = _fetch_and_cache_public(redis_client, market)
    for k in _public_keys(market):
        result[k] = public_cache.get(k, [])

    # User private data
    uid = user["id"]
    user_cache = get_cached(redis_client, f"market:{market}:user:{uid}:private")
    if user_cache is None:
        user_cache = _fetch_and_cache_user(redis_client, market, user)
    for k in _private_keys(market):
        result[k] = user_cache.get(k, [])

    # News (cached per market)
    news_cache = get_cached(redis_client, f"market:{market}:news")
    result["news"] = news_cache or []
    result["updated_at"] = get_last_updated(redis_client, market) or ""

    return result


def _fetch_and_cache_public(redis_client, market: str) -> dict:
    from investbrief.run import _create_provider
    provider = _create_provider(market)
    all_data = provider.fetch_all([], [], 3)
    public = {k: all_data.get(k, []) for k in _public_keys(market)}
    set_cached(redis_client, f"market:{market}:public", public)
    return public


def _fetch_and_cache_user(redis_client, market: str, user: dict) -> dict:
    from investbrief.run import _create_provider
    market_cfg = user.get("markets", {}).get(market, {})
    holdings = market_cfg.get("holdings", [])
    industries = market_cfg.get("industries", [])
    max_recs = market_cfg.get("max_recommendations", 3)

    provider = _create_provider(market)
    all_data = provider.fetch_all(holdings, industries, max_recs)

    private = {k: all_data.get(k, []) for k in _private_keys(market)}
    set_cached(redis_client, f"market:{market}:user:{user['id']}:private", private)
    return private


def refresh_market(redis_client, market: str, user: dict) -> dict:
    if not can_refresh(redis_client, market):
        return {"status": "rate_limited", "message": "请60秒后再试"}

    set_refresh_lock(redis_client, market)

    invalidate(redis_client, f"market:{market}:public")
    invalidate(redis_client, f"market:{market}:news")
    for key in redis_client.scan_iter(f"market:{market}:user:*:private"):
        invalidate(redis_client, key)

    set_last_updated(redis_client, market)

    return get_market_data(redis_client, market, user)
