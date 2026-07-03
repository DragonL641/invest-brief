"""Smoke for mail package public API."""
from investbrief.mail.sender import EmailSender
from investbrief.mail.render import (
    load_template, render_template, render_holdings_template, translate_html,
)


def test_mail_api_present():
    assert EmailSender is not None
    assert callable(load_template)
    assert callable(render_template)
    assert callable(render_holdings_template)
    assert callable(translate_html)


def test_load_template_finds_email_base():
    html = load_template("email_base.html")
    assert "macro_summary" in html or "{{macro_summary}}" in html  # template placeholder present
