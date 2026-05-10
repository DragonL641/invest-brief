import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, Depends
from investbrief.web.auth import get_current_user
from investbrief.web.deps import get_redis
from investbrief.web.services.data_fetcher import get_market_data, refresh_market
from investbrief.web.services.cache import get_last_updated

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/data", tags=["data"])

_pool = ThreadPoolExecutor(max_workers=4)

FETCH_TIMEOUT = 90


@router.get("/status")
def get_status(redis=Depends(get_redis)):
    return {
        "us": {"updated_at": get_last_updated(redis, "us")},
        "cn": {"updated_at": get_last_updated(redis, "cn")},
    }


def _empty_result(market: str, reason: str = "timeout") -> dict:
    keys = ["indices", "holdings", "recommendations", "news", "economic_calendar"]
    errors = [{"section": k, "reason": reason, "detail": ""} for k in keys]
    return {k: [] for k in keys} | {"updated_at": "", "error": "data_fetch_timeout", "errors": errors}


@router.get("/{market}")
async def get_data(market: str, user: dict = Depends(get_current_user), redis=Depends(get_redis)):
    if market not in ("us", "cn"):
        return {"error": "invalid market"}
    loop = asyncio.get_event_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(_pool, get_market_data, redis, market, user),
            timeout=FETCH_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning(f"Data fetch timeout for market={market}")
        return _empty_result(market, reason="timeout")
    except Exception as e:
        logger.error(f"Data fetch error for market={market}: {e}")
        return _empty_result(market, reason="unknown")


@router.post("/{market}/refresh")
async def refresh_data(market: str, user: dict = Depends(get_current_user), redis=Depends(get_redis)):
    if market not in ("us", "cn"):
        return {"error": "invalid market"}
    loop = asyncio.get_event_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(_pool, refresh_market, redis, market, user),
            timeout=FETCH_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning(f"Data refresh timeout for market={market}")
        return _empty_result(market, reason="timeout")
    except Exception as e:
        logger.error(f"Data refresh error for market={market}: {e}")
        return _empty_result(market, reason="unknown")
