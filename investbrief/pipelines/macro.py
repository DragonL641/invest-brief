"""Macro report pipeline: fetch US+CN+Gold macro data, Claude synthesis, render, send."""
import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from investbrief.core.config import load_config, REPORTS_DIR, CONFIG_FILE, enabled_market_codes
from investbrief.core.timeutil import now_cn
from investbrief.market import create_provider

logger = logging.getLogger(__name__)

NEWS_LIMIT = 5


def _safe_regime_judge(engine, market):
    """Regime judge with resilience — returns {} on failure (renders empty card)."""
    try:
        return engine.judge(market)
    except Exception as e:
        logger.warning(f"Regime judge for {market} failed: {e}")
        return {}


_INDICATORS_FACTORIES = {
    "cn": "investbrief.market.cn.indicators:cn_indicators",
    "us": "investbrief.market.us.indicators:us_indicators",
    "gold": "investbrief.market.gold.indicators:gold_indicators",
}


def _build_indicators(market_code, data_source, config):
    """按市场加载 indicator 工厂(注册表分发, 加市场=加一行)。"""
    entry = _INDICATORS_FACTORIES.get(market_code)
    if entry is None:
        raise ValueError(f"No indicators factory for market: {market_code}")
    mod_path, func_name = entry.split(":")
    import importlib
    factory = getattr(importlib.import_module(mod_path), func_name)
    return factory(data_source, config)


def run_macro_report(args):
    """Build ONE merged multi-market macro report and send to all active recipients."""
    logger.info("=" * 60)
    logger.info("invest-brief - Macro report pipeline (multi-market merged)")

    if getattr(args, "update", False):
        logger.info("Update-only mode: refreshing macro data, no render/send")
        config = load_config()
        for code in enabled_market_codes(config):
            try:
                create_provider(code).refresh(force=True)
            except Exception as e:
                logger.warning(f"{code} data refresh failed in update-only mode: {e}")
        logger.info("Update-only complete")
        return

    config = load_config()
    recipients = [r for r in config.get("recipients", []) if r.get("active", True)]
    if not recipients:
        logger.info("No active recipients, skipping.")
        return

    # 日级缓存：命中（非 --force）→ 直接发缓存 HTML，跳过整个 build（省 refresh+fetch+Claude）
    from investbrief.core.mail_cache import make_key, get_cache, set_cache
    today = now_cn().strftime("%Y-%m-%d")
    cache_key = make_key("macro", today)
    if not getattr(args, "force", False) and not getattr(args, "dry_run", False):
        cached = get_cache(cache_key)
        if cached:
            logger.info(f"Macro cache hit ({cache_key}), sending cached HTML")
            from investbrief.mail.sender import EmailSender
            now = now_cn()
            subject = f"【宏观经济日报】{now.strftime('%Y年%m月%d日')}"
            sender = EmailSender(str(CONFIG_FILE))
            messages = [{"to": r["email"], "subject": subject, "html": cached} for r in recipients]
            sent, failed = sender.send_bulk(messages)
            if failed:
                if len(failed) == len(recipients):
                    raise RuntimeError(f"All {len(recipients)} macro recipients failed (cached): "
                                       f"{[f[0] for f in failed]}")
                logger.warning(f"{len(failed)}/{len(recipients)} macro recipients failed (cached): "
                               f"{[f[0] for f in failed]}")
            logger.info("Macro report pipeline complete (cached)")
            return

    render_config = {"color_up": "#e74c3c", "color_down": "#27ae60"}
    skip_summary = getattr(args, "skip_summary", False)

    # 遍历 enabled markets —— 消除硬编码 us/cn/gold 流程
    market_codes = [c for c in enabled_market_codes(config) if c != "us"]  # us 由外围卡替代(Task 13 删 us provider)
    logger.info(f"Enabled markets: {market_codes}")
    providers = {code: create_provider(code) for code in market_codes}

    # refresh（并行; 单市场失败不阻塞, get_* 回退库内最新值）
    from concurrent.futures import ThreadPoolExecutor

    def _safe_refresh(fn, label):
        try:
            fn()
        except Exception as e:
            logger.warning(f"{label} data refresh failed, falling back to stored values: {e}")

    with ThreadPoolExecutor(max_workers=max(2, len(market_codes))) as ex:
        for code, p in providers.items():
            ex.submit(lambda p=p, c=code: _safe_refresh(p.refresh, c.upper()))

    # 各市场收集 macro 数据（按能力声明调 macro_brief 仍接收 us/cn 字段）
    market_macro = {}
    for code, p in providers.items():
        market_macro[code] = {
            "monetary_policy": p.get_monetary_policy(),
            "asset_performance": p.get_asset_performance(),
            "economic_calendar": p.get_economic_calendar(),
        }

    # news（各市场 get_news 合并; gold 默认返回空）
    news = []
    try:
        for code, p in providers.items():
            news += p.get_news(config, NEWS_LIMIT)
        news = news[:NEWS_LIMIT]
    except Exception as e:
        logger.warning(f"News fetch failed: {e}")

    # risk（每市场用自己的 indicators 实例注入 RiskModel）
    from investbrief.risk.models import RiskModel
    from investbrief.risk.render import render_risk_card, render_gold_section
    from investbrief.risk.config import load_indicators
    any_data = next(iter(providers.values())).data
    risk_scores, risk_html = {}, {}
    for code, p in providers.items():
        if not p.risk_group:
            continue
        try:
            ind_config = load_indicators(p.risk_group)
            indicators = _build_indicators(code, p.data, ind_config)
            model = RiskModel(p.data, indicators=indicators)
            risk_scores[code] = model.calculate_score(code)
        except Exception as e:
            logger.warning(f"Risk score for {code} failed: {e}")
            risk_scores[code] = {}
        if code == "gold":
            risk_html[code] = render_gold_section(risk_scores[code])
        else:
            risk_html[code] = render_risk_card(risk_scores[code])

    # regime（只对 supports_regime 的市场）
    from investbrief.regime.engine import RegimeEngine
    from investbrief.regime.render import render_regime_card
    regime_engine = RegimeEngine(any_data)
    regime_data, regime_html = {}, {}
    for code, p in providers.items():
        if p.supports_regime:
            regime_data[code] = _safe_regime_judge(regime_engine, code)
            regime_html[code] = render_regime_card(regime_data[code])

    # 外围环境卡(全 akshare,替换原 US section)
    from investbrief.datasources.akshare import AKShareClient
    from investbrief.market.overseas import fetch_overseas_data, render_overseas_card
    try:
        overseas_data = fetch_overseas_data(AKShareClient())
        overseas_html = render_overseas_card(overseas_data)
    except Exception as e:
        logger.warning(f"Overseas card failed: {e}")
        overseas_data, overseas_html = {}, ""
    overseas_for_claude = {
        "美联储利率": overseas_data.get("fed_rate"),
        "美债10Y": overseas_data.get("us_10y"),
        "标普500": (overseas_data.get("sp500") or {}).get("point"),
        "USDCNY": overseas_data.get("usdcny"),
    }

    # Claude ①⑥（传外围 + cn macro + 全市场 risk/regime）
    if skip_summary:
        logger.info("Skipping Claude brief (--skip-summary)")
        macro_summary = "<p>（已跳过 AI 研判）</p>"
        risk_outlook = "<p>—</p>"
    else:
        logger.info("Generating macro brief via Claude (①⑥)")
        from investbrief.market.macro_brief import generate_macro_brief
        macro_summary, risk_outlook = generate_macro_brief(
            overseas_for_claude, market_macro.get("cn", {}), news,
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

    # render sections（按 market_codes 顺序; gold 的 risk_html 已是 render_gold_section 输出, gold.render_section 透传返回）
    sections = [overseas_html] if overseas_html else []
    for code, p in providers.items():
        kwargs = dict(risk_html=risk_html.get(code, ""), regime_html=regime_html.get(code, ""))
        if code == "cn" and hasattr(p, "get_sentiment"):
            try:
                kwargs["sentiment"] = p.get_sentiment()
            except Exception as e:
                logger.warning(f"CN sentiment fetch failed: {e}")
        sections.append(p.render_section(market_macro[code], render_config, **kwargs))
    market_section_html = "".join(sections)

    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    report_data = {
        "subject": f"【宏观经济日报】{now.strftime('%Y年%m月%d日')}",
        "data_time": now.strftime("%Y-%m-%d %H:%M"),
        "date": now.strftime("%Y-%m-%d"),
        "market": "all",
        "macro_summary": macro_summary,
        "risk_outlook": risk_outlook,
        "market_section_html": market_section_html,
        "research_views": research_views_html,
        "news": news,
    }

    if getattr(args, "dry_run", False):
        logger.info("Dry run - outputting report data to stdout")
        print(json.dumps(report_data, ensure_ascii=False, indent=2, default=str))
        # Release SQLite connections (each provider holds one)
        try:
            for p in providers.values():
                p.data.close()
        except Exception:
            pass
        return

    from investbrief.pipelines._send import send_report
    send_report(report_data, config, recipients)

    # Release SQLite connections (each provider holds one)
    try:
        for p in providers.values():
            p.data.close()
    except Exception:
        pass

    # Save local preview
    preview_html = None
    try:
        from investbrief.mail.render import render_template
        REPORTS_DIR.mkdir(exist_ok=True)
        preview_html = render_template("email_base.j2", report_data, "zh-CN")
        preview_path = REPORTS_DIR / "preview_macro.html"
        preview_path.write_text(preview_html, encoding="utf-8")
        logger.info(f"Preview saved to {preview_path}")
    except Exception as e:
        logger.warning(f"Failed to save preview: {e}")
    if preview_html:
        set_cache(cache_key, preview_html)  # 写缓存移到 try 外（preview_html render 失败则跳过）

    logger.info("Macro report pipeline complete")
