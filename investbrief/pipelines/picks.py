# investbrief/pipelines/picks.py
"""股票推荐 pipeline:三 profile × CN 选 Top1 → 3 只 → Claude 研判 → 渲染 → 发送。"""
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

from investbrief.core.config import load_config, CONFIG_FILE, REPORTS_DIR, DB_PATH
from investbrief.core.timeutil import now_cn
from investbrief.mail.sender import EmailSender
from investbrief.picks import profiles as _profiles
load_profiles = _profiles.load_profiles  # 模块级 alias,便于测试 monkeypatch(与 _spot_df 对称)
from investbrief.picks import universe as _universe
from investbrief.picks import data as _data
from investbrief.picks import factors as _factors
from investbrief.picks import engine as _engine
from investbrief.picks import renderer as _renderer
from investbrief.picks import brief as _brief

logger = logging.getLogger(__name__)

_CACHE_PATH = str(Path(DB_PATH).with_name("picks_cache.db"))
# holdings analyzer 季频缓存(rating/fund/cn_activity, TTL=7d)。与 picks_cache.db 必须隔离:
# fund:cn:{symbol} 两库语义不同(picks 归一化小数 / holdings 原始百分数),合并会读串,不可合并。
_HOLDINGS_CACHE_PATH = str(Path(DB_PATH).with_name("holdings_cache.db"))
_PROFILES = ("swing", "medium", "long")

# 候选股深拉并发度:对齐 holdings/analyzer.py(2),更高会触发 eastmoney 限流。
_DEEP_PULL_WORKERS = 2


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
    # 基线 cap 作为候选池;动态收缩靠 futures 循环早停(见下)。
    effective_cap = _candidate_cap(profile_name)
    candidates_df = candidates_df.head(effective_cap)

    u = prof.get("universe", {})
    gates = u.get("fundamental_gates") or {}
    max_5d_gain = u.get("max_5d_gain")
    min_listed_days = u.get("min_listed_days")
    min_listed_years = u.get("min_listed_years")
    hist_days = _history_days(profile_name)
    # needs_fund: 基本面 gate 或 任一 fundamental 类因子 → 打分阶段需 fund。
    # swing 纯技术面(无 gate + 无 fundamental 因子)→ 打分阶段 fund={},Top1 选定后单独拉 fund 给卡片。
    # main_flow 属 flow 类(从 fund['main_flow_5d'] 读,由 fetch_flow 注入,不依赖 fetch_fundamentals)。
    needs_fund = bool(gates) or any(
        _factors.FACTOR_CATEGORY.get(f) == "fundamental" for f in prof["factors"]
    )

    # 限流代理计数(线程安全):数据层 fetch_history 限流时吞异常返回空 df,
    # _process_candidate 在 hist 空返回时累加 limit_hits;futures 循环据此早停。
    # 注:不嗅探 except 异常文案——网络限流根本到不了 except(被数据层吞掉返回空)。
    limit_hits = {"n": 0}
    limit_lock = threading.Lock()

    def _bump_limit():
        with limit_lock:
            limit_hits["n"] += 1

    def _process_candidate(row) -> tuple[dict, tuple] | None:
        """工作线程:单候选深拉 + gate 校验 + 因子计算 → (cand, (symbol, (hist, fund, val))) | None。"""
        raw_code = str(row.get("代码", row.get("symbol", "")))
        symbol = raw_code
        if not symbol:
            return None
        try:
            hist = _data.fetch_history(symbol, market, days=hist_days)
            if hist is None or hist.empty:
                # 空返回 = 限流代理信号(数据层 fetch_history 限流时吞异常返回空 df,
                # 到不了 except)。计数累加,futures 循环在 ≥25 时早停。
                # 阈值 25 足够高,偶发的合法空返回(新股/ETF 数据缺失)不会误触发。
                _bump_limit()
                return None
            fund = _data.fetch_fundamentals(symbol, market) if needs_fund else {}
            # main_flow 因子(CN only):近5日主力资金流,只在 profile 启用该因子时拉取(限流保护)。
            # 用 spread 构造新 dict 避免污染 fund 的 7 天缓存。
            if "main_flow" in prof["factors"]:
                fund = {**fund, "main_flow_5d": _data.fetch_flow(symbol, market, days=5)}
            # profitability_stability 因子:连续盈利年数。gate(min_profitable_years)也用此值,
            # 拉一次注入 fund 供两者复用(fetch_profitable_years 自带 30d 缓存兜底跨调用)。
            if "profitability_stability" in prof["factors"] or gates.get("min_profitable_years"):
                fund = {**fund, "profitable_years": _data.fetch_profitable_years(symbol, market)}
            # 深拉阶段校验:基本面 gate(只在数据存在时执行,缺失则跳过该 gate)
            if gates and not _passes_fundamental_gates(fund, gates, symbol, market):
                return None
            # 深拉阶段校验:5 日涨幅上限(swing)
            if max_5d_gain and not _passes_price_gates(hist, max_5d_gain):
                return None
            # 深拉阶段校验:上市时长(TODO A: earliest_report_period 代理)
            if (min_listed_days or min_listed_years) and not _passes_listing_gates(
                    symbol, market, min_listed_days, min_listed_years):
                return None
            val = _valuation_for(row, market)  # pe/pb 是卡片展示维度,总是取(spot 已有,零成本);不止 valuation 因子时用
            raw = {}
            for fkey in prof["factors"]:
                fn = _factors.FACTOR_REGISTRY.get(fkey)
                raw[fkey] = fn(hist, fund, val) if fn else None
            cand = {"symbol": symbol, "name": str(row.get("名称", symbol)),
                    "market": market, "raw_factors": raw,
                    "industry": None}
            return cand, (symbol, (hist, fund, val))
        except Exception as e:
            # 非网络异常(因子计算/gate/KeyError 等)——不是限流,不计入 limit_hits。
            logger.warning(f"candidate {market}:{raw_code} failed: {e}")
            return None

    cands: list[dict] = []
    detail: dict[str, tuple] = {}  # symbol -> (hist, fund, val) 供 Top1 补齐卡片展示维度
    rows = list(candidates_df.iterrows())
    with ThreadPoolExecutor(max_workers=_DEEP_PULL_WORKERS) as ex:
        futures = [ex.submit(_process_candidate, row) for _, row in rows]
        for fut in futures:
            r = fut.result()
            # 空返回计数 ≥ 早停阈值(限流代理信号累积)→ cancel 未启动 future + break,保速度
            if limit_hits["n"] >= _RATE_LIMIT_EARLY_STOP_HITS:
                for f in futures:
                    f.cancel()
                logger.warning(
                    f"{profile_name}/{market}: heavy rate-limit "
                    f"(hits={limit_hits['n']}), early-stop deep-pull"
                )
                break
            if r is None:
                continue
            cand, (sym, det) = r
            cands.append(cand)
            detail[sym] = det

    prof_with_name = {**prof, "_name": profile_name}
    ranked = _engine.rank_picks(cands, prof_with_name, market)
    if not ranked:
        return None
    top = ranked[0]
    # 补 price/key_mas/stop + 技术面/基本面/估值(卡片展示用)——必须在渲染前完成
    _h, _f, _v = detail.get(top["symbol"], (None, {}, {}))
    # swing 两阶段:打分阶段未拉 fund(纯技术面)→ Top1 选定后单独拉 fund 给卡片展示。
    # medium/long(needs_fund)打分阶段已拉 fund,_f 已含 roe/gm 等,跳过。
    if not needs_fund and top.get("symbol"):
        fetched = _data.fetch_fundamentals(top["symbol"], market)
        _f = {**(_f or {}), **fetched}
    _enrich(top, _h, prof, _f, _v)
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
    # fund['profitable_years'] 由 _process_candidate 注入(复用,避免二次拉取);
    # 缺失(long profile 未走注入路径或 fetch 返回 None)时回退到直接 fetch。
    min_years = gates.get("min_profitable_years")
    if min_years is not None and symbol and market:
        years = fund.get("profitable_years")
        if years is None:
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


def _compute_stop_level(close: float | None, ma20, ma60, risk: dict | None) -> float | None:
    """止损价:取「趋势信号线(MA)」与「现价下拽 max_dd」的较小者,恒低于现价。

    下跌趋势里 MA 可能高于现价(云铝 MA60=28.44 > 现价 23.15),直接用 MA 会得到
    「止损>现价」的荒谬值;clamp 到 close*(1-max_dd) 确保止损始终在现价下方。

    注:max_dd 此处语义为「自现价的回撤」(stop ≤ close*(1-max_dd)),区别于旧实现
    的「MA 下方再打 max_dd 折」——上涨趋势里新止损会比旧逻辑更接近现价(更松)。
    """
    if not close:
        return None
    max_dd = (risk or {}).get("stop_max_dd", 0.08)
    price_stop = close * (1 - max_dd)
    if risk and risk.get("stop_break_ma20") and ma20:
        return round(min(ma20, price_stop), 2)
    if risk and risk.get("stop_break_ma60") and ma60:
        return round(min(ma60, price_stop), 2)
    return round(price_stop, 2)


def _enrich(pick: dict, hist, prof: dict, fund: dict | None = None, val: dict | None = None):
    """补 price/key_mas/stop + 技术面/基本面/估值(卡片展示维度)。"""
    try:
        if hist is None or hist.empty:
            return
        from investbrief.core import ta
        c = hist["close"]
        close = float(c.iloc[-1])
        pick["price"] = round(close, 2)
        # 今日涨跌幅(close vs 前收)—— 卡片 price_row 展示 + AI 研判引用
        if len(c) > 1:
            _prev_close = float(c.iloc[-2])
            pick["change_pct"] = round((close - _prev_close) / _prev_close * 100, 2) if _prev_close else None
        # 量比(今日量 / 近 20 日均量)—— 卡片技术面展示 + AI「放量」引用
        _vol_ratio = None
        if "volume" in hist.columns:
            _vol = pd.to_numeric(hist["volume"], errors="coerce").dropna().tail(21)
            if len(_vol) >= 2 and _vol.iloc[-1] and _vol.iloc[:-1].mean():
                _vol_ratio = round(float(_vol.iloc[-1]) / float(_vol.iloc[:-1].mean()), 2)
        mas = ta.ma_set(c, (5, 10, 20, 60, 120))   # 含 5/10/20 才能算 ma_alignment
        ma20, ma60, ma120 = mas.get("ma20"), mas.get("ma60"), mas.get("ma120")
        pick["key_mas"] = {"ma20": ma20, "ma60": ma60, "ma120": ma120}
        pick["stop_level"] = _compute_stop_level(close, ma20, ma60, prof.get("risk", {}))
        # 关键价位(卡片标题展示):压力=近60日最高,支撑=近60日最低
        if "high" in hist.columns and "low" in hist.columns:
            pick["key_levels"] = {
                "resistance": round(float(hist["high"].tail(60).max()), 2),
                "support":    round(float(hist["low"].tail(60).min()), 2),
            }
        # 技术面(卡片展示)
        macd = ta.macd(c)
        rets = ta.returns(c)
        pick["technicals"] = {
            "rsi": ta.rsi(c), "macd_cross": macd.get("macd_cross"), "macd_bar": macd.get("macd_bar"),
            "ma_alignment": mas.get("ma_alignment"),
            "return_5d": rets.get("return_5d"), "return_20d": rets.get("return_20d"),
            "return_60d": rets.get("return_60d"),
            "ma20": ma20, "ma60": ma60, "ma120": ma120,
            "close_vs_ma60_pct": (close / ma60 - 1) if (ma60 and close and ma60 != 0) else None,
            "volume_ratio": _vol_ratio,
        }
        # 基本面 + 估值(merge fund + val.pe/pb)
        pick["fundamentals"] = {**(fund or {}), "pe": (val or {}).get("pe"), "pb": (val or {}).get("pb")}
    except Exception as e:
        logger.warning(f"enrich {pick.get('symbol')} failed: {e}")


def _enrich_with_holdings(pick: dict, analyzer, with_ai: bool):
    """复用 holdings 逐股分析,补 机构态度/盈利预测/综合研判。

    analyzer 由调用方(run_picks_report)传入:run 级单例 + 机构调研 batch 预注入
    (set_research_batch),避免每只 Top1 走 90 次/股的单股 fallback。
    编排层(pipelines)调用 holdings.analyzer —— 不破坏"域间不互引"不变量
    (picks 域本身不 import holdings)。失败降级(维度缺省,不阻塞)。
    """
    try:
        hr = analyzer.analyze_one(pick["symbol"], pick["market"], "stock", with_ai=with_ai)
        if hr.rating:
            pick["rating"] = hr.rating
        if hr.forecast:
            pick["forecast"] = hr.forecast
        if hr.ai_conclusion:
            pick["ai_conclusion"] = hr.ai_conclusion
    except Exception as e:
        logger.warning(f"holdings enrich {pick.get('symbol')} failed: {e}")


def _candidate_cap(profile_name: str) -> int:
    return {"swing": 30, "medium": 40, "long": 30}.get(profile_name, 30)


# 限流早停:build_picks_for_profile 内 _process_candidate 把"空返回"作为限流
# 代理信号(数据层 fetch_history 限流时吞异常返回空 df),累加 limit_hits;
# 超 25 次则 futures 循环 cancel 未启动 future + break,保速度。
# limit_hits 是原始"空返回"计数(线程安全累加)。
_RATE_LIMIT_EARLY_STOP_HITS = 25


def _history_days(profile_name: str) -> int:
    # long=400:momentum_12m_ex1m 需 252 交易日;CN akshare 400 自然日≈270 交易日。
    # swing 180 / medium 260 不变。
    return {"swing": 180, "medium": 260, "long": 400}.get(profile_name, 180)


def _valuation_for(row, market: str) -> dict:
    """从 spot 行取 PE/PB;3 年分位留空(深拉估值历史在 data 增强,首版用截面分位回退)。

    CN stock_zh_a_spot_em: 市盈率-动态 / 市净率。
    """
    pe = _num(row, "市盈率-动态")
    pb = _num(row, "市净率")
    return {"pe": pe, "pb": pb, "pe_pct_3y": None, "pb_pct_3y": None, "peg": None}


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
    # 注入 holdings analyzer 季频缓存(rating/fund/cn_activity, TTL=7d)。
    # --only picks 单跑时 scheduler 没先跑 holdings, _fcache 默认 None → enrich 裸拉无缓存;
    # 显式 init 后这些维度走 holdings_cache.db 跨日缓存。用独立 db(见 _HOLDINGS_CACHE_PATH 红线)。
    from investbrief.holdings.analyzer import init_cache as _holdings_init_cache
    _holdings_init_cache(_HOLDINGS_CACHE_PATH)

    config = load_config()
    recipients = [r for r in config.get("recipients", []) if r.get("active", True)]
    if not recipients:
        logger.info("No active recipients, skipping picks.")
        return

    # 日级缓存：命中（非 --force）→ 直接发缓存 HTML，跳过整个 build（省 30min 深拉）
    from investbrief.core.mail_cache import make_key, get_cache, set_cache
    now = now_cn()
    today = now.strftime("%Y-%m-%d")
    cache_key = make_key("picks", today)
    if not getattr(args, "force", False) and not getattr(args, "dry_run", False):
        cached = get_cache(cache_key)
        if cached:
            logger.info(f"Picks cache hit ({cache_key}), sending cached HTML")
            subject = f"【股票推荐】{now.strftime('%Y年%m月%d日')}"
            sender = EmailSender(str(CONFIG_FILE))
            messages = [{"to": r["email"], "subject": subject, "html": cached} for r in recipients]
            sent, failed = sender.send_bulk(messages)
            if failed:
                logger.warning(f"{len(failed)}/{len(recipients)} picks recipients failed (cached): "
                               f"{[f[0] for f in failed]}")
            logger.info("Picks pipeline complete (cached)")
            return

    all_picks: list[dict] = []
    sections_html = ""
    skip_summary = getattr(args, "skip_summary", False)

    # 三阶段编排(对齐 pipelines/holdings.py:52-64 的批量预取模式):
    # ① 先 build 全部 profile 拿 Top1 —— Top1 选定后才知机构调研 batch 的 symbol 集合
    # ② run 级批量预取机构调研:N 只 Top1 共享一次 90 天遍历(1×90 次 eastmoney),
    #    替代旧的"边 build 边 enrich"里每只 Top1 走 90 次/股单股 fallback(3×90 次)
    # ③ 用注入了 batch 的单个 analyzer enrich + render(run 级单例,省 N×new)
    built: list[tuple[str, dict | None]] = [(_p, _safe_build(_p, "cn")) for _p in _PROFILES]

    from investbrief.holdings.analyzer import HoldingsAnalyzer
    analyzer = HoldingsAnalyzer()
    cn_symbols = [cn["symbol"] for _, cn in built if cn]
    if cn_symbols:
        try:
            from investbrief.datasources.akshare import AKShareClient
            batch = AKShareClient().get_institutional_research_batch(cn_symbols, days=90)
            if batch:
                analyzer.set_research_batch(batch)
        except Exception as e:
            logger.warning(f"research batch prefetch failed, falling back to per-stock: {e}")

    for prof_name, cn in built:
        if cn:
            _enrich_with_holdings(cn, analyzer, with_ai=not skip_summary)
            all_picks.append(cn)
        sections_html += _renderer.render_pick_section(prof_name, cn)

    picks_brief = "" if skip_summary else _brief.generate_picks_brief(all_picks)

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

    set_cache(cache_key, html)  # 写日级缓存（仅真实 send 路径；dry_run/preview 在此之前 return）

    subject = f"【股票推荐】{now.strftime('%Y年%m月%d日')}"
    sender = EmailSender(str(CONFIG_FILE))
    messages = [{"to": r["email"], "subject": subject, "html": html} for r in recipients]
    sent, failed = sender.send_bulk(messages)
    if failed:
        logger.warning(f"{len(failed)}/{len(recipients)} picks recipients failed: "
                       f"{[f[0] for f in failed]}")
    logger.info("Picks pipeline complete")
