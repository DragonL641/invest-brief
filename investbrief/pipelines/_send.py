"""Shared send helper for the macro and holdings pipelines."""
import logging
from datetime import datetime

from investbrief.core.config import CONFIG_FILE

logger = logging.getLogger(__name__)


def send_report(report_data: dict, config: dict, recipients: list):
    """Render and send report to each recipient (one SMTP connection for all)."""
    from investbrief.mail.render import render_template
    from investbrief.mail.sender import EmailSender

    sender = EmailSender(str(CONFIG_FILE))

    messages = []
    for r in recipients:
        email = r["email"]
        name = r.get("name", email)
        language = r.get("language", "zh-CN")
        logger.info(f"Processing: {name} ({email}) - Language: {language}")
        html = render_template("email_base.j2", report_data, language)
        subject = report_data.get("subject", f"【投资日报】{datetime.now().strftime('%Y年%m月%d日')}")
        messages.append({"to": email, "subject": subject, "html": html})

    sent, failed = sender.send_bulk(messages)
    if failed:
        failed_emails = [f[0] for f in failed]
        if len(failed) == len(recipients):
            raise RuntimeError(f"All {len(recipients)} recipients failed: {failed_emails}")
        logger.warning(f"{len(failed)}/{len(recipients)} recipients failed: {failed_emails}")
