"""Smoke for mail package public API."""
from investbrief.mail.sender import EmailSender
from investbrief.mail.render import (
    load_template, render_template, render_holdings_template,
)


def test_mail_api_present():
    assert EmailSender is not None
    assert callable(load_template)
    assert callable(render_template)
    assert callable(render_holdings_template)


def test_load_template_finds_email_base():
    html = load_template("email_base.j2")
    assert "macro_summary" in html or "{{macro_summary}}" in html  # template placeholder present


def test_render_template_substitutes_placeholders():
    """Jinja2 render path: placeholders substituted, HTML preserved (autoescape=False)."""
    from investbrief.mail.render import render_template
    html = render_template("email_base.j2", {
        "macro_summary": "<p>TEST_MARK</p>",
        "market_section_html": "",
        "research_views": "",
        "news": [],
    }, "zh-CN")
    assert "TEST_MARK" in html
    assert "{{macro_summary}}" not in html  # placeholder replaced, not leaked
    assert "<p>TEST_MARK</p>" in html       # autoescape=False preserves HTML


def test_send_bulk_one_connection_partial_failure(monkeypatch):
    """send_bulk: one SMTP connection, per-message failure doesn't block others."""
    from investbrief.mail.sender import EmailSender

    # Construct EmailSender minimally — avoid reading real config.json
    fake = EmailSender.__new__(EmailSender)
    fake.sender_email = "a@x.com"
    fake.sender_name = "A"
    fake.app_password = "pw"
    fake.use_ssl = True

    connects = []
    sends = []

    class _FakeServer:
        def login(self, *a): pass
        def sendmail(self, frm, to, raw):
            sends.append(to)
            if to == "fail@x.com":
                raise RuntimeError("smtp down for one")
        def quit(self): pass

    def _create_conn(*a, **k):
        connects.append(1)
        return _FakeServer()

    fake._create_connection = _create_conn  # bypass real SSL

    messages = [
        {"to": "ok1@x.com", "subject": "s", "html": "<p>1</p>"},
        {"to": "fail@x.com", "subject": "s", "html": "<p>2</p>"},
        {"to": "ok2@x.com", "subject": "s", "html": "<p>3</p>"},
    ]
    sent, failed = fake.send_bulk(messages)
    assert sent == 2
    assert len(failed) == 1 and failed[0][0] == "fail@x.com"
    assert len(connects) == 1  # only ONE connection for all 3 messages
    assert sends == ["ok1@x.com", "fail@x.com", "ok2@x.com"]  # all attempted despite mid-failure
