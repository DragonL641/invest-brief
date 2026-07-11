"""Holdings report pipeline: per-recipient analysis email (distinct from macro)."""
import json
import logging
from pathlib import Path

from investbrief.core.config import load_config, CONFIG_FILE, REPORTS_DIR, DB_PATH
from investbrief.core.timeutil import now_cn

logger = logging.getLogger(__name__)

_CACHE_PATH = str(Path(DB_PATH).with_name("holdings_cache.db"))


def run_holdings_report(args):
    """Build per-recipient holdings-analysis emails and send (distinct from the macro email).

    Only recipients with a non-empty `holdings` list receive this email. Holdings are
    deduplicated across recipients so each unique symbol is analyzed once per run.
    """
    logger.info("=" * 60)
    logger.info("invest-brief - Holdings report pipeline (per-recipient)")
    # 注入季频维度跨日缓存(rating/fundamentals/cn_activity, TTL=7d, 限流缓解)
    from investbrief.holdings.analyzer import init_cache
    init_cache(_CACHE_PATH)
    config = load_config()
    recipients = [r for r in config.get("recipients", [])
                  if r.get("active", True) and r.get("holdings")]
    if not recipients:
        logger.info("No active recipients with holdings, skipping.")
        return

    from investbrief.holdings.analyzer import HoldingsAnalyzer
    from investbrief.holdings.brief import generate_holdings_brief
    from investbrief.holdings.renderer import render_holdings_section
    from investbrief.mail.render import render_holdings_template

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

    # 机构调研 run 级批量预取：N 只 CN stock 共享一次 90 天遍历（省 N×~135s）
    cn_stock_symbols = sorted({h["symbol"] for h in all_holdings
                               if h["market"] == "cn" and h["type"] == "stock"})
    if cn_stock_symbols:
        try:
            from investbrief.datasources.akshare import AKShareClient
            batch = AKShareClient().get_institutional_research_batch(cn_stock_symbols, days=90)
            if batch:
                analyzer.set_research_batch(batch)
                logger.info(f"Prefetched institutional research batch for "
                            f"{len(cn_stock_symbols)} CN stock(s)")
        except Exception as e:
            logger.warning(f"research batch prefetch failed, falling back to per-stock: {e}")

    by_key: dict = {}
    dry_run = getattr(args, "dry_run", False)
    for h in all_holdings:
        by_key[(h["symbol"], h["market"], h["type"])] = analyzer.analyze_one(
            h["symbol"], h["market"], h["type"], with_ai=not dry_run
        )

    now = now_cn()
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
                "email_holdings.j2",
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

    # Send per recipient (one SMTP connection for all)
    from investbrief.core.mail_cache import make_key, get_cache, set_cache
    from investbrief.mail.sender import EmailSender
    sender = EmailSender(str(CONFIG_FILE))
    messages = []
    last_html = ""
    today = now.strftime("%Y-%m-%d")
    for r in recipients:
        try:
            email, name = r["email"], r.get("name", r["email"])
            language = r.get("language", "zh-CN")
            sub = _subset(r)
            # per-recipient 缓存：key 含 email + 持仓指纹（r["holdings"] 原始 dict）
            cache_key = make_key("holdings", today, email, r["holdings"])
            cached = None if getattr(args, "force", False) else get_cache(cache_key)
            if cached:
                logger.info(f"Holdings cache hit ({cache_key}), using cached HTML")
                html = cached
            else:
                summary_html = "<p>（已跳过 AI 研判）</p>" if skip_summary else generate_holdings_brief(sub)
                report_data = {
                    "data_time": data_time,
                    "holdings_summary": summary_html,
                    "holdings_sections": render_holdings_section(sub),
                }
                html = render_holdings_template("email_holdings.j2", report_data, language)
                set_cache(cache_key, html)
            last_html = html
            subject = f"【持仓分析】{now.strftime('%Y年%m月%d日')} — {name}"
            messages.append({"to": email, "subject": subject, "html": html})
        except Exception as e:
            logger.warning(f"Recipient {r.get('email')} holdings render failed, skipping: {e}")

    sent, failed = sender.send_bulk(messages)
    if failed:
        failed_emails = [f[0] for f in failed]
        if len(failed) == len(recipients):
            raise RuntimeError(f"All {len(recipients)} holdings recipients failed: {failed_emails}")
        logger.warning(f"{len(failed)}/{len(recipients)} holdings recipients failed: {failed_emails}")

    # Save preview of the last rendered email
    if last_html:
        try:
            REPORTS_DIR.mkdir(exist_ok=True)
            (REPORTS_DIR / "preview_holdings.html").write_text(last_html, encoding="utf-8")
            logger.info("Holdings preview saved to reports/preview_holdings.html")
        except Exception as e:
            logger.warning(f"Failed to save holdings preview: {e}")
    logger.info("Holdings report pipeline complete")
