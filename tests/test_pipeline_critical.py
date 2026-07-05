"""Critical-path tests: Claude failure fallback, send resilience, cron parsing."""

from unittest.mock import MagicMock


def test_generate_macro_brief_falls_back_on_claude_failure(monkeypatch):
    """Claude 失败 → generate_macro_brief 返回兜底占位，不崩。

    Migration: generate_macro_brief now goes through call_claude, which catches
    network-class errors internally and returns None on failure — so we mock
    call_claude -> None to exercise the fallback path.
    """
    from investbrief.core import llm as llm_mod
    from investbrief.market import macro_brief

    monkeypatch.setattr(llm_mod, "call_claude", lambda *a, **kw: None)

    summary, risk = macro_brief.generate_macro_brief({"monetary_policy": {}}, {"monetary_policy": {}}, [])

    assert isinstance(summary, str) and isinstance(risk, str)
    # Fallback strings from macro_brief.generate_macro_brief
    assert summary == "<p>宏观研判生成失败，请查看下方数据。</p>"
    assert risk == "<p>风险研判生成失败。</p>"


def test_send_report_continues_after_single_failure(monkeypatch):
    """第一个收件人 send 抛异常 → 仍尝试第二个。"""
    from investbrief.pipelines._send import send_report

    config = {
        "email_service": {
            "smtp_server": "x",
            "smtp_port": 465,
            "sender_email": "a@b.c",
        }
    }
    recipients = [
        {"email": "fail@x.com", "name": "F", "language": "zh-CN"},
        {"email": "ok@x.com", "name": "O", "language": "zh-CN"},
    ]

    sender = MagicMock()
    calls = []

    def fake_send(email, subject, html):
        calls.append(email)
        if email == "fail@x.com":
            raise RuntimeError("smtp down")

    sender.send.side_effect = fake_send
    monkeypatch.setattr("investbrief.mail.sender.EmailSender", lambda *a, **k: sender)

    # send_report imports these inside the function, so patch at the source module
    import investbrief.mail.render as report_mod
    monkeypatch.setattr(report_mod, "load_template", lambda: "<html></html>")
    monkeypatch.setattr(report_mod, "render_template", lambda tpl, data, lang: "<html></html>")
    monkeypatch.setattr(report_mod, "translate_html", lambda html, lang: html)

    send_report({"subject": "s", "market_section_html": ""}, config, recipients)

    assert calls == ["fail@x.com", "ok@x.com"], (
        "second recipient must still be attempted after first fails"
    )


def test_first_enabled_cron_handles_config_shapes():
    """first_enabled_cron parses list-of-dict, dict, and old-style shapes."""
    from investbrief.pipelines.scheduler import first_enabled_cron

    # new-style: markets.us.schedule = [{"cron": "0 23 * * 1-5"}]
    c1 = {"markets": {"us": {"enabled": True, "schedule": [{"cron": "0 23 * * 1-5"}]}}}
    assert first_enabled_cron(c1) == "0 23 * * 1-5"

    # dict schedule
    c2 = {"markets": {"us": {"enabled": True, "schedule": {"cron": "30 22 * * 1-5"}}}}
    assert first_enabled_cron(c2) == "30 22 * * 1-5"

    # cn first enabled when us disabled
    c3 = {"markets": {"us": {"enabled": False}, "cn": {"enabled": True, "schedule": [{"cron": "0 23 * * 1-5"}]}}}
    assert first_enabled_cron(c3) == "0 23 * * 1-5"

    # old-style top-level
    c4 = {"schedule": {"enabled": True, "cron": "15 23 * * 1-5"}}
    assert first_enabled_cron(c4) == "15 23 * * 1-5"

    # none enabled
    assert first_enabled_cron({"markets": {}}) is None


from investbrief.pipelines.macro import _safe_regime_judge


class _BoomEngine:
    """judge() 总是抛异常,验证 _safe_regime_judge 兜底。"""
    def judge(self, market):
        raise RuntimeError("simulated DB failure")


def test_safe_regime_judge_returns_empty_on_failure():
    """RegimeEngine 异常时返回 {} → 渲染空卡片,pipeline 不阻塞。"""
    result = _safe_regime_judge(_BoomEngine(), "us")
    assert result == {}
