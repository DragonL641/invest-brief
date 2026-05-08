import json
import uuid
from fastapi import APIRouter, Depends
from investbrief.web.auth import get_current_user
from investbrief.web.deps import get_redis
from investbrief.web.models.schemas import WatchlistItem

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


def _key(user_id: int) -> str:
    return f"user:{user_id}:watchlist"


def _load(redis, user_id: int) -> list[dict]:
    data = redis.get(_key(user_id))
    return json.loads(data) if data else []


def _save(redis, user_id: int, items: list[dict]):
    redis.set(_key(user_id), json.dumps(items, ensure_ascii=False))


@router.get("")
def get_watchlist(user: dict = Depends(get_current_user), redis=Depends(get_redis)):
    return _load(redis, user["id"])


@router.post("")
def add_item(item: WatchlistItem, user: dict = Depends(get_current_user), redis=Depends(get_redis)):
    items = _load(redis, user["id"])
    new_item = {"id": str(uuid.uuid4())[:8], "symbol": item.symbol, "name": item.name, "market": item.market}
    items.append(new_item)
    _save(redis, user["id"], items)
    return new_item


@router.delete("/{item_id}")
def delete_item(item_id: str, user: dict = Depends(get_current_user), redis=Depends(get_redis)):
    items = _load(redis, user["id"])
    items = [i for i in items if i["id"] != item_id]
    _save(redis, user["id"], items)
    return {"ok": True}
