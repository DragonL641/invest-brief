import logging
from fastapi import APIRouter, Depends
from investbrief.web.auth import get_current_user
from investbrief.web.config import update_recipient
from investbrief.web.models.schemas import PreferencesUpdate, PreferencesResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/preferences", tags=["preferences"])


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
    delivery = _ensure_delivery(user)
    return PreferencesResponse(
        markets=markets,
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
        return {"error": "user_not_found"}

    return {"status": "ok"}
