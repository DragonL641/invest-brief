import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from investbrief.web.auth import get_current_user
from investbrief.web.deps import get_redis
from investbrief.web.services.data_fetcher import (
    get_market_data, refresh_market, refresh_section, fetch_single_section,
    SECTION_CONFIG,
)
from investbrief.web.services.cache import get_section_cached

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/data", tags=["data"])

_pool = ThreadPoolExecutor(max_workers=4)

FETCH_TIMEOUT = 180


def _error_sections(market: str, reason: str = "timeout") -> dict:
    """Return all sections in error state (used on timeout/unhandled error)."""
    sections = {}
    all_sections = (
        list(SECTION_CONFIG.get(market, {}).get("public", {}).keys())
        + list(SECTION_CONFIG.get(market, {}).get("private", {}).keys())
        + ["news"]
    )
    for name in all_sections:
        sections[name] = {
            "data": None, "status": "error",
            "error": {"reason": reason, "detail": "", "section": name,
                      "retryable": True, "suggestion_key": f"error.suggestion.{reason}"},
            "updated_at": None,
        }
    return {"sections": sections}


# Section fetch order: fast/light sections first, heavy sections last
_STREAM_ORDER = [
    "indices",
    "economic_calendar",
    "congressional_trades",
    "news",
    "premarket_movers",
    "holdings",
    "recommendations",
    "earnings_calendar",
]


@router.get("/status")
def get_status(redis=Depends(get_redis)):
    """Return last-updated timestamp per market (from the most recent public section)."""
    result = {}
    for market in ("us", "cn"):
        latest = None
        for section_name in SECTION_CONFIG.get(market, {}).get("public", {}):
            cached = get_section_cached(redis, market, section_name)
            if cached and cached.get("updated_at"):
                ts = cached["updated_at"]
                if latest is None or ts > latest:
                    latest = ts
        result[market] = {"updated_at": latest}
    return result


async def _stream_sections(market: str, user: dict, redis):
    """Async generator that yields SSE events for each section as it completes."""
    loop = asyncio.get_event_loop()
    for section_name in _STREAM_ORDER:
        cfg = SECTION_CONFIG.get(market, {})
        is_valid = (
            section_name in cfg.get("public", {})
            or section_name in cfg.get("private", {})
            or section_name == "news"
        )
        if not is_valid:
            continue
        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    _pool, fetch_single_section, redis, market, section_name, user,
                ),
                timeout=FETCH_TIMEOUT,
            )
            event = {"type": "section", "section": section_name, **result}
        except asyncio.TimeoutError:
            logger.warning(f"SSE section timeout: {market}/{section_name}")
            event = {
                "type": "section", "section": section_name,
                "data": None, "status": "error",
                "error": {"reason": "timeout", "detail": "", "section": section_name,
                          "retryable": True, "suggestion_key": "error.suggestion.timeout"},
                "updated_at": None,
            }
        except Exception as e:
            logger.error(f"SSE section error: {market}/{section_name}: {e}")
            event = {
                "type": "section", "section": section_name,
                "data": None, "status": "error",
                "error": {"reason": "unknown", "detail": str(e)[:200], "section": section_name,
                          "retryable": True, "suggestion_key": "error.suggestion.unknown"},
                "updated_at": None,
            }
        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    yield "data: {\"type\": \"done\"}\n\n"


@router.get("/{market}/stream")
async def stream_data(market: str, user: dict = Depends(get_current_user), redis=Depends(get_redis)):
    if market not in ("us", "cn"):
        raise HTTPException(status_code=400, detail="invalid market")
    return StreamingResponse(
        _stream_sections(market, user, redis),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{market}")
async def get_data(market: str, user: dict = Depends(get_current_user), redis=Depends(get_redis)):
    if market not in ("us", "cn"):
        raise HTTPException(status_code=400, detail="invalid market")
    loop = asyncio.get_event_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(_pool, get_market_data, redis, market, user),
            timeout=FETCH_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning(f"Data fetch timeout for market={market}")
        return _error_sections(market, reason="timeout")
    except Exception as e:
        logger.error(f"Data fetch error for market={market}: {e}")
        return _error_sections(market, reason="unknown")


@router.post("/{market}/refresh")
async def refresh_data(market: str, user: dict = Depends(get_current_user), redis=Depends(get_redis)):
    if market not in ("us", "cn"):
        raise HTTPException(status_code=400, detail="invalid market")
    loop = asyncio.get_event_loop()
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(_pool, refresh_market, redis, market, user),
            timeout=FETCH_TIMEOUT,
        )
        if result.get("status") == "rate_limited":
            return JSONResponse(status_code=429, content={"status": "rate_limited"})
        return result
    except asyncio.TimeoutError:
        logger.warning(f"Data refresh timeout for market={market}")
        return _error_sections(market, reason="timeout")
    except Exception as e:
        logger.error(f"Data refresh error for market={market}: {e}")
        return _error_sections(market, reason="unknown")


@router.post("/{market}/refresh/{section}")
async def refresh_single_section(
    market: str, section: str,
    user: dict = Depends(get_current_user), redis=Depends(get_redis),
):
    if market not in ("us", "cn"):
        raise HTTPException(status_code=400, detail="invalid market")
    loop = asyncio.get_event_loop()
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(_pool, refresh_section, redis, market, section, user),
            timeout=FETCH_TIMEOUT,
        )
        if result.get("status") == "rate_limited":
            return JSONResponse(status_code=429, content={"status": "rate_limited"})
        return result
    except asyncio.TimeoutError:
        logger.warning(f"Section refresh timeout for {market}/{section}")
        return {
            "section": section, "data": None, "status": "error",
            "error": {"reason": "timeout", "detail": "", "section": section,
                      "retryable": True, "suggestion_key": "error.suggestion.timeout"},
            "updated_at": None,
        }
    except Exception as e:
        logger.error(f"Section refresh error for {market}/{section}: {e}")
        return {
            "section": section, "data": None, "status": "error",
            "error": {"reason": "unknown", "detail": str(e)[:200], "section": section,
                      "retryable": True, "suggestion_key": "error.suggestion.unknown"},
            "updated_at": None,
        }
