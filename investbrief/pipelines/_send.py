"""Shared send helper for the macro and holdings pipelines."""
import logging

from investbrief.core.config import CONFIG_FILE
from investbrief.core.timeutil import now_cn

logger = logging.getLogger(__name__)


def send_report(report_data: dict, config: dict, recipients: list):
    """Render and send report to each recipient (one SMTP connection for all)."""
    from investbrief.mail.render import render_template
    from investbrief.mail.sender import EmailSender

    sender = EmailSender(str(CONFIG_FILE))

    # language 被忽略(Chinese-only), report_data 对所有收件人相同 → 渲染一次复用,
    # 避免 css_inline 对每个收件人重复解析同一份 HTML
    html = render_template("email_base.j2", report_data, "zh-CN")
    subject = report_data.get("subject", f"【投资日报】{now_cn().strftime('%Y年%m月%d日')}")

    messages = []
    for r in recipients:
        email = r["email"]
        name = r.get("name", email)
        logger.info(f"Processing: {name} ({email})")
        messages.append({"to": email, "subject": subject, "html": html})

    sent, failed = sender.send_bulk(messages)
    if failed:
        failed_emails = [f[0] for f in failed]
        if len(failed) == len(recipients):
            raise RuntimeError(f"All {len(recipients)} recipients failed: {failed_emails}")
        logger.warning(f"{len(failed)}/{len(recipients)} recipients failed: {failed_emails}")
