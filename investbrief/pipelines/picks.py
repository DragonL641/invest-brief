# investbrief/pipelines/picks.py
"""股票推荐 pipeline:三 profile × 两市场 选 Top1 → 6 只 → Claude 研判 → 渲染 → 发送。"""
import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from investbrief.core.config import load_config, CONFIG_FILE, REPORTS_DIR, DB_PATH
from investbrief.picks import profiles as _profiles
load_profiles = _profiles.load_profiles  # 模块级 alias,便于测试 monkeypatch(与 _spot_df 对称)
from investbrief.picks import universe as _universe
from investbrief.picks import data as _data
from investbrief.picks import factors as _factors
from investbrief.picks import engine as _engine
from investbrief.picks import renderer as _renderer
from investbrief.picks import brief as _brief

logger = logging.getLogger(__name__)

_CACHE_PATH = str(DB_PATH).replace("macro_data.db", "picks_cache.db")
_PROFILES = ("swing", "medium", "long")
_MARKETS = ("cn", "us")


def _spot_df(market: str):
    return _universe.get_spot_df(market)


def build_picks_for_profile(profile_name: str, market: str) -> dict | None:
    """跑单 profile×市场 → Top1 pick(或 None)。"""
    try:
        prof = load_profiles()[profile_name]
    except Exception as e:
        logger.warning(f"profile {profile_name} load failed: {e}")
        return None
    spot = _spot_df(market)
    candidates_df = _universe.coarse_filter(spot, prof, market)
    if candidates_df is None or candidates_df.empty:
        logger.info(f"{profile_name}/{market}: no candidates after coarse filter")
        return None

    # 深拉 + 因子(限制候选数,控制 eastmoney 调用)
    cap = _candidate_cap(profile_name)
    candidates_df = candidates_df.head(cap)
    cands = []
    for _, row in candidates_df.iterrows():
        symbol = str(row.get("代码") if market == "cn" else row.get("代码", row.get("symbol", "")))
        if not symbol:
            continue
        hist = _data.fetch_history(symbol, market, days=_history_days(profile_name))
        fund = _data.fetch_fundamentals(symbol, market) if profile_name != "swing" else {}
        val = _valuation_for(row, market) if "valuation" in prof["factors"] else {}
        if hist is None or hist.empty:
            continue
        raw = {}
        for fkey in prof["factors"]:
            fn = _factors.FACTOR_REGISTRY.get(fkey)
            raw[fkey] = fn(hist, fund, val) if fn else None
        cands.append({"symbol": symbol, "name": str(row.get("名称", symbol)),
                      "market": market, "raw_factors": raw,
                      "industry": _industry_for(row, market)})

    prof_with_name = {**prof, "_name": profile_name}
    ranked = _engine.rank_picks(cands, prof_with_name, market)
    if not ranked:
        return None
    top = ranked[0]
    # 补 price/key_mas/stop_level(从历史)——必须在渲染前完成
    _enrich(top, _data.fetch_history(top["symbol"], market, days=120), prof)
    return top


def _enrich(pick: dict, hist, prof: dict):
    try:
        if hist is None or hist.empty:
            return
        from investbrief.core import ta
        c = hist["close"]
        pick["price"] = ta._last(c)
        mas = ta.ma_set(c, (20, 60, 120))
        pick["key_mas"] = {"ma20": mas.get("ma20"), "ma60": mas.get("ma60"), "ma120": mas.get("ma120")}
        risk = prof.get("risk", {})
        if risk.get("stop_break_ma20") and mas.get("ma20"):
            pick["stop_level"] = round(mas["ma20"] * (1 - risk.get("stop_max_dd", 0.08)), 2)
        elif risk.get("stop_break_ma60") and mas.get("ma60"):
            pick["stop_level"] = round(mas["ma60"], 2)
    except Exception as e:
        logger.warning(f"enrich {pick.get('symbol')} failed: {e}")


def _candidate_cap(profile_name: str) -> int:
    return {"swing": 60, "medium": 80, "long": 60}.get(profile_name, 60)


def _history_days(profile_name: str) -> int:
    return {"swing": 180, "medium": 260, "long": 120}.get(profile_name, 180)


def _valuation_for(row, market: str) -> dict:
    """从 spot 行取 PE/PB;3 年分位留空(深拉估值历史在 data 增强,首版用截面分位回退)。"""
    pe = _num(row, "市盈率-动态" if market == "cn" else None)
    pb = _num(row, "市净率" if market == "cn" else None)
    return {"pe": pe, "pb": pb, "pe_pct_3y": None, "pb_pct_3y": None, "peg": None}


def _industry_for(row, market: str):
    return None  # 首版不接入行业(中性化接口已留)


def _num(row, col):
    if not col or col not in row:
        return None
    try:
        v = float(row[col])
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def run_picks_report(args):
    """编排:6 只 Top1 → 研判 → 渲染 → 发送(dry_run 打印 JSON;preview 渲染不发)。"""
    logger.info("=" * 60)
    logger.info("invest-brief - Picks pipeline (6 Top1)")
    _data.init_cache(_CACHE_PATH)

    config = load_config()
    recipients = [r for r in config.get("recipients", []) if r.get("active", True)]
    if not recipients:
        logger.info("No active recipients, skipping picks.")
        return

    all_picks: list[dict] = []
    sections_html = ""
    for prof_name in _PROFILES:
        cn = build_picks_for_profile(prof_name, "cn")
        us = build_picks_for_profile(prof_name, "us")
        all_picks += [p for p in (cn, us) if p]
        sections_html += _renderer.render_pick_section(prof_name, cn, us)

    skip_summary = getattr(args, "skip_summary", False)
    picks_brief = "" if skip_summary else _brief.generate_picks_brief(all_picks)

    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    report_data = {
        "data_time": now.strftime("%Y-%m-%d %H:%M"),
        "picks_brief": picks_brief,
        "picks_sections": sections_html,
        "picks": all_picks,
    }

    if getattr(args, "dry_run", False):
        print(json.dumps(report_data, ensure_ascii=False, indent=2, default=str))
        return

    from investbrief.mail.render import render_picks_template
    html = render_picks_template("email_picks.j2", report_data, "zh-CN")

    # preview_picks.html 始终存(发或不发都存)
    try:
        REPORTS_DIR.mkdir(exist_ok=True)
        (REPORTS_DIR / "preview_picks.html").write_text(html, encoding="utf-8")
    except Exception as e:
        logger.warning(f"save picks preview failed: {e}")

    if getattr(args, "preview", False):
        logger.info("Preview mode: rendered to reports/preview_picks.html, not sent.")
        return

    subject = f"【股票推荐】{now.strftime('%Y年%m月%d日')}"
    from investbrief.mail.sender import EmailSender
    sender = EmailSender(str(CONFIG_FILE))
    messages = [{"to": r["email"], "subject": subject, "html": html} for r in recipients]
    sent, failed = sender.send_bulk(messages)
    if failed:
        logger.warning(f"{len(failed)}/{len(recipients)} picks recipients failed: "
                       f"{[f[0] for f in failed]}")
    logger.info("Picks pipeline complete")
