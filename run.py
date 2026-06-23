# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "yfinance",
#   "requests",
#   "anthropic",
#   "python-dotenv",
#   "matplotlib",
#   "croniter",
#   "akshare",
# ]
# ///

"""
Entry point for invest-brief.

Usage:
    uv run run.py --market us --now           # Run US market once immediately
    uv run run.py --market cn --now           # Run CN market once immediately
    uv run run.py --market all --now          # Run all markets once immediately
    uv run run.py --market us --dry-run       # Build US report, output to stdout
    uv run run.py --market us --skip-summary  # Skip Claude API summary
    uv run run.py --market us                 # Scheduler mode (cron-based)
"""

import sys
import json
import os
import signal
import argparse
import logging
import time
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from croniter import croniter

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent
ENV_FILE = PROJECT_DIR / ".env"
CONFIG_FILE = PROJECT_DIR / "config.json"

load_dotenv(ENV_FILE, override=False)

# Auto-detect system proxy for yfinance / requests (macOS system proxy)
if not os.environ.get("HTTPS_PROXY"):
    import subprocess
    try:
        r = subprocess.run(
            ["networksetup", "-getsecurewebproxy", "Wi-Fi"],
            capture_output=True, text=True, timeout=3,
        )
        enabled = "Enabled: Yes" in r.stdout
        if enabled:
            host = port = ""
            for line in r.stdout.splitlines():
                if line.startswith("Server:"):
                    host = line.split(":", 1)[1].strip()
                elif line.startswith("Port:"):
                    port = line.split(":", 1)[1].strip()
            proxy = f"http://{host}:{port}"
            os.environ.setdefault("HTTP_PROXY", proxy)
            os.environ.setdefault("HTTPS_PROXY", proxy)
    except Exception:
        pass

# Bypass proxy for AKShare data sources (eastmoney)
_no_proxy = os.environ.get("NO_PROXY", "")
_eastmoney_domains = ".eastmoney.com,.push2.eastmoney.com,.push2his.eastmoney.com,.push2delay.eastmoney.com"
if _no_proxy:
    os.environ["NO_PROXY"] = f"{_no_proxy},{_eastmoney_domains}"
else:
    os.environ["NO_PROXY"] = _eastmoney_domains

# Ensure ANTHROPIC_AUTH_TOKEN is available as ANTHROPIC_API_KEY for anthropic SDK
if not os.environ.get("ANTHROPIC_API_KEY") and os.environ.get("ANTHROPIC_AUTH_TOKEN"):
    os.environ["ANTHROPIC_API_KEY"] = os.environ["ANTHROPIC_AUTH_TOKEN"]

logger = logging.getLogger("run")

# Graceful shutdown flag
_shutdown = False

NEWS_LIMIT = 5


def _handle_signal(signum, frame):
    global _shutdown
    sig_name = signal.Signals(signum).name
    logger.info(f"Received {sig_name}, shutting down gracefully...")
    _shutdown = True


# ============================================================================
# Config
# ============================================================================

def load_config() -> dict:
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)
    _validate_config(config)
    return config


def _validate_config(config: dict):
    """Validate required config fields with clear error messages."""
    if "email_service" not in config:
        raise ValueError("config.json missing 'email_service' section")
    email_cfg = config["email_service"]
    for key in ("smtp_server", "smtp_port", "sender_email"):
        if key not in email_cfg:
            raise ValueError(f"config.json email_service missing '{key}'")
    if "recipients" not in config or not config["recipients"]:
        raise ValueError("config.json missing or empty 'recipients' list")


# ============================================================================
# Provider factory
# ============================================================================

def _create_provider(market: str):
    """Create a market provider instance."""
    if market == "us":
        from investbrief.us.provider import USMarketProvider
        return USMarketProvider()
    elif market == "cn":
        from investbrief.cn.provider import CNMarketProvider
        return CNMarketProvider()
    else:
        raise ValueError(f"Unknown market: {market}")


# ============================================================================
# News fetching (market-aware)
# ============================================================================

def fetch_news(config, tickers, max_news_count, industries, market="us"):
    """Fetch news for the specified market."""
    if market == "us":
        from investbrief.us.news import DataProvider
        provider = DataProvider(config)
        return provider.get_financial_news(
            tickers=tickers,
            limit=max_news_count,
            user_tickers=tickers,
            industries=industries,
        )
    elif market == "cn":
        from investbrief.cn.news import fetch_cn_news
        return fetch_cn_news(tickers, industries, max_news_count)
    return []


# ============================================================================
# Global metrics
# ============================================================================

def build_global_metrics(indices):
    metrics = []
    for idx in indices:
        metrics.append({
            "label": idx["name"],
            "value": f"{idx['change'] or 0:+.2f}%",
            "change": idx["change"],
        })
    return metrics


# ============================================================================
# Macro report prompts (merged US+CN)
# ============================================================================

MACRO_SUMMARY_PROMPT = """你是一位资深宏观经济分析师，为投资者撰写每日中美宏观市场简报。

基于提供的中美宏观数据，输出纯 HTML（<p> 与 <strong>，不要 markdown、不要列表标记），分 4 段：
1. 宏观环境：中美经济数据信号（CPI/PMI/就业等）、增长与通胀走向
2. 货币政策：美联储 vs 中国央行立场、美债收益率、中美利差含义
3. 大类资产：美股/A股/债市/汇率/商品走势逻辑与轮动
4. 风险与机会：最需关注的事件、潜在拐点
要求：每段 2-3 句，关键数字用 <strong>，总字数 400-600，只用提供的数据不编造，第一段首句给整体方向（偏多/偏空/中性）。"""

RISK_OUTLOOK_PROMPT = """基于以下中美经济日历与宏观数据，列出未来一周需关注的风险事件与关注点。输出 HTML（<p> 或 <ul><li>），150字以内，中文，关键事件用 <strong>。"""


# ============================================================================
# Macro report Claude ①⑥
# ============================================================================

def _serialize_macro_context(us_data: dict, cn_data: dict, news: list) -> str:
    """Build compact text context from US+CN macro data for Claude."""
    lines = []

    def _emit_market(label: str, md: dict):
        lines.append(f"## {label}")
        mp = md.get("monetary_policy") or {}
        if mp:
            for k, v in mp.items():
                lines.append(f"- {k}: {v}")
        ap = md.get("asset_performance") or []
        if ap:
            lines.append("### 大类资产表现")
            for a in ap[:8]:
                name = a.get("name", "")
                change = a.get("change")
                try:
                    change_str = f"{change:+.2f}%" if change is not None else "-"
                except (TypeError, ValueError):
                    change_str = str(change) if change is not None else "-"
                lines.append(f"- {name}: {change_str}")
        ec = md.get("economic_calendar") or []
        if ec:
            lines.append("### 经济日历")
            for e in ec[:8]:
                ev = e.get("event") or e.get("name", "")
                dt = e.get("date", "")
                forecast = e.get("forecast", "")
                previous = e.get("previous", "")
                lines.append(f"- {dt} {ev} (预期:{forecast or 'N/A'}, 前值:{previous or 'N/A'})")

    _emit_market("美国宏观", us_data)
    _emit_market("中国宏观", cn_data)

    if news:
        lines.append("\n## 重要新闻")
        for n in news[:5]:
            lines.append(f"- {n.get('title', '')} ({n.get('source', '')})")

    return "\n".join(lines)


def generate_macro_summary(us_data: dict, cn_data: dict, news: list) -> str:
    """Generate the ① macro core-view summary (merged US+CN) via Claude."""
    try:
        from investbrief.core.llm import get_client, default_model

        client = get_client()
        context = _serialize_macro_context(us_data, cn_data, news)

        response = client.messages.create(
            model=default_model(),
            max_tokens=2048,
            temperature=0.3,
            system=MACRO_SUMMARY_PROMPT,
            messages=[{"role": "user", "content": context}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        logger.warning(f"Macro summary generation failed: {e}")
        return "<p>宏观研判生成失败，请查看下方数据。</p>"


def generate_risk_outlook(us_data: dict, cn_data: dict) -> str:
    """Generate the ⑥ risk & outlook block (merged US+CN) via Claude."""
    try:
        from investbrief.core.llm import get_client, default_model

        client = get_client()
        context = _serialize_macro_context(us_data, cn_data, [])

        response = client.messages.create(
            model=default_model(),
            max_tokens=512,
            temperature=0.3,
            system=RISK_OUTLOOK_PROMPT,
            messages=[{"role": "user", "content": context}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        logger.warning(f"Risk outlook generation failed: {e}")
        return "<p>风险研判生成失败。</p>"


# ============================================================================
# Send report
# ============================================================================

def send_report(report_data: dict, config: dict, recipients: list):
    """Render and send report to each recipient."""
    from investbrief.report import load_template, render_template, translate_html
    from investbrief.core.mailer import EmailSender

    template = load_template()

    # Build render config from email_service section for color settings
    email_cfg = config.get("email_service", {})
    render_config = {
        "color_up": "#e74c3c",
        "color_down": "#27ae60",
    }

    sender = EmailSender(str(CONFIG_FILE))

    for r in recipients:
        email = r["email"]
        name = r.get("name", email)
        language = r.get("language", "zh-CN")

        logger.info(f"Processing: {name} ({email}) - Language: {language}")

        html = render_template(template, report_data, language, r.get("settings", {}))

        if language != "zh-CN":
            html = translate_html(html, language)

        subject = report_data.get("subject", f"【投资日报】{datetime.now().strftime('%Y年%m月%d日')}")

        try:
            sender.send(email, subject, html)
            logger.info(f"Sent successfully to {email}")
        except Exception as e:
            logger.error(f"Failed to send to {email}: {e}")



# ============================================================================
# Macro report pipeline (merged US+CN)
# ============================================================================

def _run_macro_report(args):
    """Build ONE merged US+CN macro report and send to all active recipients."""
    logger.info("=" * 60)
    logger.info("invest-brief - Macro report pipeline (US+CN merged)")

    config = load_config()
    recipients = [r for r in config.get("recipients", []) if r.get("active", True)]
    if not recipients:
        logger.info("No active recipients, skipping.")
        return

    render_config = {"color_up": "#e74c3c", "color_down": "#27ae60"}
    skip_summary = getattr(args, "skip_summary", False)

    # Fetch macro data
    logger.info("Fetching macro data (US + CN)")
    us = _create_provider("us")
    cn = _create_provider("cn")
    from investbrief.us.calendar import get_upcoming_events_with_yfinance
    from investbrief.cn.calendar import get_upcoming_events as get_cn_events
    us_data = {
        "monetary_policy": us.get_monetary_policy(),
        "asset_performance": us.get_asset_performance(),
        "economic_calendar": get_upcoming_events_with_yfinance(),
    }
    cn_data = {
        "monetary_policy": cn.get_monetary_policy(),
        "asset_performance": cn.get_asset_performance(),
        "economic_calendar": get_cn_events(),
    }

    # News (US + CN, no tickers)
    news = []
    try:
        news = fetch_news(config, [], NEWS_LIMIT, [], market="us") + \
            fetch_news(config, [], NEWS_LIMIT, [], market="cn")
        news = news[:NEWS_LIMIT]
    except Exception as e:
        logger.warning(f"News fetch failed: {e}")

    # Claude ①⑥
    if skip_summary:
        logger.info("Skipping Claude summary (--skip-summary)")
        macro_summary = "<p>（已跳过 AI 研判）</p>"
        risk_outlook = "<p>—</p>"
    else:
        logger.info("Generating macro summary via Claude (①)")
        macro_summary = generate_macro_summary(us_data, cn_data, news)
        logger.info("Generating risk outlook via Claude (⑥)")
        risk_outlook = generate_risk_outlook(us_data, cn_data)

    # Render sections
    us_html = us.render_section(us_data, render_config)
    cn_html = cn.render_section(cn_data, render_config)

    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    report_data = {
        "subject": f"【宏观经济日报】{now.year}年{now.month}月{now.day}日",
        "data_time": now.strftime("%Y-%m-%d %H:%M"),
        "date": now.strftime("%Y-%m-%d"),
        "market": "all",
        "macro_summary": macro_summary,
        "risk_outlook": risk_outlook,
        "market_section_html": us_html + cn_html,
        "news": news,
        "global_metrics": build_global_metrics(us_data.get("asset_performance", [])[:4]),
    }

    if getattr(args, "dry_run", False):
        logger.info("Dry run - outputting report data to stdout")
        print(json.dumps(report_data, ensure_ascii=False, indent=2, default=str))
        return

    send_report(report_data, config, recipients)

    # Save local preview
    try:
        from investbrief.report import load_template, render_template
        preview_dir = Path(__file__).parent / "reports"
        preview_dir.mkdir(exist_ok=True)
        template = load_template()
        preview_html = render_template(template, report_data, "zh-CN", {})
        preview_path = preview_dir / "preview_macro.html"
        preview_path.write_text(preview_html, encoding="utf-8")
        logger.info(f"Preview saved to {preview_path}")
    except Exception as e:
        logger.warning(f"Failed to save preview: {e}")

    logger.info("Macro report pipeline complete")


# ============================================================================
# Run Once (immediate execution)
# ============================================================================

def run_once(args):
    """Execute the macro pipeline (always merged US+CN)."""
    _run_macro_report(args)


# ============================================================================
# Scheduler (cron-based long-running process)
# ============================================================================

def run_scheduler(config):
    """Run as a long-lived process, executing ONE merged macro report at cron-scheduled times.

    The macro pipeline always merges US+CN, so only a single scheduler thread is started
    using the first enabled market's cron expression to avoid double-sending.
    """
    cron_expr = _first_enabled_cron(config)
    if cron_expr is None:
        logger.error("No enabled markets found in config; nothing to schedule")
        return

    t = threading.Thread(
        target=_run_scheduled_macro,
        args=(cron_expr,),
        name="scheduler-macro",
        daemon=True,
    )
    t.start()

    while not _shutdown:
        time.sleep(1)


def _first_enabled_cron(config: dict) -> str | None:
    """Return the cron expression of the first enabled market (us preferred), else None."""
    markets_cfg = config.get("markets", {})
    for market in ("us", "cn"):
        cfg = markets_cfg.get(market, {})
        if not cfg.get("enabled", False):
            continue
        raw = cfg.get("schedule")
        if isinstance(raw, list):
            if raw:
                return raw[0].get("cron", "0 23 * * 1-5")
        elif isinstance(raw, dict):
            return raw.get("cron", "0 23 * * 1-5")
    # Fallback: old-style top-level schedule
    schedule_cfg = config.get("schedule", {})
    if schedule_cfg.get("enabled", False):
        return schedule_cfg.get("cron", "0 23 * * 1-5")
    return None


def _run_scheduled_macro(cron_expr: str):
    """Run the merged macro report loop on a single cron schedule."""
    if not croniter.is_valid(cron_expr):
        logger.error(f"Invalid cron expression: {cron_expr}")
        return

    tz = ZoneInfo("Asia/Shanghai")
    now = datetime.now(tz)
    cron = croniter(cron_expr, now)
    next_run = cron.get_next(datetime)

    logger.info(f"Scheduler started with cron: '{cron_expr}'")
    logger.info(f"Next run scheduled at: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")

    while not _shutdown:
        now = datetime.now(tz)

        if now >= next_run:
            logger.info("=" * 60)
            logger.info("Scheduled macro report run triggered")

            args = argparse.Namespace(
                market="all",
                dry_run=False,
                skip_summary=False,
                log_level=logging.getLevelName(logger.getEffectiveLevel()),
            )

            try:
                _run_macro_report(args)
            except Exception as e:
                logger.error(f"Scheduled run failed: {e}", exc_info=True)

            cron = croniter(cron_expr, now)
            next_run = cron.get_next(datetime)
            logger.info(f"Next run scheduled at: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")

        time.sleep(30)

    logger.info("Scheduler stopped")


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="invest-brief - Personalized Investment Briefing")
    parser.add_argument(
        "--market",
        required=False,
        choices=["us", "cn", "all"],
        help="(Deprecated) macro pipeline always merges US+CN; kept for CLI compat",
    )
    parser.add_argument("--now", action="store_true", help="Run once immediately (default: scheduler mode)")
    parser.add_argument("--dry-run", action="store_true", help="Build report, output to stdout, do not send email")
    parser.add_argument("--skip-summary", action="store_true", help="Skip Claude API summary, use placeholder")
    parser.add_argument("--log-level", default="INFO", help="Log level (DEBUG, INFO, WARNING, ERROR)")
    args = parser.parse_args()

    # Setup logging
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_dir / "run.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )

    if args.now or args.dry_run:
        run_once(args)
    else:
        # Scheduler mode
        config = load_config()
        schedule_cfg = config.get("schedule", {})
        enabled = schedule_cfg.get("enabled", False)

        # Also check new-style markets config
        markets_cfg = config.get("markets", {})
        has_enabled_market = any(m.get("enabled", False) for m in markets_cfg.values())

        if not enabled and not has_enabled_market:
            logger.error("Scheduler mode is not enabled. Use --now for immediate execution or enable schedule in config.json")
            sys.exit(1)

        signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)

        run_scheduler(config)


if __name__ == "__main__":
    main()
