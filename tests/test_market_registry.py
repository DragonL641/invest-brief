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


def test_gold_provider_declares_capabilities():
    from investbrief.market.gold.provider import GoldMarketProvider
    assert GoldMarketProvider.market_code == "gold"
    assert GoldMarketProvider.risk_group == "gold"
    assert GoldMarketProvider.supports_regime is False
    p = GoldMarketProvider()
    # get_news/get_economic_calendar 继承默认(空)
    assert p.get_news({}, 5) == []
    assert p.get_economic_calendar() == []
    # render_section 透传 risk_html, 不 import risk
    assert p.render_section({}, {}, risk_html="<gold-section/>") == "<gold-section/>"
    assert p.render_section({}, {}) == ""


def test_fake_market_runs_through_pipeline(monkeypatch, capsys):
    """注册一个全新市场 kr(FakeProvider), 编排层无需改代码即可跑通。

    这是'加市场纯增量'的可执行验收。
    """
    import investbrief.pipelines.macro as macro

    class _KRFakeProvider:
        market_code = "kr"
        risk_group = None            # kr 暂不参与 risk
        supports_regime = False
        data = type("D", (), {"close": lambda self: None})()
        def refresh(self, force=False): pass
        def get_monetary_policy(self): return {"kr_rate": 3.5}
        def get_asset_performance(self): return [{"name": "KOSPI", "change": 0.5}]
        def get_economic_calendar(self): return []
        def get_news(self, config, limit): return [{"title": "kr-news"}]
        def render_section(self, data, config, **kwargs):
            return "<section-kr/>"

    from investbrief.market import MARKET_PROVIDERS
    MARKET_PROVIDERS["kr"] = _KRFakeProvider
    try:
        monkeypatch.setattr(macro, "enabled_market_codes", lambda cfg: ["us", "cn", "gold", "kr"])
        monkeypatch.setattr(macro, "create_provider", lambda c: _KRFakeProvider())
        monkeypatch.setattr(macro, "load_config", lambda: {"recipients": [{"active": True}]})
        monkeypatch.setattr(macro, "_safe_regime_judge", lambda e, c: {})
        args = type("A", (), {"dry_run": True, "skip_summary": True, "update": False, "only": "macro"})()
        macro.run_macro_report(args)
        import json
        data = json.loads(capsys.readouterr().out)
        assert "<section-kr/>" in data["market_section_html"]
    finally:
        MARKET_PROVIDERS.pop("kr", None)
