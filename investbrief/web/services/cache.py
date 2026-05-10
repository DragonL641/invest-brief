import json
import time
from typing import Optional


def get_cached(redis_client, key: str) -> Optional[dict]:
    data = redis_client.get(key)
    if data is None:
        return None
    return json.loads(data)


def set_cached(redis_client, key: str, value: dict, ttl_seconds: int = 14400):
    redis_client.setex(key, ttl_seconds, json.dumps(value, ensure_ascii=False, default=str))


def invalidate(redis_client, key: str):
    redis_client.delete(key)


def get_last_updated(redis_client, market: str) -> Optional[str]:
    return redis_client.get(f"market:{market}:updated_at")


def set_last_updated(redis_client, market: str):
    redis_client.set(f"market:{market}:updated_at", time.strftime("%Y-%m-%dT%H:%M:%S%z"))


def can_refresh(redis_client, market: str) -> bool:
    key = f"market:{market}:refresh_lock"
    return redis_client.get(key) is None


def set_refresh_lock(redis_client, market: str, ttl: int = 60):
    redis_client.setex(f"market:{market}:refresh_lock", ttl, "1")


# --- Section-level cache operations ---

def get_section_cached(redis_client, market: str, section: str, uid: str | None = None) -> dict | None:
    key = _section_key(market, section, uid)
    return get_cached(redis_client, key)


def set_section_cached(redis_client, market: str, section: str, value: dict,
                       ttl: int, uid: str | None = None):
    key = _section_key(market, section, uid)
    set_cached(redis_client, key, value, ttl_seconds=ttl)


def invalidate_section(redis_client, market: str, section: str, uid: str | None = None):
    key = _section_key(market, section, uid)
    invalidate(redis_client, key)


def can_section_refresh(redis_client, market: str, section: str, uid: str | None = None) -> bool:
    key = _section_refresh_lock_key(market, section, uid)
    return redis_client.get(key) is None


def set_section_refresh_lock(redis_client, market: str, section: str,
                             uid: str | None = None, ttl: int = 30):
    key = _section_refresh_lock_key(market, section, uid)
    redis_client.setex(key, ttl, "1")


def _section_key(market: str, section: str, uid: str | None) -> str:
    if uid:
        return f"market:{market}:user:{uid}:section:{section}"
    return f"market:{market}:section:{section}"


def _section_refresh_lock_key(market: str, section: str, uid: str | None) -> str:
    if uid:
        return f"market:{market}:user:{uid}:section:{section}:refresh_lock"
    return f"market:{market}:section:{section}:refresh_lock"
