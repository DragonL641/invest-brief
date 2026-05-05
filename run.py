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

# Ensure ANTHROPIC_AUTH_TOKEN is available as ANTHROPIC_API_KEY for anthropic SDK
if not os.environ.get("ANTHROPIC_API_KEY") and os.environ.get("ANTHROPIC_AUTH_TOKEN"):
    os.environ["ANTHROPIC_API_KEY"] = os.environ["ANTHROPIC_AUTH_TOKEN"]

logger = logging.getLogger("run")

# Graceful shutdown flag
_shutdown = False

NEWS_LIMIT = 5

# ============================================================================
# Market-aware system prompts
# ============================================================================

SYSTEM_PROMPTS = {
    "us": """你是一位经验丰富的美股投资组合经理，为高净值客户撰写每日市场简报。语气专业但不刻板，像一个值得信赖的投资顾问在说话。

要求：
1. 输出纯 HTML 段落（<p>标签），不包含任何 markdown
2. 使用中文撰写
3. 内容结构（每段 2-3 句话）：
   - 宏观环境：大盘走势 + 宏观指标（国债/原油/美元）传递的信号
   - 持仓诊断：个股涨跌原因分析，结合分析师评级变动、技术指标（RSI/MACD）、财报数据给出判断
   - 事件驱动：重要新闻对持仓的实质影响，即将到来的财报/经济事件需要注意什么
   - 操作建议：基于以上分析，给出明确的 hold/buy/sell 观点，附理由
4. 总字数 300-500 字
5. 只使用提供的数据，不要编造数字
6. 关键数字用 <strong> 标签，关键判断用 <strong> 标签
7. 不要使用列表或标题，只用段落""",
    "cn": """你是一位经验丰富的A股投资分析师，为高净值客户撰写每日市场简报。语气专业但不刻板，像一个值得信赖的投资顾问在说话。

要求：
1. 输出纯 HTML 段落（<p>标签），不包含任何 markdown
2. 使用中文撰写
3. 内容结构（每段 2-3 句话）：
   - 大盘分析：主要指数走势、成交量、资金流向
   - 持仓诊断：个股涨跌原因分析，结合技术指标给出判断
   - 政策与事件：重要政策动向、行业新闻对持仓的影响
   - 操作建议：基于以上分析，给出明确的持有/加仓/减仓观点，附理由
4. 总字数 300-500 字
5. 只使用提供的数据，不要编造数字
6. 关键数字用 <strong> 标签，关键判断用 <strong> 标签
7. 不要使用列表或标题，只用段落""",
}


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
# Recipient helpers
# ============================================================================

def _filter_recipients(recipients: list, market: str) -> list:
    """Return active recipients that have holdings or industries for the given market."""
    result = []
    for r in recipients:
        if not r.get("active", True):
            continue
        settings = r.get("settings", {})
        markets = r.get("markets", {})
        # Support both old-style "settings" and new-style "markets"
        if markets:
            market_cfg = markets.get(market, {})
            if market_cfg.get("holdings") or market_cfg.get("industries"):
                result.append(r)
        elif market == "us" and (settings.get("holdings") or settings.get("industries")):
            # Fallback: old config with no "markets" key, treat as US-only
            result.append(r)
    return result


def merge_recipient_settings(recipients: list, market: str) -> tuple:
    """Merge holdings and industries from all recipients for a given market."""
    all_holdings = []
    seen_symbols = set()
    all_industries = set()

    for r in recipients:
        holdings = []
        industries = []

        # New-style config: r["markets"][market]
        markets = r.get("markets", {})
        if markets and market in markets:
            market_cfg = markets[market]
            holdings = market_cfg.get("holdings", [])
            industries = market_cfg.get("industries", [])
        elif market == "us":
            # Old-style fallback: r["settings"]
            settings = r.get("settings", {})
            holdings = settings.get("holdings", [])
            industries = settings.get("industries", [])

        for h in holdings:
            key = h.get("symbol", "")
            if key and key not in seen_symbols:
                seen_symbols.add(key)
                all_holdings.append(h)
        all_industries.update(industries)

    return all_holdings, list(all_industries)


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
# News summarization via Claude API
# ============================================================================

NEWS_SUMMARY_PROMPT = """你是财经新闻编辑。阅读以下新闻，为每条新闻生成中文标题和简明摘要。

规则：
1. 标题：用中文概括核心事件，10-20字，保留关键公司名/股票代码（英文）
2. 摘要：1-2句中文，说明影响什么、为什么重要，不要废话
3. 严格按 JSON 数组格式返回，每项包含 title 和 summary 字段
4. 数量与输入一致，顺序与输入一致
5. 不要加 markdown 代码块标记"""


def summarize_news(news: list, market="us") -> list:
    """Summarize news titles and generate Chinese briefs via Claude API."""
    if not news:
        return news

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

        from investbrief.core.models import NewsSummaryResponse
        validated = NewsSummaryResponse.from_raw_list(summaries)
        if validated and len(validated.items) == len(news):
            for i, item in enumerate(validated.items):
                news[i]["title"] = item.title
                news[i]["summary"] = item.summary
        else:
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
# Daily summary via Claude API
# ============================================================================

def _serialize_market_context(market_data, news, holdings, market="us"):
    """Serialize market data and news into structured text for Claude."""
    lines = []

    cur = "$" if market == "us" else "¥"

    # Indices
    lines.append("## 市场指数")
    for idx in market_data.get("indices", []):
        lines.append(f"- {idx['name']}: {idx['point'] or 0:.2f} ({idx['change'] or 0:+.2f}%)")

    # Holdings
    lines.append("\n## 持仓股票")
    for h in market_data.get("holdings", []):
        symbol = h.get("symbol", "")
        name = h.get("name", symbol)
        price = h.get("price", 0)
        change = h.get("change", 0)
        lines.append(f"- {symbol} ({name}): {cur}{price or 0:.2f} ({change or 0:+.2f}%)")

        if market == "us":
            info = h.get("info", {})
            if info.get("pe"):
                lines.append(f"  P/E: {info['pe']:.1f}")
            targets = h.get("targets", {})
            if targets.get("mean"):
                upside = h.get("upside_pct")
                lines.append(f"  目标价: {cur}{targets['mean']:.2f} (上涨空间: {upside:+.1f}%)" if upside else f"  目标价: {cur}{targets['mean']:.2f}")
            for ug in h.get("upgrades", [])[:3]:
                firm = ug.get("firm", "")
                grade = ug.get("to_grade", "")
                date = ug.get("date", "")
                lines.append(f"  评级变动: {firm} → {grade} ({date})")
            for eh in h.get("earnings_history", [])[:2]:
                surprise = eh.get("surprise_pct")
                if surprise is not None:
                    lines.append(f"  财报惊喜: {surprise:+.1f}%")

        if market == "cn":
            # CN-specific: PE from quote, financial indicators, rating summary
            if h.get("pe") is not None:
                lines.append(f"  PE(动态): {h['pe']:.1f}")
            fin = h.get("financial")
            if fin:
                if fin.get("roe") is not None:
                    lines.append(f"  ROE: {fin['roe']:.2f}%")
                if fin.get("revenue_growth") is not None:
                    lines.append(f"  营收增长: {fin['revenue_growth']:+.2f}%")
                if fin.get("profit_growth") is not None:
                    lines.append(f"  净利润增长: {fin['profit_growth']:+.2f}%")
            rating = h.get("rating_summary")
            if rating and rating.get("total_reports", 0) > 0:
                total = rating["total_reports"]
                buy = rating.get("buy", 0) + rating.get("outperform", 0)
                lines.append(f"  研报: {total}份, 买入评级 {buy/total*100:.0f}%")
            # Insider trades (高管增减持)
            for t in h.get("insider_trades", [])[:3]:
                lines.append(f"  高管变动: {t.get('name', '')} {t.get('action', '')} {t.get('shares') or 0:,.0f}股 ({t.get('date', '')})")
            # Institutional research
            for r in h.get("institutional_research", [])[:3]:
                lines.append(f"  机构调研: {r.get('institution', '')}家机构 ({r.get('date', '')})")

        techs = h.get("technicals")
        if techs:
            rsi = techs.get("rsi_14")
            if rsi:
                rsi_label = "超买" if rsi > 70 else "超卖" if rsi < 30 else ""
                lines.append(f"  RSI(14): {rsi:.1f} {rsi_label}")
            if techs.get("macd_hist") is not None:
                direction = "金叉" if techs["macd_hist"] > 0 else "死叉"
                lines.append(f"  MACD: {direction}")

    if market == "us":
        # Earnings calendar
        earnings_cal = market_data.get("earnings_calendar", [])
        if earnings_cal:
            lines.append("\n## 即将财报")
            for e in earnings_cal:
                lines.append(f"- {e['symbol']} ({e['name']}): {e['date']} ({e['days_away']}天后)")

        # Economic calendar
        econ_cal = market_data.get("economic_calendar", [])
        if econ_cal:
            lines.append("\n## 即将公布的经济数据")
            for e in econ_cal[:8]:
                lines.append(f"- {e.get('date', '')} {e.get('event', '')} (预期: {e.get('forecast', 'N/A')}, 前值: {e.get('previous', 'N/A')})")

        # Insider trades (EDGAR Form 4)
        for h in market_data.get("holdings", []):
            edgar = h.get("insider_trades_edgar", [])
            if edgar:
                lines.append(f"\n## {h['symbol']} 内部人交易 (SEC Form 4)")
                for tx in edgar[:5]:
                    action = tx.get("action_label", "")
                    shares = tx.get("shares", "")
                    price = tx.get("price", "")
                    date = tx.get("date", "")
                    code = tx.get("code", "")
                    lines.append(f"- {date}: {action} {shares}股 @ {cur}{price} (代码: {code})")

    if market == "cn":
        # Dragon tiger (龙虎榜)
        dt = market_data.get("dragon_tiger", [])
        if dt:
            lines.append("\n## 龙虎榜")
            for d in dt[:10]:
                net = d.get("net_buy")
                net_str = f"{cur}{net/1e8:.2f}亿" if net and net >= 1e8 else f"{cur}{net/1e4:.1f}万" if net else "-"
                lines.append(f"- {d.get('name', '')} ({d.get('symbol', '')}): {d.get('change_pct', 0):+.2f}% 净买入{net_str} ({d.get('reason', '')})")

        # Economic calendar
        econ_cal = market_data.get("economic_calendar", [])
        if econ_cal:
            lines.append("\n## 经济日历")
            for e in econ_cal[:8]:
                lines.append(f"- {e.get('name', '')} {e.get('date', '')} ({e.get('days_away', '')}天后)")

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
        summary = n.get("summary", "")
        source = n.get("source", "")
        t = n.get("time", "") or n.get("date", "")
        entry = f"- {title} ({source}, {t})"
        if summary:
            entry += f"\n  摘要: {summary[:200]}"
        lines.append(entry)

    return "\n".join(lines)


def generate_daily_summary(market_data, news, holdings, market="us"):
    """Generate personalized daily summary via Claude API."""
    try:
        import anthropic
        import re

        client = anthropic.Anthropic(
            api_key=os.environ.get("ANTHROPIC_API_KEY"),
            base_url=os.environ.get("ANTHROPIC_BASE_URL"),
        )

        context = _serialize_market_context(market_data, news, holdings, market=market)
        holdings_symbols = ", ".join(h["symbol"] for h in holdings)
        system_prompt = SYSTEM_PROMPTS.get(market, SYSTEM_PROMPTS["us"])

        user_message = f"当前持仓: {holdings_symbols}\n\n{context}"

        with client.messages.stream(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            temperature=0.3,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        ) as stream:
            summary = ""
            for text in stream.text_stream:
                summary += text

        summary = re.sub(r"^\s*```(?:html)?\s*\n?", "", summary)
        summary = re.sub(r"\n?\s*```\s*$", "", summary)
        return summary.strip()

    except Exception as e:
        logger.warning(f"Claude API summary failed: {e}")
        return "<p>今日市场数据已更新，请查看上方详情。</p>"


# ============================================================================
# Section-level guidance via Claude API
# ============================================================================

SECTION_GUIDANCE_PROMPT = """你是面向投资小白的理财顾问。根据提供的市场数据，为以下三个区域各生成1-2句投资指导（用中文）。

要求：
1. 语气亲切通俗，用大白话解释数据含义和操作建议
2. 每个区域的建议要结合该区域的数据，不要泛泛而谈
3. 包含具体的数字参考（如"涨了X%"、"目标价Y"）
4. 对新手友好：解释专业术语（如"RSI超买意味着短期可能回调"）
5. 严格按 JSON 格式返回，key 为 market_overview / holdings / recommendations
6. 不要加 markdown 代码块标记

区域说明：
- market_overview: 市场总览区域，分析大盘走势和宏观环境对持仓的影响
- holdings: 持仓股票区域，逐只分析涨跌原因和短期操作建议（持有/加仓/减仓/观望）
- recommendations: 推荐关注区域，说明推荐逻辑和追入的风险提示"""


def generate_section_guidance(market_data, news, holdings, market="us"):
    """Generate per-section investment guidance via Claude API. Returns dict of section_key -> guidance_text."""
    try:
        import anthropic

        client = anthropic.Anthropic(
            api_key=os.environ.get("ANTHROPIC_API_KEY"),
            base_url=os.environ.get("ANTHROPIC_BASE_URL"),
        )

        context = _serialize_market_context(market_data, news, holdings, market=market)
        holdings_symbols = ", ".join(h["symbol"] for h in holdings)

        user_message = f"当前持仓: {holdings_symbols}\n\n{context}"

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            temperature=0.3,
            system=SECTION_GUIDANCE_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )

        import re
        text = response.content[0].text.strip()
        text = re.sub(r"^\s*```(?:json)?\s*\n?", "", text)
        text = re.sub(r"\n?\s*```\s*$", "", text)

        guidance = json.loads(text)
        if isinstance(guidance, dict):
            logger.info(f"Generated section guidance for {list(guidance.keys())}")
            return guidance

        logger.warning("Section guidance response is not a dict")
        return {}

    except Exception as e:
        logger.warning(f"Section guidance generation failed: {e}")
        return {}


# ============================================================================
# Report data
# ============================================================================

def build_report_data(market: str, market_html: str, market_data: dict,
                      news: list) -> dict:
    market_names = {"us": "美股日报", "cn": "A股日报"}
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    return {
        "subject": f"【{market_names.get(market, '投资日报')}】{now.year}年{now.month}月{now.day}日",
        "data_time": now.strftime("%Y-%m-%d %H:%M"),
        "date": now.strftime("%Y-%m-%d"),
        "global_metrics": build_global_metrics(market_data.get("indices", [])),
        "market_section_html": market_html,
        "news": news,
        "market": market,
    }


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
# Single-market pipeline
# ============================================================================

def _run_single_market(market: str, args):
    """Execute the full pipeline for a single market."""
    logger.info(f"{'=' * 60}")
    logger.info(f"invest-brief - Starting {market.upper()} market pipeline")

    # Step 1: Load config
    logger.info("Step 1: Loading configuration")
    config = load_config()
    all_recipients = [r for r in config.get("recipients", []) if r.get("active", True)]
    recipients = _filter_recipients(all_recipients, market)

    if not recipients:
        logger.info(f"No active recipients for market '{market}', skipping.")
        return

    logger.info(f"Found {len(recipients)} recipient(s) for market '{market}'")

    # Step 2: Merge settings
    logger.info("Step 2: Merging recipient settings")
    holdings, industries = merge_recipient_settings(recipients, market)
    holdings_symbols = [h["symbol"] for h in holdings]
    logger.info(f"Holdings: {holdings_symbols}, Industries: {industries}")

    # Step 3: Fetch market data
    logger.info("Step 3: Fetching market data")
    try:
        provider = _create_provider(market)
        cn_config = config.get("markets", {}).get(market, {})
        max_recs = cn_config.get("max_recommendations", 3)
        market_data = provider.fetch_all(holdings, industries, max_recommendations=max_recs)
        logger.info(f"Got {len(market_data.get('holdings', []))} holdings, {len(market_data.get('indices', []))} indices")
    except Exception as e:
        logger.warning(f"Market data fetch failed: {e}")
        market_data = {"indices": [], "holdings": [], "recommendations": []}

    # Step 4: Fetch news
    logger.info("Step 4: Fetching news")
    try:
        news = fetch_news(config, holdings_symbols, NEWS_LIMIT, industries, market=market)
        logger.info(f"Got {len(news)} news items")
    except Exception as e:
        logger.warning(f"News fetch failed: {e}")
        news = []

    # Step 5: Summarize news
    if news:
        logger.info("Step 5: Summarizing news via Claude API")
        news = summarize_news(news, market=market)
    else:
        logger.info("Step 5: No news to summarize")

    # Step 6: Generate per-section guidance
    skip_summary = getattr(args, 'skip_summary', False)
    section_guidance = {}
    if not skip_summary:
        logger.info("Step 6: Generating section guidance via Claude API")
        section_guidance = generate_section_guidance(market_data, news, holdings, market=market)
    else:
        logger.info("Step 6: Skipping section guidance (--skip-summary)")

    # Step 7: Render market HTML and build report data
    logger.info("Step 7: Building report data")
    try:
        render_config = {
            "color_up": "#e74c3c",
            "color_down": "#27ae60",
        }
        market_html = provider.render_section(market_data, render_config, guidance=section_guidance)
    except Exception as e:
        logger.warning(f"Market HTML render failed: {e}")
        market_html = "<p>市场数据渲染失败。</p>"

    report_data = build_report_data(market, market_html, market_data, news)

    if getattr(args, 'dry_run', False):
        logger.info("Dry run - outputting report data to stdout")
        print(json.dumps(report_data, ensure_ascii=False, indent=2, default=str))
        logger.info("Dry run complete")
        return

    # Step 8: Send report
    logger.info("Step 8: Sending report")
    send_report(report_data, config, recipients)

    # Save local preview
    try:
        from investbrief.report import load_template, render_template
        preview_dir = Path(__file__).parent / "reports"
        preview_dir.mkdir(exist_ok=True)
        template = load_template()
        preview_html = render_template(template, report_data, "zh-CN", {})
        preview_path = preview_dir / f"preview_{market}.html"
        preview_path.write_text(preview_html, encoding="utf-8")
        logger.info(f"Preview saved to {preview_path}")
    except Exception as e:
        logger.warning(f"Failed to save preview: {e}")

    logger.info(f"Market '{market}' pipeline complete")


# ============================================================================
# Run Once (immediate execution)
# ============================================================================

def run_once(args):
    """Execute the pipeline for selected market(s)."""
    market = args.market
    if market == "all":
        for m in ["us", "cn"]:
            _run_single_market(m, args)
    else:
        _run_single_market(market, args)


# ============================================================================
# Scheduler (cron-based long-running process)
# ============================================================================

def run_scheduler(config):
    """Run as a long-lived process, executing at cron-scheduled times."""
    # Try new-style per-market config first
    markets_cfg = config.get("markets", {})
    if markets_cfg:
        for market, cfg in markets_cfg.items():
            if not cfg.get("enabled", False):
                continue
            schedule = cfg.get("schedule", {})
            cron_expr = schedule.get("cron", "0 23 * * 1-5")
            _run_scheduled_market(market, cron_expr, config)
        return

    # Fallback to old-style single schedule
    schedule_cfg = config.get("schedule", {})
    cron_expr = schedule_cfg.get("cron", "0 23 * * 1-5")
    _run_scheduled_market("us", cron_expr, config)


def _run_scheduled_market(market: str, cron_expr: str, config: dict):
    """Run scheduled loop for a single market."""
    if not croniter.is_valid(cron_expr):
        logger.error(f"Invalid cron expression: {cron_expr}")
        return

    tz = ZoneInfo("Asia/Shanghai")
    now = datetime.now(tz)
    cron = croniter(cron_expr, now)
    next_run = cron.get_next(datetime)

    logger.info(f"Scheduler started for market '{market}' with cron: '{cron_expr}'")
    logger.info(f"Next run scheduled at: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")

    while not _shutdown:
        now = datetime.now(tz)

        if now >= next_run:
            logger.info(f"{'=' * 60}")
            logger.info(f"Scheduled run triggered for market '{market}'")

            args = argparse.Namespace(
                market=market,
                dry_run=False,
                skip_summary=False,
                log_level=logging.getLevelName(logger.getEffectiveLevel()),
            )

            try:
                _run_single_market(market, args)
            except Exception as e:
                logger.error(f"Scheduled run failed for market '{market}': {e}", exc_info=True)

            cron = croniter(cron_expr, now)
            next_run = cron.get_next(datetime)
            logger.info(f"Next run scheduled at: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")

        time.sleep(30)

    logger.info(f"Scheduler stopped for market '{market}'")


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="invest-brief - Personalized Investment Briefing")
    parser.add_argument(
        "--market",
        required=True,
        choices=["us", "cn", "all"],
        help="Market to run: us, cn, or all",
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
