"""ETF 分析 API 路由。"""

import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from investbrief.web.auth import get_current_user
from investbrief.web.deps import get_redis
from investbrief.web.services.cache import get_cached, set_cached
from investbrief.cn.client import AKShareClient
from investbrief.etf.analyzer import ETFAnalyzer

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/etf", tags=["etf"])

_pool = ThreadPoolExecutor(max_workers=4)


@router.get("/search")
async def search_etf(q: str = Query(..., min_length=1, max_length=20)):
    """搜索 ETF（按代码或名称模糊匹配）。"""
    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(_pool, _search_etf_sync, q)
    return {"results": results}


def _search_etf_sync(q: str):
    client = AKShareClient()
    return client.search_etf(q)


@router.get("/analyze/{symbol}")
async def analyze_etf(
    symbol: str,
    user: dict = Depends(get_current_user),
    redis=Depends(get_redis),
):
    """单只 ETF 完整分析（数据 + 规则匹配 + AI 综合研判）。"""
    cache_key = f"etf:analyze:{symbol}"
    cached = get_cached(redis, cache_key)
    if cached:
        return cached

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(_pool, _analyze_etf_sync, symbol)

    resp = {
        "symbol": result.symbol,
        "name": result.name,
        "price": result.price,
        "change_pct": result.change_pct,
        "iopv": result.iopv,
        "premium_rate": result.premium_rate,
        "main_net_flow": result.main_net_flow,
        "rule_results": result.rule_results,
        "dimension_summary": result.dimension_summary,
        "ai_conclusion": result.ai_conclusion,
    }
    set_cached(redis, cache_key, resp, ttl_seconds=300)
    return resp


def _analyze_etf_sync(symbol: str):
    analyzer = ETFAnalyzer()
    return analyzer.analyze(symbol)


@router.get("/batch")
async def analyze_batch(
    symbols: str = Query(..., description="逗号分隔的 ETF 代码列表"),
    user: dict = Depends(get_current_user),
    redis=Depends(get_redis),
):
    """批量分析多只 ETF（每只返回摘要）。"""
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    if not symbol_list:
        return {"results": []}

    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(_pool, _analyze_batch_sync, symbol_list, redis)
    return {"results": results}


def _analyze_batch_sync(symbol_list: list[str], redis):
    # 批量获取 spot 数据（一次 API 调用）
    client = AKShareClient()
    spot_list = client.get_etf_spot_batch(symbol_list)
    spot_map = {s["symbol"]: s for s in spot_list}

    results = []
    for sym in symbol_list[:10]:
        spot = spot_map.get(sym)
        if not spot:
            results.append({"symbol": sym, "name": "未找到", "error": True})
            continue

        cache_key = f"etf:analyze:{sym}"
        cached = get_cached(redis, cache_key)
        if cached:
            results.append({
                "symbol": sym,
                "name": cached.get("name", spot.get("name", "")),
                "price": cached.get("price", spot.get("price")),
                "change_pct": cached.get("change_pct", spot.get("change_pct")),
                "premium_rate": cached.get("premium_rate", spot.get("premium_rate")),
                "main_net_flow": cached.get("main_net_flow", spot.get("main_net_flow")),
                "ai_conclusion": cached.get("ai_conclusion", ""),
                "dimension_summary": cached.get("dimension_summary", {}),
            })
        else:
            results.append({
                "symbol": sym,
                "name": spot.get("name", ""),
                "price": spot.get("price"),
                "change_pct": spot.get("change_pct"),
                "premium_rate": spot.get("premium_rate"),
                "main_net_flow": spot.get("main_net_flow"),
                "ai_conclusion": "",
                "dimension_summary": {},
            })

    return results


@router.get("/watchlist")
async def get_watchlist(user: dict = Depends(get_current_user), redis=Depends(get_redis)):
    """获取用户 ETF 自选列表。"""
    from investbrief.web.config import get_config
    config = get_config()
    recipients = config.get("recipients", [])
    for r in recipients:
        if r.get("id") == user["id"]:
            watchlist = r.get("etf_watchlist", [])
            return {"watchlist": watchlist}
    return {"watchlist": []}


@router.post("/watchlist")
async def add_to_watchlist(
    payload: dict,
    user: dict = Depends(get_current_user),
    redis=Depends(get_redis),
):
    """添加 ETF 到自选列表。payload: {"symbol": "510300"}"""
    symbol = payload.get("symbol", "").strip()
    if not symbol or len(symbol) != 6 or not symbol.isdigit():
        return {"error": "ETF 代码必须是6位数字"}

    from investbrief.web.config import get_config, update_recipient
    config = get_config()
    recipients = config.get("recipients", [])

    # 获取 ETF 名称（使用缓存的全量数据）
    loop = asyncio.get_event_loop()
    spot = await loop.run_in_executor(_pool, _get_etf_name, symbol)
    name = spot.get("name", "") if spot else symbol

    for i, r in enumerate(recipients):
        if r.get("id") == user["id"]:
            watchlist = r.get("etf_watchlist", [])
            if any(w.get("symbol") == symbol for w in watchlist):
                return {"watchlist": watchlist}
            watchlist.append({"symbol": symbol, "name": name})
            recipients[i]["etf_watchlist"] = watchlist
            update_recipient(r["id"], {"etf_watchlist": watchlist})
            return {"watchlist": watchlist}

    return {"error": "User not found"}


def _get_etf_name(symbol: str):
    client = AKShareClient()
    return client.get_etf_spot(symbol)


@router.delete("/watchlist/{symbol}")
async def remove_from_watchlist(
    symbol: str,
    user: dict = Depends(get_current_user),
    redis=Depends(get_redis),
):
    """从自选列表移除 ETF。"""
    from investbrief.web.config import get_config, update_recipient
    config = get_config()
    recipients = config.get("recipients", [])

    for i, r in enumerate(recipients):
        if r.get("id") == user["id"]:
            watchlist = r.get("etf_watchlist", [])
            watchlist = [w for w in watchlist if w.get("symbol") != symbol]
            recipients[i]["etf_watchlist"] = watchlist
            update_recipient(r["id"], {"etf_watchlist": watchlist})
            return {"watchlist": watchlist}

    return {"error": "User not found"}
