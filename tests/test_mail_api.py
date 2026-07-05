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
