"""Holdings report pipeline: per-recipient analysis email (distinct from macro)."""
import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from investbrief.core.config import load_config, CONFIG_FILE, REPORTS_DIR

logger = logging.getLogger(__name__)


def run_holdings_report(args):
    """Build per-recipient holdings-analysis emails and send (distinct from the macro email).

    Only recipients with a non-empty `holdings` list receive this email. Holdings are
    deduplicated across recipients so each unique symbol is analyzed once per run.
    """
    logger.info("=" * 60)
    logger.info("invest-brief - Holdings report pipeline (per-recipient)")
    config = load_config()
    recipients = [r for r in config.get("recipients", [])
                  if r.get("active", True) and r.get("holdings")]
    if not recipients:
        logger.info("No active recipients with holdings, skipping.")
        return

    from investbrief.holdings.analyzer import HoldingsAnalyzer
    from investbrief.holdings.brief import generate_holdings_brief
    from investbrief.holdings.renderer import render_holdings_section
    from investbrief.mail.render import load_template, render_holdings_template

    skip_summary = getattr(args, "skip_summary", False)

    # Collect unique holdings across recipients (analyzer caches per-key internally)
    seen: set = set()
    all_holdings: list = []
    for r in recipients:
        for h in r["holdings"]:
            key = (h["symbol"], h["market"], h["type"])
            if key not in seen:
                seen.add(key)
                all_holdings.append(h)

    logger.info(f"Analyzing {len(all_holdings)} unique holdings for {len(recipients)} recipient(s)")
    analyzer = HoldingsAnalyzer()
    by_key: dict = {}
    for h in all_holdings:
        by_key[(h["symbol"], h["market"], h["type"])] = analyzer.analyze_one(
            h["symbol"], h["market"], h["type"]
        )

    template = load_template("email_holdings.html")
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    data_time = now.strftime("%Y-%m-%d %H:%M")

    def _subset(r):
        return [by_key[(h["symbol"], h["market"], h["type"])] for h in r["holdings"]]

    # Dry run: JSON to stdout + preview HTML for the first recipient
    if getattr(args, "dry_run", False):
        logger.info("Dry run - outputting holdings data to stdout")
        try:
            first = recipients[0]
            sub = _subset(first)
            summary_html = "<p>（已跳过 AI 研判）</p>" if skip_summary else generate_holdings_brief(sub)
            preview_html = render_holdings_template(
                template,
                {"data_time": data_time,
                 "holdings_summary": summary_html,
                 "holdings_sections": render_holdings_section(sub)},
                first.get("language", "zh-CN"),
            )
            REPORTS_DIR.mkdir(exist_ok=True)
            (REPORTS_DIR / "preview_holdings.html").write_text(preview_html, encoding="utf-8")
            logger.info("Holdings preview saved to reports/preview_holdings.html")
        except Exception as e:
            logger.warning(f"Failed to render holdings preview: {e}")
        out = [{"email": r["email"], "name": r.get("name"), "language": r.get("language"),
                "holdings": [h.to_dict() for h in _subset(r)]} for r in recipients]
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
        return

    # Send per recipient
    from investbrief.mail.render import translate_html
    from investbrief.mail.sender import EmailSender
    sender = EmailSender(str(CONFIG_FILE))
    failed: list = []
    last_html = ""
    for r in recipients:
        email, name = r["email"], r.get("name", r["email"])
        language = r.get("language", "zh-CN")
        sub = _subset(r)
        summary_html = "<p>（已跳过 AI 研判）</p>" if skip_summary else generate_holdings_brief(sub)
        report_data = {
            "data_time": data_time,
            "holdings_summary": summary_html,
            "holdings_sections": render_holdings_section(sub),
        }
        html = render_holdings_template(template, report_data, language)
        if language != "zh-CN":
            html = translate_html(html, language)
        last_html = html
        subject = f"【持仓分析】{now.strftime('%Y年%m月%d日')} — {name}"
        try:
            sender.send(email, subject, html)
            logger.info(f"Holdings email sent to {email}")
        except Exception as e:
            logger.error(f"Failed to send holdings to {email}: {e}")
            failed.append(email)

    # Save preview of the last rendered email
    if last_html:
        try:
            REPORTS_DIR.mkdir(exist_ok=True)
            (REPORTS_DIR / "preview_holdings.html").write_text(last_html, encoding="utf-8")
            logger.info("Holdings preview saved to reports/preview_holdings.html")
        except Exception as e:
            logger.warning(f"Failed to save holdings preview: {e}")

    if failed:
        logger.warning(f"{len(failed)}/{len(recipients)} holdings emails failed: {failed}")
    logger.info("Holdings report pipeline complete")
