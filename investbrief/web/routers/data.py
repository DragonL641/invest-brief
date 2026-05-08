from fastapi import APIRouter, Depends
from investbrief.web.auth import get_current_user
from investbrief.web.deps import get_redis
from investbrief.web.services.data_fetcher import get_market_data, refresh_market
from investbrief.web.services.cache import get_last_updated

router = APIRouter(prefix="/api/data", tags=["data"])


@router.get("/{market}")
def get_data(market: str, user: dict = Depends(get_current_user), redis=Depends(get_redis)):
    if market not in ("us", "cn"):
        return {"error": "invalid market"}
    return get_market_data(redis, market, user)


@router.post("/{market}/refresh")
def refresh_data(market: str, user: dict = Depends(get_current_user), redis=Depends(get_redis)):
    if market not in ("us", "cn"):
        return {"error": "invalid market"}
    return refresh_market(redis, market, user)


@router.get("/status")
def get_status(redis=Depends(get_redis)):
    return {
        "us": {"updated_at": get_last_updated(redis, "us")},
        "cn": {"updated_at": get_last_updated(redis, "cn")},
    }
