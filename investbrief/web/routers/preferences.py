import logging
from fastapi import APIRouter, Depends, HTTPException
from investbrief.web.auth import get_current_user
from investbrief.web.config import update_recipient
from investbrief.web.models.schemas import PreferencesUpdate, PreferencesResponse, AddHoldingRequest
from investbrief.us.industries import US_GICS_SECTORS, US_INDUSTRIES_MIGRATION
from investbrief.cn.industries import CN_SW_INDUSTRIES, CN_INDUSTRIES_MIGRATION

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/preferences", tags=["preferences"])

_VALID_KEYS = {i["key"] for i in US_GICS_SECTORS} | {i["key"] for i in CN_SW_INDUSTRIES}
_MIGRATION_MAP = {**US_INDUSTRIES_MIGRATION, **CN_INDUSTRIES_MIGRATION}


def _migrate_industries(industries: list[str]) -> list[str]:
    """Map old custom industry keys to new official keys, drop unmappable ones."""
    result = []
    for key in industries:
        if key in _VALID_KEYS:
            result.append(key)
        elif key in _MIGRATION_MAP:
            mapped = _MIGRATION_MAP[key]
            if mapped not in result:
                result.append(mapped)
    return result


def _ensure_delivery(user: dict) -> list:
    """Auto-migrate users without delivery field."""
    delivery = user.get("delivery")
    if delivery is not None:
        return delivery
    markets = user.get("markets", {})
    return [{
        "email": user["email"],
        "language": user.get("language", "zh-CN"),
        "schedule": {m: [] for m in markets},
    }]


@router.get("", response_model=PreferencesResponse)
def get_preferences(user: dict = Depends(get_current_user)):
    markets = user.get("markets", {})
    migrated = {}
    for mkt, cfg in markets.items():
        industries = cfg.get("industries", [])
        new_industries = _migrate_industries(industries)
        migrated[mkt] = {**cfg, "industries": new_industries}

    delivery = _ensure_delivery(user)
    return PreferencesResponse(
        markets=migrated,
        delivery=delivery,
        language=user.get("language", "zh-CN"),
    )


@router.put("")
def update_preferences(
    body: PreferencesUpdate,
    user: dict = Depends(get_current_user),
):
    updates = {}

    if body.markets:
        existing_markets = user.get("markets", {})
        for market, prefs in body.markets.items():
            existing_markets[market] = {
                **existing_markets.get(market, {}),
                "holdings": [h.model_dump() for h in prefs.holdings],
                "industries": prefs.industries,
            }
        updates["markets"] = existing_markets

    if body.delivery:
        updates["delivery"] = [d.model_dump() for d in body.delivery]

    result = update_recipient(user["id"], updates)
    if result is None:
        raise HTTPException(status_code=500, detail="user_not_found")

    return {"status": "ok"}


@router.post("/holding")
def add_holding(
    body: AddHoldingRequest,
    user: dict = Depends(get_current_user),
):
    """Add a single stock to user's holdings (used by watchlist add button)."""
    cfg = user.get("markets", {}).get(body.market, {})
    holdings = cfg.get("holdings", [])

    if any(h.get("symbol") == body.symbol for h in holdings):
        raise HTTPException(status_code=409, detail="Stock already in holdings")

    holdings.append({"symbol": body.symbol, "name": body.name})

    updates = {
        "markets": {
            **user.get("markets", {}),
            body.market: {**cfg, "holdings": holdings},
        }
    }
    result = update_recipient(user["id"], updates)
    if result is None:
        raise HTTPException(status_code=500, detail="user_not_found")

    return {"status": "ok"}
