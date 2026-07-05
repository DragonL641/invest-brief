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

    # 取流动性最好的 cap 只作为候选池(避免无排序时取到随机切片)
    turnover_col = next((c for c in ("成交额", "amount", "turnover") if c in candidates_df.columns), None)
    if turnover_col:
        candidates_df = candidates_df.sort_values(by=turnover_col, ascending=False)
    candidates_df = candidates_df.head(_candidate_cap(profile_name))

    u = prof.get("universe", {})
    gates = u.get("fundamental_gates") or {}
    max_5d_gain = u.get("max_5d_gain")
    min_listed_days = u.get("min_listed_days")
    min_listed_years = u.get("min_listed_years")
    cands = []
    for _, row in candidates_df.iterrows():
        symbol = str(row.get("代码") if market == "cn" else row.get("代码", row.get("symbol", "")))
        if not symbol:
            continue
        try:
            hist = _data.fetch_history(symbol, market, days=_history_days(profile_name))
            fund = _data.fetch_fundamentals(symbol, market) if profile_name != "swing" else {}
            if hist is None or hist.empty:
                continue
            # 深拉阶段校验:基本面 gate(只在数据存在时执行,缺失则跳过该 gate)
            if gates and not _passes_fundamental_gates(fund, gates, symbol, market):
                continue
            # 深拉阶段校验:5 日涨幅上限(swing)
            if max_5d_gain and not _passes_price_gates(hist, max_5d_gain):
                continue
            # 深拉阶段校验:上市时长(TODO A: earliest_report_period 代理)
            if (min_listed_days or min_listed_years) and not _passes_listing_gates(
                    symbol, market, min_listed_days, min_listed_years):
                continue
            val = _valuation_for(row, market) if "valuation" in prof["factors"] else {}
            raw = {}
            for fkey in prof["factors"]:
                fn = _factors.FACTOR_REGISTRY.get(fkey)
                raw[fkey] = fn(hist, fund, val) if fn else None
            cands.append({"symbol": symbol, "name": str(row.get("名称", symbol)),
                          "market": market, "raw_factors": raw,
                          "industry": _industry_for(symbol, market)})
        except Exception as e:
            logger.warning(f"candidate {market}:{symbol} failed: {e}")
            continue

    prof_with_name = {**prof, "_name": profile_name}
    ranked = _engine.rank_picks(cands, prof_with_name, market)
    if not ranked:
        return None
    top = ranked[0]
    # 补 price/key_mas/stop_level(从历史)——必须在渲染前完成
    _enrich(top, _data.fetch_history(top["symbol"], market, days=120), prof)
    return top


def _passes_fundamental_gates(fund: dict, gates: dict, symbol: str = "",
                              market: str = "") -> bool:
    """基本面 gate 校验:仅在数据实际可用时执行,缺失数据不静默过滤。

    - min_roe_4q: roe 已归一化为小数,低于阈值 → 失败
    - positive_operating_cashflow: 仅当 fund 含 fcf_positive 时才校验
      (TODO C 已为 CN 接入;缺失/NaN → 跳过)
    - min_profitable_years: TODO B;fetch 返回 int 时校验,返回 None(数据缺失) → 跳过
    """
    min_roe = gates.get("min_roe_4q")
    if min_roe is not None:
        roe = fund.get("roe")
        if roe is not None and roe < min_roe:
            return False
    pos_cf = gates.get("positive_operating_cashflow")
    if pos_cf and "fcf_positive" in fund and not fund["fcf_positive"]:
        return False
    # TODO B: profitable years(数据缺失 → 跳过,不静默过滤)
    min_years = gates.get("min_profitable_years")
    if min_years is not None and symbol and market:
        years = _data.fetch_profitable_years(symbol, market)
        if years is not None and years < min_years:
            return False
    return True


def _passes_price_gates(hist, max_5d_gain: float) -> bool:
    """5 日涨幅上限校验(swing 深拉阶段)。数据不足 → 通过(不静默过滤)。"""
    try:
        if hist is None or len(hist) < 6:
            return True
        ret = hist["close"].iloc[-1] / hist["close"].iloc[-6] - 1
        return bool(ret <= max_5d_gain)
    except Exception:
        return True


def _passes_listing_gates(symbol: str, market: str, min_days: int | None,
                          min_years: int | None) -> bool:
    """上市时长 gate(TODO A: earliest_report_period 代理)。

    代理: 用最早可得财报报告期作为上市时长的下界。报告期可能含 pre-IPO 数据,
    故本代理偏保守(高估上市时长),不会误剔新股的"老股"。

    - min_listed_years: (today - earliest_period).days / 365.25 ≥ min_years
    - min_listed_days:  (today - earliest_period).days ≥ min_days × 0.69(近似交易日)
      (250 交易日 ≈ 1.2 年;0.69 系数把 250 转为 ~363 自然日)
    数据缺失(earliest_period fetch 返回 None) → 通过(不静默过滤)。
    """
    if not symbol or (min_days is None and min_years is None):
        return True
    try:
        earliest = _data.fetch_earliest_report_period(symbol, market)
        if not earliest:
            return True
        from datetime import datetime as _dt
        # earliest 形如 '1998-12-31'(CN) 或 '2021-09-30'(US financials col)
        first_dt = _dt.strptime(str(earliest)[:10], "%Y-%m-%d")
        days = (_dt.now() - first_dt).days
        if min_years is not None and days / 365.25 < min_years:
            return False
        if min_days is not None:
            # 250 交易日 ≈ 1.2 年,系数 ~1.45 把自然日换交易日;但保守用 0.69(=1/1.45)
            # 反向校验: 实际自然日 / 0.69 ≥ 250 才算 250 交易日
            trading_days_approx = days * 0.69
            if trading_days_approx < min_days:
                return False
        return True
    except Exception:
        return True


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
    """从 spot 行取 PE/PB;3 年分位留空(深拉估值历史在 data 增强,首版用截面分位回退)。

    CN stock_zh_a_spot_em: 市盈率-动态 / 市净率;US stock_us_spot_em: 市盈率(无 市净率)。
    """
    if market == "cn":
        pe = _num(row, "市盈率-动态")
        pb = _num(row, "市净率")
    else:
        pe = _num(row, "市盈率")   # stock_us_spot_em has 市盈率 (no 市净率)
        pb = None
    return {"pe": pe, "pb": pb, "pe_pct_3y": None, "pb_pct_3y": None, "peg": None}


def _industry_for(symbol: str, market: str):
    """候选股行业标签(用于 industry_neutralize)。

    US: yfinance info['sector'](fetch_industry 缓存 30 天)
    CN: stock_individual_info_em 接口对全市场崩(Length mismatch),返回 None 降级。
    """
    if not symbol:
        return None
    return _data.fetch_industry(symbol, market)


def _num(row, col):
    if not col or col not in row:
        return None
    try:
        v = float(row[col])
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def _safe_build(profile_name: str, market: str):
    """build_picks_for_profile 的韧性包装:任何异常 → None(占位卡),不阻塞 pipeline。"""
    try:
        return build_picks_for_profile(profile_name, market)
    except Exception as e:
        logger.warning(f"build_picks_for_profile {profile_name}/{market} failed: {e}")
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
        cn = _safe_build(prof_name, "cn")
        us = _safe_build(prof_name, "us")
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
