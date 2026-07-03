"""Critical-path tests: Claude failure fallback, send resilience, cron parsing."""

from unittest.mock import MagicMock


def test_generate_macro_brief_falls_back_on_claude_failure(monkeypatch):
    """Claude 抛异常 → generate_macro_brief 返回兜底占位，不崩。"""
    from investbrief.market import macro_brief

    fake_client = MagicMock()
    fake_client.messages.create.side_effect = RuntimeError("claude down")
    monkeypatch.setattr(macro_brief, "get_client", lambda: fake_client)

    summary, risk = macro_brief.generate_macro_brief({"monetary_policy": {}}, {"monetary_policy": {}}, [])

    assert isinstance(summary, str) and isinstance(risk, str)
    # Fallback strings from macro_brief.generate_macro_brief
    assert summary == "<p>宏观研判生成失败，请查看下方数据。</p>"
    assert risk == "<p>风险研判生成失败。</p>"


def test_send_report_continues_after_single_failure(monkeypatch):
    """第一个收件人 send 抛异常 → 仍尝试第二个。"""
    import run

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

    run.send_report({"subject": "s", "market_section_html": ""}, config, recipients)

    assert calls == ["fail@x.com", "ok@x.com"], (
        "second recipient must still be attempted after first fails"
    )


def test_first_enabled_cron_handles_config_shapes():
    """_first_enabled_cron parses list-of-dict, dict, and old-style shapes."""
    import run

    # new-style: markets.us.schedule = [{"cron": "0 23 * * 1-5"}]
    c1 = {"markets": {"us": {"enabled": True, "schedule": [{"cron": "0 23 * * 1-5"}]}}}
    assert run._first_enabled_cron(c1) == "0 23 * * 1-5"

    # dict schedule
    c2 = {"markets": {"us": {"enabled": True, "schedule": {"cron": "30 22 * * 1-5"}}}}
    assert run._first_enabled_cron(c2) == "30 22 * * 1-5"

    # cn first enabled when us disabled
    c3 = {"markets": {"us": {"enabled": False}, "cn": {"enabled": True, "schedule": [{"cron": "0 23 * * 1-5"}]}}}
    assert run._first_enabled_cron(c3) == "0 23 * * 1-5"

    # old-style top-level
    c4 = {"schedule": {"enabled": True, "cron": "15 23 * * 1-5"}}
    assert run._first_enabled_cron(c4) == "15 23 * * 1-5"

    # none enabled
    assert run._first_enabled_cron({"markets": {}}) is None
