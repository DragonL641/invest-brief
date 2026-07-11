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


def test_pipeline_iterates_all_enabled_markets(monkeypatch, capsys):
    """us 由外围卡替代(不渲染 us section);cn/gold 正常遍历。"""
    captured = _stub_providers(monkeypatch, ["us", "cn", "gold"])
    monkeypatch.setattr(macro, "load_config", lambda: {"recipients": [{"active": True}]})
    # stub overseas fetch(避免 network)
    import investbrief.market.overseas as overseas_mod
    monkeypatch.setattr(overseas_mod, "fetch_overseas_data",
                        lambda ak: {"fed_rate": 5.25, "us_10y": 4.56,
                                    "sp500": {"point": 7575, "change": 0.4}, "usdcny": 7.18})
    macro.run_macro_report(_run_args())
    data = json.loads(capsys.readouterr().out)
    rendered_codes = [c for c, _, _ in captured["rendered"]]
    assert rendered_codes == ["cn", "gold"]           # us 排除(外围卡替代)
    assert set(captured["news"]) == {"cn", "gold"}     # us news 也不取
    html = data["market_section_html"]
    assert "外围环境" in html                           # 外围卡置顶
    assert "<section-cn/>" in html and "<section-gold/>" in html
    assert "<section-us/>" not in html                 # us 不再渲染
