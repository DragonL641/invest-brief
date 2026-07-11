"""Macro pipeline 编排层: 遍历 enabled markets, 单市场失败不影响其他。"""
import json

import investbrief.pipelines.macro as macro


def _stub_providers(monkeypatch, market_codes):
    captured = {"rendered": [], "news": []}

    class _StubProvider:
        def __init__(self, code):
            self.market_code = code
            self.risk_group = code
            self.supports_regime = code != "gold"
            self.data = type("D", (), {"close": lambda self: None})()

        def refresh(self, force=False):
            pass

        def get_monetary_policy(self):
            return {"stub": self.market_code}

        def get_asset_performance(self):
            return []

        def get_economic_calendar(self):
            return []

        def get_news(self, config, limit):
            captured["news"].append(self.market_code)
            return [{"title": f"news-{self.market_code}"}]

        def render_section(self, data, config, **kwargs):
            captured["rendered"].append((self.market_code, kwargs.get("risk_html", ""),
                                         kwargs.get("regime_html", "")))
            return f"<section-{self.market_code}/>"

    monkeypatch.setattr(macro, "create_provider", lambda code: _StubProvider(code))
    monkeypatch.setattr(macro, "enabled_market_codes", lambda cfg: market_codes)
    monkeypatch.setattr(macro, "_safe_regime_judge", lambda e, c: {"quadrant": "中性"})
    return captured


def _run_args(**kw):
    return type("A", (), {"dry_run": True, "skip_summary": True, "update": False,
                          "only": "macro", **kw})()


def _patch_overseas(monkeypatch):
    """stub overseas fetch(避免 network),返回最小可用 data。"""
    import investbrief.market.overseas as overseas_mod
    monkeypatch.setattr(overseas_mod, "fetch_overseas_data",
                        lambda ak: {"fed_rate": 5.25, "us_10y": 4.56,
                                    "sp500": {"point": 7575, "change": 0.4}, "usdcny": 7.18})


def test_pipeline_iterates_all_enabled_markets(monkeypatch, capsys):
    """us 由外围卡替代(不渲染 us section);cn/gold 正常遍历。"""
    captured = _stub_providers(monkeypatch, ["us", "cn", "gold"])
    monkeypatch.setattr(macro, "load_config", lambda: {"recipients": [{"active": True}]})
    _patch_overseas(monkeypatch)
    macro.run_macro_report(_run_args())
    data = json.loads(capsys.readouterr().out)
    rendered_codes = [c for c, _, _ in captured["rendered"]]
    assert rendered_codes == ["cn", "gold"]           # us 排除(外围卡替代)
    assert set(captured["news"]) == {"cn", "gold"}     # us news 也不取
    html = data["market_section_html"]
    assert "外围环境" in html                           # 外围卡置顶
    assert "<section-cn/>" in html and "<section-gold/>" in html
    assert "<section-us/>" not in html                 # us 不再渲染


def test_news_one_provider_failure_does_not_block_others(monkeypatch, capsys):
    """单 provider get_news 抛异常时,其它 provider 的新闻仍应被收集(容错在循环内)。"""

    class _Provider:
        def __init__(self, code, news_fn):
            self.market_code = code
            self.risk_group = code
            self.supports_regime = code != "gold"
            self.data = type("D", (), {"close": lambda self: None})()
            self._news_fn = news_fn

        def refresh(self, force=False):
            pass

        def get_monetary_policy(self):
            return {}

        def get_asset_performance(self):
            return []

        def get_economic_calendar(self):
            return []

        def get_news(self, config, limit):
            return self._news_fn()

        def render_section(self, data, config, **kwargs):
            return f"<section-{self.market_code}/>"

    def _fail(*a, **kw):
        raise RuntimeError("cn news API down")

    monkeypatch.setattr(macro, "create_provider", lambda code: _Provider(
        code, _fail if code == "cn" else (lambda: [{"title": "news-gold"}])))
    monkeypatch.setattr(macro, "enabled_market_codes", lambda cfg: ["cn", "gold"])
    monkeypatch.setattr(macro, "_safe_regime_judge", lambda e, c: {"quadrant": "中性"})
    monkeypatch.setattr(macro, "load_config", lambda: {"recipients": [{"active": True}]})
    _patch_overseas(monkeypatch)
    macro.run_macro_report(_run_args())
    data = json.loads(capsys.readouterr().out)
    # gold 的新闻应仍在(cn 失败不中断收集)
    assert any(n.get("title") == "news-gold" for n in data["news"])


def test_run_macro_empty_markets_no_crash(monkeypatch):
    """所有市场禁用(或仅 us 启用后被排除)→ providers 空 → 不抛 StopIteration,早返回。"""
    # enabled_market_codes 返回空列表
    monkeypatch.setattr(macro, "enabled_market_codes", lambda cfg: [])
    monkeypatch.setattr(macro, "load_config", lambda: {"recipients": [{"active": True}]})
    # 不应抛异常;run_macro_report 应 logger.warning 后 return
    macro.run_macro_report(_run_args())
