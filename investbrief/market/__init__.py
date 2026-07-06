"""市场分析域：provider 工厂 + 公共导出。"""
from investbrief.market.base import MarketProvider
from investbrief.market.us.provider import USMarketProvider
from investbrief.market.cn.provider import CNMarketProvider
from investbrief.market.gold.provider import GoldMarketProvider

MARKET_PROVIDERS = {
    "us": USMarketProvider,
    "cn": CNMarketProvider,
    "gold": GoldMarketProvider,
}


def create_provider(market: str) -> MarketProvider:
    """字典分发，加新市场只需在 MARKET_PROVIDERS 注册一行。"""
    cls = MARKET_PROVIDERS.get(market)
    if cls is None:
        raise ValueError(f"Unknown market: {market}. Registered: {sorted(MARKET_PROVIDERS)}")
    return cls()
