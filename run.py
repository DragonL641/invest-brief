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
# Macro report prompts (merged US+CN)
# ============================================================================

MACRO_BRIEF_PROMPT = """你是资深宏观经济分析师，为投资者撰写每日中美宏观市场简报。

基于提供的中美宏观数据，输出纯 JSON（不要 markdown 代码块标记），包含两个字段：
- "summary"：核心观点，纯 HTML（可用 <p>、<strong>、<ul><li>、<br>；不要 markdown/代码块标记），分 4 个小节，每节以 <strong>小节标题</strong> 起头：
  1. <strong>宏观环境</strong>：中美经济数据信号（CPI/PMI/就业等）、增长与通胀走向
  2. <strong>货币政策</strong>：美联储 vs 中国央行立场、美债收益率、中美利差含义
  3. <strong>大类资产</strong>：美股/A股/债市/汇率/商品走势逻辑与轮动
  4. <strong>风险与机会</strong>：最需关注的事件、潜在拐点
  每节先用 <strong>1 句方向性结论</strong>开门（偏多/偏空/中性），再用 <ul><li> 列 2-4 个分点论据，关键数字用 <strong>。
  必须分点陈列、可读性优先；禁止把一节写成一大段连续文字墙。总字数 400-600。
- "risk"：未来一周风险事件与关注点，纯 HTML，用 <ul><li> 列 3-5 条，每条关键事件/日期用 <strong>，120 字以内。

只用提供的数据，不编造数字。严格按 JSON 输出，形如 {"summary": "...", "risk": "..."}。"""


# ============================================================================
# Macro report Claude ①⑥
# ============================================================================

def _safe_risk_score(model, market):
    """calculate_score with resilience — returns {} on failure (renders empty card)."""
    try:
        return model.calculate_score(market)
    except Exception as e:
        logger.warning(f"Risk score for {market} failed: {e}")
        return {}


def _serialize_macro_context(us_data: dict, cn_data: dict, news: list, risk_scores: dict | None = None) -> str:
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

    if risk_scores:
        lines.append("\n## 市场周期风险分（模型跟踪信号；跟踪≠预测，不可作为单独买卖依据）")
        for market, name in (("us", "美股"), ("cn", "A股"), ("gold", "黄金")):
            r = risk_scores.get(market) or {}
            if r.get("total_score") is not None:
                lines.append(f"- {name}: 风险分 {r['total_score']}（{r['state']}），{r['action']}")

    return "\n".join(lines)


def generate_macro_brief(us_data: dict, cn_data: dict, news: list, risk_scores: dict | None = None, max_retries: int = 2) -> tuple[str, str]:
    """一次 Claude 调用同时生成 ①核心观点 + ⑥风险（JSON 输出），带重试。

    失败重试 max_retries 次；最终仍失败则返回兜底占位（pipeline 不崩）。
    """
    import re as _re
    from investbrief.core.llm import get_client, default_model

    client = get_client()
    context = _serialize_macro_context(us_data, cn_data, news, risk_scores=risk_scores)
    fallback_summary = "<p>宏观研判生成失败，请查看下方数据。</p>"
    fallback_risk = "<p>风险研判生成失败。</p>"

    for attempt in range(max_retries + 1):
        try:
            response = client.messages.create(
                model=default_model(),
                max_tokens=2560,
                temperature=0.3,
                system=MACRO_BRIEF_PROMPT,
                messages=[{"role": "user", "content": context}],
            )
            text = response.content[0].text.strip()
            text = _re.sub(r"^\s*```(?:json)?\s*\n?", "", text)
            text = _re.sub(r"\n?\s*```\s*$", "", text)
            data = json.loads(text)
            summary = (data.get("summary") or "").strip() or fallback_summary
            risk = (data.get("risk") or "").strip() or fallback_risk
            logger.info(f"Generated macro brief (attempt {attempt + 1})")
            return summary, risk
        except Exception as e:
            if attempt < max_retries:
                logger.warning(f"Macro brief attempt {attempt + 1} failed, retrying: {e}")
            else:
                logger.warning(f"Macro brief failed after {max_retries + 1} attempts: {e}")
    return fallback_summary, fallback_risk


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

        html = render_template(template, report_data, language)

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
        macro_summary, risk_outlook = generate_macro_brief(us_data, cn_data, news, risk_scores=risk_scores)

    # Research views (sell-side market commentary) — Tavily fetch + Claude synthesis
    research_views_html = ""
    if not skip_summary:
        try:
            from investbrief.research.views import fetch_research_views
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
        from investbrief.report import load_template, render_template
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
    parser.add_argument("--update", action="store_true",
                        help="Only refresh macro data into SQLite, no render/email")
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
