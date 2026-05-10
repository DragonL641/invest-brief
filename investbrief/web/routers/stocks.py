import logging
from fastapi import APIRouter, Depends, Query
from investbrief.web.auth import get_current_user
from investbrief.web.deps import get_redis
from investbrief.web.services.cache import get_cached, set_cached
from investbrief.us.clients import FinnhubClient
from investbrief.us.industries import US_GICS_SECTORS
from investbrief.cn.industries import CN_SW_INDUSTRIES

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/stocks", tags=["stocks"])


@router.get("/search")
def search_stocks(
    q: str = Query(..., min_length=1),
    market: str = Query(...),
    user: dict = Depends(get_current_user),
):
    if market == "us":
        return _search_us(q)
    elif market == "cn":
        return _search_cn(q)
    return {"results": []}


@router.get("/industries")
def get_industries(
    market: str = Query(...),
    user: dict = Depends(get_current_user),
):
    if market == "us":
        return {"industries": US_GICS_SECTORS}
    elif market == "cn":
        return {"industries": CN_SW_INDUSTRIES}
    return {"industries": []}


def _search_us(query: str) -> dict:
    client = FinnhubClient()
    if not client.enabled:
        return {"results": []}
    try:
        results = client.search_symbol(query)
    except Exception as e:
        logger.warning(f"US stock search failed: {e}")
        results = []
    return {"results": results}


def _search_cn(query: str) -> dict:
    redis_client = get_redis()
    cache_key = "stocks:cn:all"
    stocks = None

    try:
        cached = get_cached(redis_client, cache_key)
        if cached:
            stocks = cached.get("stocks")
    except Exception:
        pass

    if stocks is None:
        try:
            import akshare as ak
            df = ak.stock_zh_a_spot_em()
            stocks = [
                {"symbol": str(row["代码"]), "name": str(row["名称"])}
                for _, row in df.iterrows()
            ]
            try:
                set_cached(redis_client, cache_key, {"stocks": stocks}, ttl_seconds=3600)
            except Exception:
                pass
        except Exception as e:
            logger.warning(f"CN stock list fetch failed: {e}")
            return {"results": []}

    q = query.lower()
    results = [s for s in stocks if q in s["symbol"].lower() or q in s["name"]][:20]
    return {"results": results}
