"""Market provider 能力声明 + 注册表扩展性测试。"""
from investbrief.market.base import MarketProvider


def test_market_provider_has_capability_attrs():
    """ABC 必须定义能力声明的默认值。"""
    assert hasattr(MarketProvider, "risk_group")
    assert hasattr(MarketProvider, "supports_regime")
    assert hasattr(MarketProvider, "data_class")
    assert MarketProvider.risk_group is None
    assert MarketProvider.supports_regime is False


def test_provider_default_news_calendar_empty():
    """默认 get_news/get_economic_calendar 返回空 list, 子类按需覆盖。"""
    class _Minimal(MarketProvider):
        market_code = "xx"
        def get_indices(self): return []
        def get_monetary_policy(self): return {}
        def get_asset_performance(self): return []
        def render_section(self, data, config, **kwargs): return ""
    p = _Minimal()
    assert p.get_news({}, 5) == []
    assert p.get_economic_calendar() == []


def test_us_cn_declare_capabilities():
    """US/CN 子类必须填齐能力声明，供编排层遍历时按 market 取 risk group/regime/data_class。"""
    from investbrief.market.us.provider import USMarketProvider
    from investbrief.market.cn.provider import CNMarketProvider
    assert USMarketProvider.risk_group == "us"
    assert USMarketProvider.supports_regime is True
    assert CNMarketProvider.risk_group == "cn"
    assert CNMarketProvider.supports_regime is True
