import json
import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

CONFIG_FILE = Path(__file__).resolve().parent.parent.parent.parent / "config.json"


def send_email_for_user(market: str, user_config: dict) -> dict:
    """Run the email pipeline for a single user and single market."""
    try:
        from investbrief.core.mailer import EmailSender
        from investbrief.report import load_template, render_template, translate_html

        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)

        market_cfg = user_config.get("markets", {}).get(market, {})
        holdings = market_cfg.get("holdings", [])
        industries = market_cfg.get("industries", [])
        symbols = [h.get("symbol", "") for h in holdings]

        if not holdings and not industries:
            return {"status": "skipped", "message": f"No holdings or industries configured for {market}"}

        if market == "us":
            from investbrief.us.provider import USMarketProvider
            provider = USMarketProvider()
        elif market == "cn":
            from investbrief.cn.provider import CNMarketProvider
            provider = CNMarketProvider()
        else:
            return {"status": "error", "message": f"Unknown market: {market}"}

        max_recs = market_cfg.get("max_recommendations", 3)
        market_data = provider.fetch_all(holdings, industries, max_recs)

        news = []
        try:
            if market == "us":
                from investbrief.us.news import DataProvider
                dp = DataProvider(config)
                news = dp.get_financial_news(tickers=symbols, limit=20, user_tickers=symbols, industries=industries)
            elif market == "cn":
                from investbrief.cn.news import fetch_cn_news
                news = fetch_cn_news(symbols, industries, 20)
                for item in news:
                    if "date" in item and "time" not in item:
                        item["time"] = item["date"]
        except Exception as e:
            logger.warning(f"News fetch failed: {e}")

        render_config = {"color_up": "#e74c3c", "color_down": "#27ae60"}
        try:
            market_html = provider.render_section(market_data, render_config)
        except Exception as e:
            logger.warning(f"HTML render failed: {e}")
            market_html = "<p>Market data render failed.</p>"

        market_names = {"us": "US Daily", "cn": "A-Share Daily"}
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        report_data = {
            "subject": f"[{market_names.get(market, 'Invest Daily')}] {now.year}-{now.month}-{now.day}",
            "data_time": now.strftime("%Y-%m-%d %H:%M"),
            "date": now.strftime("%Y-%m-%d"),
            "global_metrics": [],
            "market_section_html": market_html,
            "news": news,
            "market": market,
        }

        template = load_template()
        language = user_config.get("language", "zh-CN")

        delivery = user_config.get("delivery")
        if not delivery:
            delivery = [{"email": user_config["email"], "language": language, "schedule": {}}]

        sender = EmailSender(str(CONFIG_FILE))
        sent_count = 0

        for target in delivery:
            target_email = target["email"]
            target_lang = target.get("language", language)

            html = render_template(template, report_data, target_lang, {})
            if target_lang != "zh-CN":
                try:
                    html = translate_html(html, target_lang)
                except Exception as e:
                    logger.warning(f"Translation failed for {target_email}: {e}")

            subject = report_data.get("subject", "Invest Daily")
            try:
                sender.send(target_email, subject, html)
                sent_count += 1
                logger.info(f"Email sent to {target_email}")
            except Exception as e:
                logger.error(f"Failed to send to {target_email}: {e}")

        return {"status": "ok", "message": f"Sent {sent_count} email(s) for {market}"}

    except Exception as e:
        logger.error(f"Email pipeline failed: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}
