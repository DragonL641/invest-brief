"""Macro report pipeline: fetch US+CN macro data, Claude synthesis, render, send."""
import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from investbrief.core.config import load_config, REPORTS_DIR
from investbrief.market import create_provider

logger = logging.getLogger(__name__)

NEWS_LIMIT = 5


def fetch_news(config, tickers, max_news_count, market="us"):
    """Fetch news for the specified market."""
    if market == "us":
        from investbrief.market.us.news import DataProvider
        provider = DataProvider(config)
        return provider.get_financial_news(
            tickers=tickers,
            limit=max_news_count,
            user_tickers=tickers,
        )
    elif market == "cn":
        from investbrief.market.cn.news import fetch_cn_news
        return fetch_cn_news(tickers, max_news_count)
    return []


def _safe_risk_score(model, market):
    """calculate_score with resilience — returns {} on failure (renders empty card)."""
    try:
        return model.calculate_score(market)
    except Exception as e:
        logger.warning(f"Risk score for {market} failed: {e}")
        return {}


def _safe_regime_judge(engine, market):
    """Regime judge with resilience — returns {} on failure (renders empty card)."""
    try:
        return engine.judge(market)
    except Exception as e:
        logger.warning(f"Regime judge for {market} failed: {e}")
        return {}


def run_macro_report(args):
    """Build ONE merged US+CN macro report and send to all active recipients."""
    logger.info("=" * 60)
    logger.info("invest-brief - Macro report pipeline (US+CN merged)")

    if getattr(args, "update", False):
        logger.info("Update-only mode: refreshing macro data, no render/send")
        us = create_provider("us")
        cn = create_provider("cn")
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
    us = create_provider("us")
    cn = create_provider("cn")
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
        news = fetch_news(config, [], NEWS_LIMIT, market="us") + \
            fetch_news(config, [], NEWS_LIMIT, market="cn")
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

    # 经济环境四象限(resilient — empty dict renders empty card)
    from investbrief.regime.engine import RegimeEngine
    from investbrief.regime.render import render_regime_card
    regime_engine = RegimeEngine(us.data)
    regime_data = {
        "us": _safe_regime_judge(regime_engine, "us"),
        "cn": _safe_regime_judge(regime_engine, "cn"),
    }
    us_regime_html = render_regime_card(regime_data["us"])
    cn_regime_html = render_regime_card(regime_data["cn"])

    # Claude ①⑥（一次调用同时生成核心观点 + 风险）
    if skip_summary:
        logger.info("Skipping Claude brief (--skip-summary)")
        macro_summary = "<p>（已跳过 AI 研判）</p>"
        risk_outlook = "<p>—</p>"
    else:
        logger.info("Generating macro brief via Claude (①⑥)")
        from investbrief.market.macro_brief import generate_macro_brief
        macro_summary, risk_outlook = generate_macro_brief(
            us_data, cn_data, news,
            risk_scores=risk_scores, regime_data=regime_data)

    # Research views (sell-side market commentary) — Tavily fetch + Claude synthesis
    research_views_html = ""
    if not skip_summary:
        try:
            from investbrief.market.research import fetch_research_views, generate_research_views
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
    us_html = us.render_section(us_data, render_config,
                                risk_html=us_risk_html, regime_html=us_regime_html)
    cn_html = cn.render_section(cn_data, render_config,
                                risk_html=cn_risk_html, regime_html=cn_regime_html)

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

    from investbrief.pipelines._send import send_report
    send_report(report_data, config, recipients)

    # Release gold data resources
    try:
        gold_data.close()
    except Exception:
        pass

    # Save local preview
    try:
        from investbrief.mail.render import render_template
        REPORTS_DIR.mkdir(exist_ok=True)
        preview_html = render_template("email_base.j2", report_data, "zh-CN")
        preview_path = REPORTS_DIR / "preview_macro.html"
        preview_path.write_text(preview_html, encoding="utf-8")
        logger.info(f"Preview saved to {preview_path}")
    except Exception as e:
        logger.warning(f"Failed to save preview: {e}")

    logger.info("Macro report pipeline complete")
