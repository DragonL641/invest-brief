# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "yfinance",
#   "requests",
#   "anthropic",
#   "python-dotenv",
#   "matplotlib",
#   "croniter",
# ]
# ///

"""
Standalone entry point for invest-brief (formerly stock-US-morning-brief).
Replaces Claude Code orchestration with pure Python + Claude API for summary generation.

Usage:
    uv run run.py              # Scheduler mode (cron-based)
    uv run run.py --now        # Run once immediately
    uv run run.py --dry-run    # Build report, output to stdout, do not send email
    uv run run.py --skip-summary  # Skip Claude API summary, use placeholder
"""

import sys
import json
import os
import signal
import argparse
import logging
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from croniter import croniter

# Make lib/ importable
sys.path.insert(0, str(Path(__file__).parent))

# Load .env before importing lib modules (they depend on env vars)
from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent
ENV_FILE = PROJECT_DIR / ".env"
CONFIG_FILE = PROJECT_DIR / "config.json"

load_dotenv(ENV_FILE, override=False)

# Ensure ANTHROPIC_AUTH_TOKEN is available as ANTHROPIC_API_KEY for anthropic SDK
if not os.environ.get("ANTHROPIC_API_KEY") and os.environ.get("ANTHROPIC_AUTH_TOKEN"):
    os.environ["ANTHROPIC_API_KEY"] = os.environ["ANTHROPIC_AUTH_TOKEN"]

logger = logging.getLogger("run")

# Graceful shutdown flag
_shutdown = False


def _handle_signal(signum, frame):
    global _shutdown
    sig_name = signal.Signals(signum).name
    logger.info(f"Received {sig_name}, shutting down gracefully...")
    _shutdown = True


# ============================================================================
# Step 1: Load Configuration
# ============================================================================

def load_config() -> dict:
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


# ============================================================================
# Step 2: Merge Recipient Settings
# ============================================================================

NEWS_LIMIT = 5


def merge_recipient_settings(recipients: list) -> tuple:
    holdings_union = []
    industries_union = set()

    for r in recipients:
        settings = r.get("settings", {})
        holdings_union.extend(settings.get("holdings", []))
        industries_union.update(settings.get("industries", []))

    seen = set()
    unique_holdings = []
    for h in holdings_union:
        if h["symbol"] not in seen:
            seen.add(h["symbol"])
            unique_holdings.append(h)

    return unique_holdings, industries_union, NEWS_LIMIT


# ============================================================================
# Step 3: Fetch Market Data
# ============================================================================

def fetch_market_data(unique_holdings, industries_union, holdings_symbols):
    from lib.market import USMarketProvider

    provider = USMarketProvider()
    return {
        "indices": provider.get_indices(),
        "holdings": provider.get_holdings_data(unique_holdings),
        "recommendations": provider.get_recommendations_from_industries(
            list(industries_union), holdings_symbols
        ),
    }


# ============================================================================
# Step 4: Fetch News
# ============================================================================

def fetch_news(config, tickers, max_news_count, industries_union):
    from lib.data_provider import DataProvider

    dp = DataProvider(config)
    return dp.get_financial_news(
        tickers=tickers,
        limit=max_news_count,
        user_tickers=tickers,
        industries=list(industries_union),
    )


# ============================================================================
# Step 4.5: Summarize News via Claude API
# ============================================================================

NEWS_SUMMARY_PROMPT = """你是财经新闻编辑。阅读以下新闻，为每条新闻生成中文标题和简明摘要。

规则：
1. 标题：用中文概括核心事件，10-20字，保留关键公司名/股票代码（英文）
2. 摘要：1-2句中文，说明影响什么、为什么重要，不要废话
3. 严格按 JSON 数组格式返回，每项包含 title 和 summary 字段
4. 数量与输入一致，顺序与输入一致
5. 不要加 markdown 代码块标记"""


def summarize_news(news: list) -> list:
    """Summarize news titles and generate Chinese briefs via Claude API."""
    if not news:
        return news

    # Only summarize the items we'll actually show
    news = news[:NEWS_LIMIT]

    try:
        import anthropic
        import re

        client = anthropic.Anthropic(
            api_key=os.environ.get("ANTHROPIC_API_KEY"),
            base_url=os.environ.get("ANTHROPIC_BASE_URL"),
        )

        items_text = "\n".join(
            f"{i+1}. Title: {n.get('title', '')}\n   Content: {n.get('summary', '')[:500]}"
            for i, n in enumerate(news)
        )

        user_message = f"请为以下 {len(news)} 条新闻生成中文标题和摘要：\n\n{items_text}"

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            temperature=0.2,
            system=NEWS_SUMMARY_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )

        text = response.content[0].text.strip()
        text = re.sub(r"^\s*```(?:json)?\s*\n?", "", text)
        text = re.sub(r"\n?\s*```\s*$", "", text)

        summaries = json.loads(text)
        if not isinstance(summaries, list) or len(summaries) != len(news):
            logger.warning(f"News summary count mismatch: got {len(summaries) if isinstance(summaries, list) else 'non-list'}, expected {len(news)}")
            return news

        for i, s in enumerate(summaries):
            if isinstance(s, dict):
                news[i]["title"] = s.get("title", news[i].get("title", ""))
                news[i]["summary"] = s.get("summary", "")

        logger.info(f"Summarized {len(news)} news items")
        return news

    except Exception as e:
        logger.warning(f"News summarization failed: {e}")
        return news


# ============================================================================
# Step 5: Build Global Metrics
# ============================================================================

def build_global_metrics(indices):
    metrics = []
    for idx in indices:
        metrics.append({
            "label": idx["name"],
            "value": f"{idx['change']:+.2f}%",
            "change": idx["change"],
        })
    return metrics


# ============================================================================
# Step 6: Generate Daily Summary via Claude API
# ============================================================================

SYSTEM_PROMPT = """你是一个专业的美股市场分析师。根据提供的市场数据和新闻，撰写一份简明扼要的每日投资简报总结。

要求：
1. 输出纯 HTML 段落（<p>标签），不包含任何 markdown
2. 使用中文撰写
3. 内容结构建议：
   - 第一段：市场整体表现（结合指数涨跌）
   - 第二段：持仓股票要点（关注涨跌幅较大的个股、关键分析师评级变动、财报表现）
   - 第三段：行业/板块动态（结合新闻中与持仓相关的信息）
   - 第四段（可选）：风险提示或值得关注的事件
4. 每段 2-3 句话，总字数 200-400 字
5. 只使用提供的数据，不要编造数字
6. 对关键数字使用 <strong> 标签突出显示
7. 不要使用列表或标题，只用段落"""


def _serialize_market_context(market_data, news, unique_holdings):
    """Serialize market data and news into structured text for Claude."""
    lines = []

    # Indices
    lines.append("## 市场指数")
    for idx in market_data.get("indices", []):
        lines.append(f"- {idx['name']}: {idx['point']:.2f} ({idx['change']:+.2f}%)")

    # Holdings
    lines.append("\n## 持仓股票")
    for h in market_data.get("holdings", []):
        symbol = h.get("symbol", "")
        name = h.get("name", symbol)
        price = h.get("price", 0)
        change = h.get("change", 0)
        info = h.get("info", {})
        lines.append(f"- {symbol} ({name}): ${price:.2f} ({change:+.2f}%)")
        if info.get("pe"):
            lines.append(f"  P/E: {info['pe']:.1f}")
        targets = h.get("targets", {})
        if targets.get("mean"):
            upside = h.get("upside_pct")
            lines.append(f"  目标价: ${targets['mean']:.2f} (上涨空间: {upside:+.1f}%)" if upside else f"  目标价: ${targets['mean']:.2f}")
        # Notable upgrades
        for ug in h.get("upgrades", [])[:3]:
            firm = ug.get("firm", "")
            grade = ug.get("to_grade", "")
            date = ug.get("date", "")
            lines.append(f"  评级变动: {firm} → {grade} ({date})")
        # Earnings surprise
        for eh in h.get("earnings_history", [])[:2]:
            surprise = eh.get("surprise_pct")
            if surprise is not None:
                lines.append(f"  财报惊喜: {surprise:+.1f}%")

    # Recommendations
    lines.append("\n## 推荐关注")
    for r in market_data.get("recommendations", []):
        symbol = r.get("symbol", "")
        buy_pct = r.get("buy_pct", 0)
        industry = r.get("industry", "")
        lines.append(f"- {symbol}: 买入评级 {buy_pct:.0f}%, 行业: {industry}")

    # News
    lines.append("\n## 重要新闻")
    for n in news[:5]:
        title = n.get("title", "")
        source = n.get("source", "")
        t = n.get("time", "")
        lines.append(f"- {title} ({source}, {t})")

    return "\n".join(lines)


def generate_daily_summary(market_data, news, unique_holdings):
    """Generate personalized daily summary via Claude API."""
    try:
        import anthropic

        client = anthropic.Anthropic(
            api_key=os.environ.get("ANTHROPIC_API_KEY"),
            base_url=os.environ.get("ANTHROPIC_BASE_URL"),
        )

        context = _serialize_market_context(market_data, news, unique_holdings)
        holdings_symbols = ", ".join(h["symbol"] for h in unique_holdings)

        user_message = f"当前持仓: {holdings_symbols}\n\n{context}"

        with client.messages.stream(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            temperature=0.3,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        ) as stream:
            summary = ""
            for text in stream.text_stream:
                summary += text

        # Strip markdown code block wrappers
        import re
        summary = re.sub(r"^\s*```(?:html)?\s*\n?", "", summary)
        summary = re.sub(r"\n?\s*```\s*$", "", summary)
        return summary.strip()

    except Exception as e:
        logger.warning(f"Claude API summary failed: {e}")
        return "<p>今日市场数据已更新，请查看上方详情。</p>"


# ============================================================================
# Step 7: Build Report Data
# ============================================================================

def build_report_data(market_data, news, global_metrics, daily_summary):
    now = datetime.now()
    return {
        "subject": f"【美股日报】{now.strftime('%Y年%-m月%-d日')}",
        "data_time": now.strftime("%H:%M:%S"),
        "global_metrics": global_metrics,
        "news": news,
        "us": {
            "indices": market_data.get("indices", []),
            "holdings": market_data.get("holdings", []),
            "recommendations": market_data.get("recommendations", []),
        },
        "daily_summary": daily_summary,
    }


# ============================================================================
# Step 8: Send Report
# ============================================================================

def send_report(report_data):
    """Send report using send_report module directly."""
    from lib.send_report import (
        load_config as sr_load_config,
        load_template,
        render_template,
        translate_html,
    )
    from lib.smtp_client import EmailSender

    config = sr_load_config()
    template = load_template()
    active_recipients = [r for r in config.get("recipients", []) if r.get("active", True)]

    if not active_recipients:
        logger.error("No active recipients found")
        return

    sender = EmailSender(str(CONFIG_FILE))

    for recipient in active_recipients:
        email = recipient["email"]
        name = recipient.get("name", email)
        language = recipient.get("language", "zh-CN")
        settings = recipient.get("settings", {})

        logger.info(f"Processing: {name} ({email}) - Language: {language}")

        html = render_template(template, report_data, language, settings)
        # Translate for non-Chinese recipients
        if language != "zh-CN":
            html = translate_html(html, language)

        subject = report_data.get("subject", f"【美股日报】{datetime.now().strftime('%Y年%m月%d日')}")

        try:
            sender.send(email, subject, html)
            logger.info(f"Sent successfully to {email}")
        except Exception as e:
            logger.error(f"Failed to send to {email}: {e}")


# ============================================================================
# Run Once (immediate execution)
# ============================================================================

def run_once(args):
    """Execute the full pipeline once."""
    logger.info("=" * 60)
    logger.info("invest-brief - Starting (run-once mode)")

    # Check weekend
    et = ZoneInfo("America/New_York")
    now_et = datetime.now(et)
    if now_et.weekday() >= 5:
        logger.info(f"Today is {now_et.strftime('%A')} in US Eastern time, market closed. Skipping.")
        return

    # Step 1: Load config
    logger.info("Step 1: Loading configuration")
    config = load_config()
    recipients = [r for r in config.get("recipients", []) if r.get("active", True)]
    if not recipients:
        logger.error("No active recipients found")
        sys.exit(1)
    logger.info(f"Found {len(recipients)} active recipient(s)")

    # Step 2: Merge settings
    logger.info("Step 2: Merging recipient settings")
    unique_holdings, industries_union, max_news_count = merge_recipient_settings(recipients)
    holdings_symbols = [h["symbol"] for h in unique_holdings]
    logger.info(f"Holdings: {holdings_symbols}, Industries: {industries_union}, Max news: {max_news_count}")

    # Step 3: Fetch market data
    logger.info("Step 3: Fetching market data")
    try:
        market_data = fetch_market_data(unique_holdings, industries_union, holdings_symbols)
        logger.info(f"Got {len(market_data.get('holdings', []))} holdings, {len(market_data.get('indices', []))} indices")
    except Exception as e:
        logger.warning(f"Market data fetch failed: {e}")
        market_data = {"indices": [], "holdings": [], "recommendations": []}

    # Step 4: Fetch news
    logger.info("Step 4: Fetching news")
    try:
        news = fetch_news(config, holdings_symbols, max_news_count, industries_union)
        logger.info(f"Got {len(news)} news items")
    except Exception as e:
        logger.warning(f"News fetch failed: {e}")
        news = []

    # Step 5: Build global metrics
    logger.info("Step 5: Building global metrics")
    global_metrics = build_global_metrics(market_data.get("indices", []))

    # Step 5.5: Summarize news
    if news and not args.skip_summary:
        logger.info("Step 5.5: Summarizing news via Claude API")
        news = summarize_news(news)
    else:
        logger.info("Step 5.5: Skipping news summary")

    # Step 6: Generate daily summary
    if args.skip_summary:
        logger.info("Step 6: Skipping summary (--skip-summary)")
        daily_summary = "<p>今日市场数据已更新，请查看上方详情。</p>"
    else:
        logger.info("Step 6: Generating daily summary via Claude API")
        daily_summary = generate_daily_summary(market_data, news, unique_holdings)
        logger.info(f"Summary generated: {len(daily_summary)} chars")

    # Step 7: Build report data
    logger.info("Step 7: Building report data")
    report_data = build_report_data(market_data, news, global_metrics, daily_summary)

    if args.dry_run:
        logger.info("Dry run - outputting report data to stdout")
        print(json.dumps(report_data, ensure_ascii=False, indent=2, default=str))
        logger.info("Dry run complete")
        return

    # Step 8: Send report
    logger.info("Step 8: Sending report")
    send_report(report_data)
    logger.info("Report sending complete")


# ============================================================================
# Scheduler (cron-based long-running process)
# ============================================================================

def run_scheduler(config):
    """Run as a long-lived process, executing at cron-scheduled times."""
    schedule_cfg = config.get("schedule", {})
    cron_expr = schedule_cfg.get("cron", "0 23 * * 1-5")

    if not croniter.is_valid(cron_expr):
        logger.error(f"Invalid cron expression: {cron_expr}")
        sys.exit(1)

    now = datetime.now()
    cron = croniter(cron_expr, now)
    next_run = cron.get_next(datetime)

    logger.info(f"Scheduler started with cron: '{cron_expr}'")
    logger.info(f"Next run scheduled at: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")

    while not _shutdown:
        now = datetime.now()

        if now >= next_run:
            logger.info("=" * 60)
            logger.info("Scheduled run triggered")

            # Build a minimal args namespace for run_once
            args = argparse.Namespace(
                dry_run=False,
                skip_summary=False,
                log_level=logging.getLevelName(logger.getEffectiveLevel()),
            )

            try:
                run_once(args)
            except Exception as e:
                logger.error(f"Scheduled run failed: {e}", exc_info=True)

            # Schedule next run
            cron = croniter(cron_expr, now)
            next_run = cron.get_next(datetime)
            logger.info(f"Next run scheduled at: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")

        # Sleep in small intervals to respond to shutdown signals promptly
        time.sleep(30)

    logger.info("Scheduler stopped")


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="invest-brief - US Stock Morning Brief")
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

    # Load config to check schedule settings
    config = load_config()

    if args.now:
        # Run once immediately
        run_once(args)
    else:
        # Scheduler mode
        schedule_cfg = config.get("schedule", {})
        enabled = schedule_cfg.get("enabled", False)

        if not enabled:
            logger.error("Scheduler mode is not enabled. Use --now for immediate execution or enable schedule in config.json")
            sys.exit(1)

        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)

        run_scheduler(config)


if __name__ == "__main__":
    main()
