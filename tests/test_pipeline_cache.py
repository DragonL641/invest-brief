# tests/test_pipeline_cache.py
"""pipeline 日级缓存集成：命中跳过 build、miss 写缓存、--force 强制。"""
import pytest
from datetime import datetime
from unittest.mock import MagicMock


def _frozen_now():
    """冻结到 2026-07-10 09:00 (Asia/Shanghai),供 monkeypatch pipeline 的 now_cn。"""
    return datetime(2026, 7, 10, 9, 0)


def _fake_recipients():
    return [{"email": "a@b.com", "name": "A", "active": True, "language": "zh-CN"}]


def test_picks_cache_hit_skips_build(tmp_path, monkeypatch):
    """预填 picks 缓存 → build_picks_for_profile 不被调，send_bulk 收到缓存 HTML。"""
    from investbrief.core import mail_cache
    from investbrief.pipelines import picks as picks_mod

    monkeypatch.setattr(mail_cache, "CACHE_DIR", tmp_path)
    today_key = "picks_2026-07-10"
    mail_cache.set_cache(today_key, "<html>CACHED</html>")

    # freeze 日期到 2026-07-10
    monkeypatch.setattr(picks_mod, "now_cn", _frozen_now)

    monkeypatch.setattr(picks_mod, "load_config",
                        lambda: {"recipients": _fake_recipients()})
    monkeypatch.setattr(picks_mod, "_data", MagicMock())  # init_cache 等 no-op

    build_called = {"n": 0}
    def fake_build(*a, **k):
        build_called["n"] += 1
        return None
    monkeypatch.setattr(picks_mod, "_safe_build", fake_build)

    sent = {}
    fake_sender = MagicMock()
    fake_sender.send_bulk = lambda msgs: sent.update(messages=msgs) or (1, [])
    monkeypatch.setattr(picks_mod, "EmailSender", lambda cfg: fake_sender)

    args = MagicMock(force=False, skip_summary=True, dry_run=False, preview=False)
    picks_mod.run_picks_report(args)

    assert build_called["n"] == 0, "命中缓存仍调用了 build"
    assert len(sent["messages"]) == 1
    assert sent["messages"][0]["html"] == "<html>CACHED</html>"


def _mock_miss_path(monkeypatch, picks_mod):
    """公共 mock：让 miss 路径跑通到 set_cache（build/render/sender 全 no-op）。"""
    monkeypatch.setattr(picks_mod, "load_config",
                        lambda: {"recipients": _fake_recipients()})
    monkeypatch.setattr(picks_mod, "_data", MagicMock())
    monkeypatch.setattr(picks_mod, "_safe_build", lambda *a, **k: None)  # build 被调但返 None
    monkeypatch.setattr(picks_mod, "_brief", MagicMock())
    monkeypatch.setattr(picks_mod, "_renderer", MagicMock())
    # render_picks_template 是 picks.run_picks_report 内的函数级 import（非模块属性），
    # 无法 monkeypatch picks_mod.render_picks_template；patch 源模块即可（local import 从那里绑定）。
    monkeypatch.setattr("investbrief.mail.render.render_picks_template",
                        lambda *a, **k: "<html>FRESH</html>")
    monkeypatch.setattr(picks_mod, "EmailSender",
                        lambda cfg: MagicMock(send_bulk=lambda m: (1, [])))


def test_picks_cache_miss_writes_cache(tmp_path, monkeypatch):
    """miss → build 被调 + set_cache 写入缓存文件。"""
    from investbrief.core import mail_cache
    from investbrief.pipelines import picks as picks_mod

    monkeypatch.setattr(mail_cache, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(picks_mod, "now_cn", _frozen_now)
    _mock_miss_path(monkeypatch, picks_mod)

    args = MagicMock(force=False, skip_summary=True, dry_run=False, preview=False)
    picks_mod.run_picks_report(args)

    assert mail_cache.get_cache("picks_2026-07-10") == "<html>FRESH</html>"  # miss 写入缓存


def test_picks_force_skips_cache_even_when_hit(tmp_path, monkeypatch):
    """预填缓存 + --force → 仍走 build（不命中缓存）。"""
    from investbrief.core import mail_cache
    from investbrief.pipelines import picks as picks_mod

    monkeypatch.setattr(mail_cache, "CACHE_DIR", tmp_path)
    mail_cache.set_cache("picks_2026-07-10", "<html>STALE</html>")
    monkeypatch.setattr(picks_mod, "now_cn", _frozen_now)

    build_called = {"n": 0}
    def fake_build(*a, **k):
        build_called["n"] += 1
        return None
    monkeypatch.setattr(picks_mod, "load_config",
                        lambda: {"recipients": _fake_recipients()})
    monkeypatch.setattr(picks_mod, "_data", MagicMock())
    monkeypatch.setattr(picks_mod, "_safe_build", fake_build)
    monkeypatch.setattr(picks_mod, "_brief", MagicMock())
    monkeypatch.setattr(picks_mod, "_renderer", MagicMock())
    monkeypatch.setattr("investbrief.mail.render.render_picks_template",
                        lambda *a, **k: "<html>FRESH</html>")
    monkeypatch.setattr(picks_mod, "EmailSender",
                        lambda cfg: MagicMock(send_bulk=lambda m: (1, [])))

    args = MagicMock(force=True, skip_summary=True, dry_run=False, preview=False)
    picks_mod.run_picks_report(args)

    assert build_called["n"] > 0, "--force 应跳过缓存走 build"


def test_picks_cache_hit_dry_run_still_builds_no_send(tmp_path, monkeypatch, capsys):
    """预填 picks 缓存 + --dry-run → 仍走 build + 打印 JSON，不查缓存不发邮件。

    回归 Critical：原缓存查询在 dry_run 守卫之前，dry_run+命中会 send_bulk 发邮件。
    """
    from investbrief.core import mail_cache
    from investbrief.pipelines import picks as picks_mod

    monkeypatch.setattr(mail_cache, "CACHE_DIR", tmp_path)
    mail_cache.set_cache("picks_2026-07-10", "<html>STALE</html>")
    monkeypatch.setattr(picks_mod, "now_cn", _frozen_now)

    build_called = {"n": 0}
    def fake_build(*a, **k):
        build_called["n"] += 1
        return None
    monkeypatch.setattr(picks_mod, "load_config",
                        lambda: {"recipients": _fake_recipients()})
    monkeypatch.setattr(picks_mod, "_data", MagicMock())
    monkeypatch.setattr(picks_mod, "_safe_build", fake_build)
    monkeypatch.setattr(picks_mod, "_brief", MagicMock())
    monkeypatch.setattr(picks_mod, "_renderer", MagicMock())

    sent = {"n": 0}
    fake_sender = MagicMock()
    fake_sender.send_bulk = lambda m: sent.update(n=sent["n"] + 1) or (1, [])
    monkeypatch.setattr(picks_mod, "EmailSender", lambda cfg: fake_sender)

    args = MagicMock(force=False, skip_summary=True, dry_run=True, preview=False)
    picks_mod.run_picks_report(args)

    assert build_called["n"] > 0, "dry_run 应走 build（不命中缓存）"
    assert sent["n"] == 0, "dry_run 不应发邮件"
    out = capsys.readouterr().out
    assert "picks" in out or "{" in out, "dry_run 应打印 JSON"


def test_macro_cache_hit_skips_build(tmp_path, monkeypatch):
    """预填 macro 缓存 → build 不被调，send_bulk 收到缓存 HTML。

    macro build 内联（refresh+fetch+risk+regime+Claude），选 generate_macro_brief
    作为"build 被调"代表——它是函数内 import，故 patch 源头模块而非 macro_mod。
    """
    from investbrief.core import mail_cache
    from investbrief.pipelines import macro as macro_mod

    monkeypatch.setattr(mail_cache, "CACHE_DIR", tmp_path)
    mail_cache.set_cache("macro_2026-07-10", "<html>MACRO</html>")

    # freeze now_cn 到 2026-07-10
    from datetime import datetime
    monkeypatch.setattr(macro_mod, "now_cn", lambda: datetime(2026, 7, 10, 9, 0))

    monkeypatch.setattr(macro_mod, "load_config",
                        lambda: {"recipients": _fake_recipients(),
                                 "markets": {"us": {"enabled": True}}, "email_service": {}})

    # generate_macro_brief 是 macro.run_macro_report 内的函数级 import，
    # 无法 monkeypatch macro_mod.generate_macro_brief；patch 源模块即可。
    build_called = {"n": 0}
    def fake_brief(*a, **k):
        build_called["n"] += 1
        return ("summary", "risk")
    monkeypatch.setattr("investbrief.market.macro_brief.generate_macro_brief", fake_brief)

    sent = {}
    fake_sender = MagicMock()
    fake_sender.send_bulk = lambda msgs: sent.update(messages=msgs) or (1, [])
    monkeypatch.setattr("investbrief.mail.sender.EmailSender", lambda cfg: fake_sender)

    # update=False 必须显式：getattr 默认返 truthy MagicMock 会进 update-only 早退分支
    args = MagicMock(force=False, skip_summary=True, dry_run=False, update=False)
    macro_mod.run_macro_report(args)

    assert build_called["n"] == 0, "命中缓存仍调 generate_macro_brief"
    assert sent["messages"][0]["html"] == "<html>MACRO</html>"


@pytest.mark.network  # 完整 macro pipeline dry-run，漏 mock overseas/news 拉取 → 触网（缓存逻辑本身 hermetic，理想应补 mock，留 followup）
def test_macro_cache_miss_writes_cache(tmp_path, monkeypatch):
    """miss → build 被调 + set_cache 写入缓存文件。

    macro build 内联且依赖众多（providers/refresh/risk/regime/news/calendar），
    用最小 fake provider 走完空 build（无 macro 数据、跳 risk/regime）+
    skip_summary=True（跳过 Claude）+ patch send_report（不发邮件）+
    patch render_template（返固定 html，不依赖 Jinja2 模板）。
    """
    from investbrief.core import mail_cache
    from investbrief.pipelines import macro as macro_mod

    monkeypatch.setattr(mail_cache, "CACHE_DIR", tmp_path)
    from datetime import datetime
    monkeypatch.setattr(macro_mod, "now_cn", lambda: datetime(2026, 7, 10, 9, 0))

    monkeypatch.setattr(macro_mod, "load_config",
                        lambda: {"recipients": _fake_recipients(),
                                 "markets": {"us": {"enabled": True}}, "email_service": {}})

    # fake provider：所有 macro getter 返空，risk_group/supports_regime falsy 跳过两段
    fake_provider = MagicMock()
    fake_provider.refresh = lambda: None
    fake_provider.get_monetary_policy = lambda: {}
    fake_provider.get_asset_performance = lambda: {}
    fake_provider.get_economic_calendar = lambda: {}
    fake_provider.get_news = lambda config, limit: []
    fake_provider.risk_group = None        # falsy → 跳过 risk 循环
    fake_provider.supports_regime = False  # falsy → 跳过 regime 循环
    fake_provider.data = MagicMock(close=lambda: None)
    fake_provider.render_section = lambda *a, **k: ""
    monkeypatch.setattr(macro_mod, "create_provider", lambda code: fake_provider)

    # send_report 不发邮件（miss 测试只关心 set_cache 是否写）。
    # send_report 是 macro.run_macro_report 内的函数级 import（非 macro_mod 属性），
    # patch 源头即可（local import 从那里绑定）。
    monkeypatch.setattr("investbrief.pipelines._send.send_report", lambda *a, **k: None)
    # preview render 返固定 html（不依赖 Jinja2 模板/REPORTS_DIR）
    monkeypatch.setattr("investbrief.mail.render.render_template",
                        lambda *a, **k: "<html>FRESH</html>")

    args = MagicMock(force=False, skip_summary=True, dry_run=False, update=False)
    macro_mod.run_macro_report(args)

    assert mail_cache.get_cache("macro_2026-07-10") == "<html>FRESH</html>"  # miss 写入缓存


@pytest.mark.network  # 同上：完整 macro pipeline dry-run，漏 mock overseas/news → 触网
def test_macro_cache_hit_dry_run_still_builds_no_send(tmp_path, monkeypatch, capsys):
    """预填 macro 缓存 + --dry-run → 仍走 build + 打印 JSON，不查缓存不发邮件。

    回归 Critical：原缓存查询在 dry_run 守卫之前，dry_run+命中会 send_bulk 发邮件。
    skip_summary=True 跳过 generate_macro_brief/research，故用 create_provider 调用
    作为"build 被调"信号（create_provider 在缓存检查之后才执行）。
    """
    from investbrief.core import mail_cache
    from investbrief.pipelines import macro as macro_mod

    monkeypatch.setattr(mail_cache, "CACHE_DIR", tmp_path)
    mail_cache.set_cache("macro_2026-07-10", "<html>STALE</html>")
    from datetime import datetime
    monkeypatch.setattr(macro_mod, "now_cn", lambda: datetime(2026, 7, 10, 9, 0))

    monkeypatch.setattr(macro_mod, "load_config",
                        lambda: {"recipients": _fake_recipients(),
                                 "markets": {"us": {"enabled": True}}, "email_service": {}})

    # fake provider：所有 macro getter 返空，risk_group/supports_regime falsy 跳过两段
    fake_provider = MagicMock()
    fake_provider.refresh = lambda: None
    fake_provider.get_monetary_policy = lambda: {}
    fake_provider.get_asset_performance = lambda: {}
    fake_provider.get_economic_calendar = lambda: {}
    fake_provider.get_news = lambda config, limit: []
    fake_provider.risk_group = None
    fake_provider.supports_regime = False
    fake_provider.data = MagicMock(close=lambda: None)
    fake_provider.render_section = lambda *a, **k: ""

    build_called = {"n": 0}
    def fake_create(code):
        build_called["n"] += 1
        return fake_provider
    monkeypatch.setattr(macro_mod, "create_provider", fake_create)

    sent = {"n": 0}
    fake_sender = MagicMock()
    fake_sender.send_bulk = lambda m: sent.update(n=sent["n"] + 1) or (1, [])
    monkeypatch.setattr("investbrief.mail.sender.EmailSender", lambda cfg: fake_sender)

    args = MagicMock(force=False, skip_summary=True, dry_run=True, update=False)
    macro_mod.run_macro_report(args)

    assert build_called["n"] > 0, "dry_run 应走 build（不命中缓存）"
    assert sent["n"] == 0, "dry_run 不应发邮件"
    out = capsys.readouterr().out
    assert "macro_summary" in out or "{" in out, "dry_run 应打印 JSON"


def test_holdings_cache_hit_per_recipient_skips_analysis(tmp_path, monkeypatch):
    """recipient A 缓存命中（跳过其 brief/render），recipient C 未命中（走分析）。

    holdings 缓存是 per-recipient（key 含 email + 持仓指纹），与 macro/picks 的
    广播缓存不同 —— 命中只跳过该 recipient 的 generate_holdings_brief +
    render_holdings_section + render_holdings_template，整个 pipeline 仍跑完。
    """
    from investbrief.core import mail_cache
    from investbrief.pipelines import holdings as h_mod

    monkeypatch.setattr(mail_cache, "CACHE_DIR", tmp_path)

    # 冻结日期到 2026-07-10（holdings 用 datetime.now(ZoneInfo) 算 today；模块级 datetime）
    monkeypatch.setattr(h_mod, "now_cn", _frozen_now)

    recipients = [
        {"email": "a@b.com", "name": "A", "active": True, "language": "zh-CN",
         "holdings": [{"symbol": "AMD", "market": "us", "type": "stock"}]},
        {"email": "c@d.com", "name": "C", "active": True, "language": "zh-CN",
         "holdings": [{"symbol": "NVDA", "market": "us", "type": "stock"}]},
    ]
    monkeypatch.setattr(h_mod, "load_config", lambda: {"recipients": recipients})

    # 预填 A 的缓存（key 含 email + 持仓指纹，指纹输入是 r["holdings"] 原始 dict 列表）
    a_key = mail_cache.make_key("holdings", "2026-07-10", "a@b.com", recipients[0]["holdings"])
    mail_cache.set_cache(a_key, "<html>A-CACHED</html>")

    # 所有辅助函数都是 run_holdings_report 内的函数级 import → patch 源头模块
    monkeypatch.setattr("investbrief.holdings.analyzer.init_cache", lambda *a, **k: None)
    fake_analyzer = MagicMock()
    fake_analyzer.analyze_one = lambda *a, **k: MagicMock()  # HoldingResult 占位
    monkeypatch.setattr("investbrief.holdings.analyzer.HoldingsAnalyzer", lambda: fake_analyzer)

    analyze_called = {"n": 0}
    def fake_brief(sub):
        analyze_called["n"] += 1
        return "<p>brief</p>"
    monkeypatch.setattr("investbrief.holdings.brief.generate_holdings_brief", fake_brief)

    monkeypatch.setattr("investbrief.holdings.renderer.render_holdings_section",
                        lambda sub: "<div>sections</div>")
    monkeypatch.setattr("investbrief.mail.render.render_holdings_template",
                        lambda *a, **k: "<html>FRESH</html>")

    sent = {}
    fake_sender = MagicMock()
    fake_sender.send_bulk = lambda msgs: sent.update(messages=msgs) or (2, [])
    monkeypatch.setattr("investbrief.mail.sender.EmailSender", lambda cfg: fake_sender)

    args = MagicMock(force=False, skip_summary=False, dry_run=False)
    h_mod.run_holdings_report(args)

    # A 命中（不分析），C 未命中（分析）→ generate_holdings_brief 只调 1 次
    assert analyze_called["n"] == 1, (
        f"应有 1 个 recipient 命中跳过分析，实际 brief 调用 {analyze_called['n']} 次")
    htmls = {m["to"]: m["html"] for m in sent["messages"]}
    assert htmls["a@b.com"] == "<html>A-CACHED</html>"  # A 用缓存
    assert htmls["c@d.com"] == "<html>FRESH</html>"     # C 走 miss 路径


def test_holdings_cache_miss_writes_per_recipient(tmp_path, monkeypatch):
    """miss → 走分析 + set_cache 为该 recipient 写入缓存文件。"""
    from investbrief.core import mail_cache
    from investbrief.pipelines import holdings as h_mod

    monkeypatch.setattr(mail_cache, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(h_mod, "now_cn", _frozen_now)

    recipients = [{"email": "a@b.com", "name": "A", "active": True, "language": "zh-CN",
                   "holdings": [{"symbol": "AMD", "market": "us", "type": "stock"}]}]
    monkeypatch.setattr(h_mod, "load_config", lambda: {"recipients": recipients})

    monkeypatch.setattr("investbrief.holdings.analyzer.init_cache", lambda *a, **k: None)
    fake_analyzer = MagicMock()
    fake_analyzer.analyze_one = lambda *a, **k: MagicMock()
    monkeypatch.setattr("investbrief.holdings.analyzer.HoldingsAnalyzer", lambda: fake_analyzer)
    monkeypatch.setattr("investbrief.holdings.brief.generate_holdings_brief",
                        lambda sub: "<p>brief</p>")
    monkeypatch.setattr("investbrief.holdings.renderer.render_holdings_section",
                        lambda sub: "<div>sections</div>")
    monkeypatch.setattr("investbrief.mail.render.render_holdings_template",
                        lambda *a, **k: "<html>FRESH</html>")
    monkeypatch.setattr("investbrief.mail.sender.EmailSender",
                        lambda cfg: MagicMock(send_bulk=lambda m: (1, [])))

    args = MagicMock(force=False, skip_summary=False, dry_run=False)
    h_mod.run_holdings_report(args)

    a_key = mail_cache.make_key("holdings", "2026-07-10", "a@b.com", recipients[0]["holdings"])
    assert mail_cache.get_cache(a_key) == "<html>FRESH</html>"  # miss 写入 per-recipient 缓存


def test_holdings_force_skips_cache_even_when_hit(tmp_path, monkeypatch):
    """预填 A 缓存 + --force → A 仍走分析（不命中缓存）。"""
    from investbrief.core import mail_cache
    from investbrief.pipelines import holdings as h_mod

    monkeypatch.setattr(mail_cache, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(h_mod, "now_cn", _frozen_now)

    recipients = [{"email": "a@b.com", "name": "A", "active": True, "language": "zh-CN",
                   "holdings": [{"symbol": "AMD", "market": "us", "type": "stock"}]}]
    monkeypatch.setattr(h_mod, "load_config", lambda: {"recipients": recipients})

    a_key = mail_cache.make_key("holdings", "2026-07-10", "a@b.com", recipients[0]["holdings"])
    mail_cache.set_cache(a_key, "<html>STALE</html>")

    monkeypatch.setattr("investbrief.holdings.analyzer.init_cache", lambda *a, **k: None)
    fake_analyzer = MagicMock()
    fake_analyzer.analyze_one = lambda *a, **k: MagicMock()
    monkeypatch.setattr("investbrief.holdings.analyzer.HoldingsAnalyzer", lambda: fake_analyzer)

    brief_called = {"n": 0}
    def fake_brief(sub):
        brief_called["n"] += 1
        return "<p>brief</p>"
    monkeypatch.setattr("investbrief.holdings.brief.generate_holdings_brief", fake_brief)
    monkeypatch.setattr("investbrief.holdings.renderer.render_holdings_section",
                        lambda sub: "<div>sections</div>")
    monkeypatch.setattr("investbrief.mail.render.render_holdings_template",
                        lambda *a, **k: "<html>FRESH</html>")
    monkeypatch.setattr("investbrief.mail.sender.EmailSender",
                        lambda cfg: MagicMock(send_bulk=lambda m: (1, [])))

    args = MagicMock(force=True, skip_summary=False, dry_run=False)
    h_mod.run_holdings_report(args)

    assert brief_called["n"] > 0, "--force 应跳过缓存走分析"
