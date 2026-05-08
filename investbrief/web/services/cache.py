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
