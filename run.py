# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "yfinance",
#   "requests",
#   "anthropic",
#   "python-dotenv",
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

# Auto-detect system proxy for yfinance / requests (macOS only — networksetup is macOS-specific)
if sys.platform == "darwin" and not os.environ.get("HTTPS_PROXY"):
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
# Config (load/validate lives in investbrief.core.config)
# ============================================================================
from investbrief.core.config import load_config


# ============================================================================
# Provider factory
# ============================================================================

def _create_provider(market: str):
    """Create a market provider instance."""
    if market == "us":
        from investbrief.market.us.provider import USMarketProvider
        return USMarketProvider()
    elif market == "cn":
        from investbrief.market.cn.provider import CNMarketProvider
        return CNMarketProvider()
    else:
        raise ValueError(f"Unknown market: {market}")


# ============================================================================
# News fetching (market-aware)
# ============================================================================

def fetch_news(config, tickers, max_news_count, industries, market="us"):
    """Fetch news for the specified market."""
    if market == "us":
        from investbrief.market.us.news import DataProvider
        provider = DataProvider(config)
        return provider.get_financial_news(
            tickers=tickers,
            limit=max_news_count,
            user_tickers=tickers,
            industries=industries,
        )
    elif market == "cn":
        from investbrief.market.cn.news import fetch_cn_news
        return fetch_cn_news(tickers, industries, max_news_count)
    return []


# ============================================================================
# Macro report Claude ①⑥ (implementation lives in investbrief.market.macro_brief)
# ============================================================================

def _safe_risk_score(model, market):
    """calculate_score with resilience — returns {} on failure (renders empty card)."""
    try:
        return model.calculate_score(market)
    except Exception as e:
        logger.warning(f"Risk score for {market} failed: {e}")
        return {}


# ============================================================================
# Research views (sell-side market commentary)
# ============================================================================

RESEARCH_VIEWS_PROMPT = """你是资深市场分析师。基于提供的「顶级卖方机构近 7 天市场观点」原始条目，为投资者写一段 HTML 摘要。

输出要求：
- 纯 HTML 片段，可用 <p>、<strong>、<ul><li>、<br>（不要 <h1>-<h6>、代码块标记）。
- 按四个小节组织，每节以 <strong>小节标题</strong> 起头：
  1. <strong>🌐 整体形势</strong>：全球宏观/利率/衰退/通胀/资金流等非单一市场的整体展望
  2. <strong>🇺🇸 美国市场</strong>：美股/美联储/美国经济相关
  3. <strong>🇨🇳 中国市场</strong>：A股/港股/中国经济相关
  4. <strong>🌍 其他市场</strong>：其他地区（韩股/欧股/新兴市场等）
- 只列「有条目」的小节；某类本周无条目，整节省略。
- 根据每条观点的内容归入最合适的小节；提供的市场标签仅作参考，整体宏观主题（如衰退、降息周期、全球资产配置）归入"整体形势"。
- 每个小节用 <ul><li> 分点陈列：每个 <li> 以 <strong>机构名</strong> 起头，接 1 句精炼观点（同一机构的多条合并为一条）。
- 不要把多家机构揉成一整段；不同机构各占一条 <li>。
- 不要在观点末尾附 (来源域名, 日期) 引用（机构名加粗已足够溯源）。
- 只用提供的数据，不编造观点、数字或机构。
- 若所有市场均无条目，输出 <p>本周暂无明显卖方机构观点。</p>。"""


def _serialize_research_views(items: list) -> str:
    """Compact text context from research-view items for Claude."""
    from urllib.parse import urlparse
    lines = []
    for it in items:
        markets = ",".join(it.get("markets") or []) or "全球其他"
        firms = ",".join(it.get("firms") or [])
        domain = urlparse(it.get("url", "")).netloc.replace("www.", "")
        lines.append(
            f"- [{markets}] {firms} | {it.get('title', '')} | "
            f"{it.get('date', '')} | {domain} | {it.get('snippet', '')}"
        )
    return "\n".join(lines)


def generate_research_views(items: list, max_retries: int = 2) -> str:
    """Synthesize research-view items into an HTML fragment via Claude, with retry.

    Returns inner HTML (caller wraps in the section). Empty/failure → placeholder.
    """
    import re as _re
    from investbrief.core.llm import get_client, default_model

    if not items:
        return ""
    client = get_client()
    context = _serialize_research_views(items)
    fallback = "<p>卖方机构观点生成失败。</p>"

    for attempt in range(max_retries + 1):
        try:
            response = client.messages.create(
                model=default_model(),
                max_tokens=1500,
                temperature=0.3,
                system=RESEARCH_VIEWS_PROMPT,
                messages=[{"role": "user", "content": context}],
            )
            text = response.content[0].text.strip()
            text = _re.sub(r"^\s*```(?:html)?\s*\n?", "", text)
            text = _re.sub(r"\n?\s*```\s*$", "", text)
            logger.info(f"Generated research views (attempt {attempt + 1})")
            return text or fallback
        except Exception as e:
            if attempt < max_retries:
                logger.warning(f"Research views attempt {attempt + 1} failed, retrying: {e}")
            else:
                logger.warning(f"Research views failed after {max_retries + 1} attempts: {e}")
    return fallback


# ============================================================================
# Send report
# ============================================================================

def send_report(report_data: dict, config: dict, recipients: list):
    """Render and send report to each recipient."""
    from investbrief.mail.render import load_template, render_template, translate_html
    from investbrief.mail.sender import EmailSender

    template = load_template()

    # Build render config from email_service section for color settings
    email_cfg = config.get("email_service", {})
    render_config = {
        "color_up": "#e74c3c",
        "color_down": "#27ae60",
    }

    sender = EmailSender(str(CONFIG_FILE))

    failed = []
    for r in recipients:
        email = r["email"]
        name = r.get("name", email)
        language = r.get("language", "zh-CN")

        logger.info(f"Processing: {name} ({email}) - Language: {language}")

        html = render_template(template, report_data, language)

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



# ============================================================================
# Macro report pipeline (merged US+CN)
# ============================================================================

def _run_macro_report(args):
    """Build ONE merged US+CN macro report and send to all active recipients."""
    logger.info("=" * 60)
    logger.info("invest-brief - Macro report pipeline (US+CN merged)")

    if getattr(args, "update", False):
        logger.info("Update-only mode: refreshing macro data, no render/send")
        us = _create_provider("us")
        cn = _create_provider("cn")
        us.refresh()
        cn.refresh()
        try:
            from investbrief.data.gold_data import GoldData
            gold_data = GoldData()
            try:
                gold_data.update_incremental()
            finally:
                gold_data.close()
        except Exception as e:
            logger.warning(f"Gold data refresh failed in update-only mode: {e}")
        logger.info("Update-only complete")
        return

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
    # P1: 增量取数落盘（失败不阻塞，get_* 回退库内最新值）
    us.refresh()
    cn.refresh()
    # P4: refresh gold data daily (resilient — fallback to stored values on failure)
    from investbrief.data.gold_data import GoldData
    gold_data = GoldData()
    try:
        gold_data.update_incremental()
    except Exception as e:
        logger.warning(f"Gold data refresh failed, falling back to stored values: {e}")
    from investbrief.market.us.calendar import get_upcoming_events_with_yfinance
    from investbrief.market.cn.calendar import get_upcoming_events as get_cn_events
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

    # P4: compute risk scores (resilient — empty dict renders empty card)
    from investbrief.risk.models import RiskModel
    from investbrief.risk.render import render_risk_card, render_gold_section
    risk_model = RiskModel(us.data)
    risk_scores = {
        "us": _safe_risk_score(risk_model, "us"),
        "cn": _safe_risk_score(risk_model, "cn"),
        "gold": _safe_risk_score(risk_model, "gold"),
    }
    us_risk_html = render_risk_card(risk_scores["us"])
    cn_risk_html = render_risk_card(risk_scores["cn"])
    gold_section_html = render_gold_section(risk_scores["gold"])

    # Claude ①⑥（一次调用同时生成核心观点 + 风险）
    if skip_summary:
        logger.info("Skipping Claude brief (--skip-summary)")
        macro_summary = "<p>（已跳过 AI 研判）</p>"
        risk_outlook = "<p>—</p>"
    else:
        logger.info("Generating macro brief via Claude (①⑥)")
        from investbrief.market.macro_brief import generate_macro_brief
        macro_summary, risk_outlook = generate_macro_brief(us_data, cn_data, news, risk_scores=risk_scores)

    # Research views (sell-side market commentary) — Tavily fetch + Claude synthesis
    research_views_html = ""
    if not skip_summary:
        try:
            from investbrief.market.research import fetch_research_views
            research_items = fetch_research_views()
            logger.info(f"Fetched {len(research_items)} research-view items")
            if research_items:
                inner = generate_research_views(research_items)
                if inner:
                    research_views_html = (
                        '<div class="section">'
                        '<h2 style="margin:0 0 15px 0;font-size:18px;color:#2c3e50;">🏦 卖方机构观点</h2>'
                        f'<div class="summary-box">{inner}</div>'
                        '</div>'
                    )
        except Exception as e:
            logger.warning(f"Research views failed: {e}")

    # Render sections
    us_html = us.render_section(us_data, render_config, risk_html=us_risk_html)
    cn_html = cn.render_section(cn_data, render_config, risk_html=cn_risk_html)

    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    report_data = {
        "subject": f"【宏观经济日报】{now.strftime('%Y年%m月%d日')}",
        "data_time": now.strftime("%Y-%m-%d %H:%M"),
        "date": now.strftime("%Y-%m-%d"),
        "market": "all",
        "macro_summary": macro_summary,
        "risk_outlook": risk_outlook,
        "market_section_html": us_html + cn_html + gold_section_html,
        "research_views": research_views_html,
        "news": news,
    }

    if getattr(args, "dry_run", False):
        logger.info("Dry run - outputting report data to stdout")
        print(json.dumps(report_data, ensure_ascii=False, indent=2, default=str))
        try:
            gold_data.close()
        except Exception:
            pass
        return

    send_report(report_data, config, recipients)

    # Release gold data resources
    try:
        gold_data.close()
    except Exception:
        pass

    # Save local preview
    try:
        from investbrief.mail.render import load_template, render_template
        preview_dir = Path(__file__).parent / "reports"
        preview_dir.mkdir(exist_ok=True)
        template = load_template()
        preview_html = render_template(template, report_data, "zh-CN")
        preview_path = preview_dir / "preview_macro.html"
        preview_path.write_text(preview_html, encoding="utf-8")
        logger.info(f"Preview saved to {preview_path}")
    except Exception as e:
        logger.warning(f"Failed to save preview: {e}")

    logger.info("Macro report pipeline complete")


# ============================================================================
# Holdings report pipeline (per-recipient, distinct from macro)
# ============================================================================

def _run_holdings_report(args):
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
            preview_dir = Path(__file__).parent / "reports"
            preview_dir.mkdir(exist_ok=True)
            (preview_dir / "preview_holdings.html").write_text(preview_html, encoding="utf-8")
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
            preview_dir = Path(__file__).parent / "reports"
            preview_dir.mkdir(exist_ok=True)
            (preview_dir / "preview_holdings.html").write_text(last_html, encoding="utf-8")
            logger.info("Holdings preview saved to reports/preview_holdings.html")
        except Exception as e:
            logger.warning(f"Failed to save holdings preview: {e}")

    if failed:
        logger.warning(f"{len(failed)}/{len(recipients)} holdings emails failed: {failed}")
    logger.info("Holdings report pipeline complete")


# ============================================================================
# Run Once (immediate execution)
# ============================================================================

def run_once(args):
    """Execute pipeline(s) once. --only controls which; default runs both macro + holdings."""
    only = getattr(args, "only", None)
    if only in (None, "macro"):
        _run_macro_report(args)
    # Holdings pipeline has no update-only mode; skip under --update
    if only in (None, "holdings") and not getattr(args, "update", False):
        _run_holdings_report(args)


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
                only=None,
                log_level=logging.getLevelName(logger.getEffectiveLevel()),
            )

            try:
                _run_macro_report(args)
            except Exception as e:
                logger.error(f"Scheduled macro run failed: {e}", exc_info=True)
            try:
                _run_holdings_report(args)
            except Exception as e:
                logger.error(f"Scheduled holdings run failed: {e}", exc_info=True)

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
    parser.add_argument("--update", action="store_true",
                        help="Only refresh macro data into SQLite, no render/email")
    parser.add_argument("--only", choices=["macro", "holdings"], default=None,
                        help="Run only one pipeline (default: both macro + holdings)")
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

    if args.now or args.dry_run or args.update:
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
