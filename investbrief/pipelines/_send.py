"""Shared send helper for the macro and holdings pipelines."""
import logging
from datetime import datetime
from pathlib import Path

from investbrief.core.config import CONFIG_FILE

logger = logging.getLogger(__name__)


def send_report(report_data: dict, config: dict, recipients: list):
    """Render and send report to each recipient."""
    from investbrief.mail.render import render_template, translate_html
    from investbrief.mail.sender import EmailSender

    sender = EmailSender(str(CONFIG_FILE))

    failed = []
    for r in recipients:
        email = r["email"]
        name = r.get("name", email)
        language = r.get("language", "zh-CN")

        logger.info(f"Processing: {name} ({email}) - Language: {language}")

        html = render_template("email_base.j2", report_data, language)

        if language != "zh-CN":
            html = translate_html(html, language)

        subject = report_data.get("subject", f"【投资日报】{datetime.now().strftime('%Y年%m月%d日')}")

        try:
            sender.send(email, subject, html)
            logger.info(f"Sent successfully to {email}")
        except Exception as e:
            logger.error(f"Failed to send to {email}: {e}")
            failed.append(email)

    if failed:
        if len(failed) == len(recipients):
            raise RuntimeError(f"All {len(recipients)} recipients failed: {failed}")
        logger.warning(f"{len(failed)}/{len(recipients)} recipients failed: {failed}")
