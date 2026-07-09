# tests/test_pipeline_cache.py
"""pipeline 日级缓存集成：命中跳过 build、miss 写缓存、--force 强制。"""
from unittest.mock import MagicMock


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
    class _FakeDT:
        @classmethod
        def now(cls, tz=None):
            from datetime import datetime
            return datetime(2026, 7, 10, 9, 0)
    monkeypatch.setattr(picks_mod, "datetime", _FakeDT)

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


class _FakeDT:
    """冻结到 2026-07-10 09:00 (Asia/Shanghai)。"""
    @classmethod
    def now(cls, tz=None):
        from datetime import datetime
        return datetime(2026, 7, 10, 9, 0)


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
    monkeypatch.setattr(picks_mod, "datetime", _FakeDT)
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
    monkeypatch.setattr(picks_mod, "datetime", _FakeDT)

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
