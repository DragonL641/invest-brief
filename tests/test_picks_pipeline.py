# tests/test_picks_pipeline.py
"""picks pipeline: 编排韧性(各环节失败不阻塞,产出占位)。"""
import pandas as pd

from investbrief.pipelines import picks


def test_run_picks_report_dry_run_no_recipients(monkeypatch):
    """无 active 收件人 → 跳过,不抛。"""
    monkeypatch.setattr(picks, "load_config", lambda: {"recipients": []})
    args = type("A", (), {"dry_run": True, "skip_summary": False, "preview": False})()
    picks.run_picks_report(args)


def test_build_picks_for_profile_returns_none_on_empty_universe(monkeypatch):
    """universe 空 → 该 profile×市场 返回 None(占位)。"""
    monkeypatch.setattr(picks, "_spot_df", lambda market: None)
    monkeypatch.setattr(picks, "load_profiles",
                        lambda: {"swing": {"universe": {}, "factors": {}, "top_n": 1,
                                           "standardize": "rank_percentile",
                                           "industry_neutralize": False}})
    assert picks.build_picks_for_profile("swing", "cn") is None


def _swing_profile():
    return {"swing": {
        "universe": {"exclude_st": False},
        "factors": {"trend_strength": {"weight": 1.0}},
        "standardize": "rank_percentile",
        "industry_neutralize": False,
        "top_n": 1,
    }}


def _medium_profile_with_roe_gate(min_roe):
    return {"medium": {
        "universe": {"exclude_st": False, "fundamental_gates": {"min_roe_4q": min_roe}},
        "factors": {"quality": {"weight": 1.0}},
        "standardize": "rank_percentile",
        "industry_neutralize": False,
        "top_n": 1,
    }}


def _one_row_spot_df():
    return pd.DataFrame([{"代码": "000001", "名称": "X", "成交额": 1.0e9}])


def _two_row_spot_df():
    return pd.DataFrame([
        {"代码": "000001", "名称": "A", "成交额": 2.0e9},
        {"代码": "000002", "名称": "B", "成交额": 1.0e9},
    ])


def _valid_history(n=130):
    import numpy as np
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    close = pd.Series(10 + 0.1 * np.arange(n), index=idx)
    vol = pd.Series(1e6 + 0 * np.arange(n), index=idx, dtype=float)
    return pd.DataFrame({"close": close, "volume": vol})


def test_build_picks_for_profile_survives_malformed_hist(monkeypatch):
    """C1: 历史帧缺 close 列 → 该候选被跳过,profile 返回 None(无候选),不抛。"""
    monkeypatch.setattr(picks, "_spot_df", lambda market: _one_row_spot_df())
    # 非空历史但缺 close 列(模拟 akshare column drift);长度足够让 swing 因子进入
    # hist["close"] 访问路径(trend_strength 要求 len ≥ 60),从而触发 KeyError
    import numpy as np
    idx = pd.date_range("2024-01-01", periods=130, freq="B")
    malformed = pd.DataFrame({"open": np.arange(130, dtype=float),
                              "volume": np.ones(130) * 1e6}, index=idx)
    monkeypatch.setattr(picks._data, "fetch_history",
                        lambda symbol, market, days: malformed)
    monkeypatch.setattr(picks, "load_profiles", lambda: _swing_profile())
    # 不抛 + 无候选存活 → None
    assert picks.build_picks_for_profile("swing", "cn") is None


def test_fundamental_gate_skips_low_roe(monkeypatch):
    """I1: medium profile + roe 0.05 < gate 0.08 → 候选被剔除,返回 None。"""
    monkeypatch.setattr(picks, "_spot_df", lambda market: _one_row_spot_df())
    monkeypatch.setattr(picks._data, "fetch_history", lambda symbol, market, days: _valid_history())
    monkeypatch.setattr(picks._data, "fetch_fundamentals",
                        lambda symbol, market: {"roe": 0.05, "fcf_positive": True})
    monkeypatch.setattr(picks, "load_profiles", lambda: _medium_profile_with_roe_gate(0.08))
    assert picks.build_picks_for_profile("medium", "cn") is None


def test_fundamental_gate_passes_high_roe(monkeypatch):
    """I1: medium profile + roe 0.20 ≥ gate 0.08 → 候选通过,返回 pick(非 None)。"""
    monkeypatch.setattr(picks, "_spot_df", lambda market: _one_row_spot_df())
    monkeypatch.setattr(picks._data, "fetch_history", lambda symbol, market, days: _valid_history())
    monkeypatch.setattr(picks._data, "fetch_fundamentals",
                        lambda symbol, market: {"roe": 0.20, "gross_margin": 0.40,
                                                "fcf_positive": True})
    monkeypatch.setattr(picks, "load_profiles", lambda: _medium_profile_with_roe_gate(0.08))
    res = picks.build_picks_for_profile("medium", "cn")
    assert res is not None
    assert res["symbol"] == "000001"


def test_safe_build_swallows_exception(monkeypatch):
    """C1b: build_picks_for_profile 抛异常 → _safe_build 返回 None,不向上传播。"""
    def _boom(*_, **__):
        raise RuntimeError("boom")
    monkeypatch.setattr(picks, "build_picks_for_profile", _boom)
    assert picks._safe_build("swing", "cn") is None


# ---- swing 两阶段 + 并发 ----

def _swing_technical_profile():
    """swing 纯技术面 profile(无 gate + 无 fundamental 因子)→ needs_fund=False。"""
    return {"swing": {
        "universe": {"exclude_st": False},
        "factors": {"trend_strength": {"weight": 1.0}},
        "standardize": "rank_percentile",
        "industry_neutralize": False,
        "top_n": 1,
    }}


def test_swing_skips_fundamentals_during_scoring(monkeypatch):
    """swing 两阶段:打分阶段不拉 fund(限流放大器),Top1 选定后只拉 1 次。"""
    monkeypatch.setattr(picks, "_spot_df", lambda market: _two_row_spot_df())
    monkeypatch.setattr(picks._data, "fetch_history", lambda s, m, days: _valid_history())
    fund_calls: list[str] = []

    def _track(symbol, market):
        fund_calls.append(symbol)
        return {"roe": 0.20, "gross_margin": 0.40, "fcf_positive": True}

    monkeypatch.setattr(picks._data, "fetch_fundamentals", _track)
    monkeypatch.setattr(picks, "load_profiles", lambda: _swing_technical_profile())
    res = picks.build_picks_for_profile("swing", "cn")
    assert res is not None
    # swing: 只对 Top1 拉 fund(不全拉)→ 恰好 1 次,不是 2 次
    assert len(fund_calls) == 1
    assert fund_calls[0] == res["symbol"]


def test_medium_fetches_fundamentals_for_all_candidates(monkeypatch):
    """medium(有 fundamental 因子)打分阶段对每个候选拉 fund(needs_fund=True)。"""
    monkeypatch.setattr(picks, "_spot_df", lambda market: _two_row_spot_df())
    monkeypatch.setattr(picks._data, "fetch_history", lambda s, m, days: _valid_history())
    fund_calls: list[str] = []

    def _track(symbol, market):
        fund_calls.append(symbol)
        return {"roe": 0.20, "gross_margin": 0.40, "fcf_positive": True}

    monkeypatch.setattr(picks._data, "fetch_fundamentals", _track)
    monkeypatch.setattr(picks, "load_profiles", lambda: _medium_profile_with_roe_gate(0.0))
    res = picks.build_picks_for_profile("medium", "cn")
    assert res is not None
    # medium(needs_fund=True)对每个候选拉 fund → 2 次(全量,因 gate + fundamental 因子)
    assert len(fund_calls) == 2


def test_deep_pull_uses_threadpool_max_workers_2(monkeypatch):
    """候选深拉用 ThreadPoolExecutor(max_workers=2),对齐 holdings 限流策略。"""
    assert picks._DEEP_PULL_WORKERS == 2
    captured: dict = {}
    real_ex = picks.ThreadPoolExecutor

    class _Spy(real_ex):
        def __init__(self, max_workers=None, **kw):
            captured["max_workers"] = max_workers
            super().__init__(max_workers=max_workers, **kw)

    monkeypatch.setattr(picks, "ThreadPoolExecutor", _Spy)
    monkeypatch.setattr(picks, "_spot_df", lambda market: _one_row_spot_df())
    monkeypatch.setattr(picks._data, "fetch_history", lambda s, m, days: _valid_history())
    monkeypatch.setattr(picks._data, "fetch_fundamentals", lambda s, m: {})
    monkeypatch.setattr(picks, "load_profiles", lambda: _swing_technical_profile())
    picks.build_picks_for_profile("swing", "cn")
    assert captured.get("max_workers") == 2



def _long_profile_with_profitable_years_gate(min_years):
    return {"long": {
        "universe": {"exclude_st": False,
                     "fundamental_gates": {"min_profitable_years": min_years}},
        "factors": {"quality": {"weight": 1.0}},
        "standardize": "rank_percentile",
        "industry_neutralize": False,
        "top_n": 1,
    }}


def test_profitable_years_gate_skips_below_threshold(monkeypatch):
    """TODO B: long profile + profitable_years=2 < gate 3 → 候选剔除,返回 None。"""
    monkeypatch.setattr(picks, "_spot_df", lambda market: _one_row_spot_df())
    monkeypatch.setattr(picks._data, "fetch_history", lambda symbol, market, days: _valid_history())
    monkeypatch.setattr(picks._data, "fetch_fundamentals",
                        lambda symbol, market: {"roe": 0.20, "fcf_positive": True})
    monkeypatch.setattr(picks._data, "fetch_profitable_years",
                        lambda symbol, market: 2)
    monkeypatch.setattr(picks, "load_profiles",
                        lambda: _long_profile_with_profitable_years_gate(3))
    assert picks.build_picks_for_profile("long", "cn") is None


def test_profitable_years_gate_passes_at_or_above(monkeypatch):
    """TODO B: long profile + profitable_years=3 ≥ gate 3 → 候选通过。"""
    monkeypatch.setattr(picks, "_spot_df", lambda market: _one_row_spot_df())
    monkeypatch.setattr(picks._data, "fetch_history", lambda symbol, market, days: _valid_history())
    monkeypatch.setattr(picks._data, "fetch_fundamentals",
                        lambda symbol, market: {"roe": 0.20, "fcf_positive": True})
    monkeypatch.setattr(picks._data, "fetch_profitable_years",
                        lambda symbol, market: 5)
    monkeypatch.setattr(picks, "load_profiles",
                        lambda: _long_profile_with_profitable_years_gate(3))
    res = picks.build_picks_for_profile("long", "cn")
    assert res is not None
    assert res["symbol"] == "000001"


def test_profitable_years_gate_degrades_when_data_missing(monkeypatch):
    """TODO B 韧性: fetch_profitable_years 返回 None(数据缺失) → gate 跳过,候选通过。"""
    monkeypatch.setattr(picks, "_spot_df", lambda market: _one_row_spot_df())
    monkeypatch.setattr(picks._data, "fetch_history", lambda symbol, market, days: _valid_history())
    monkeypatch.setattr(picks._data, "fetch_fundamentals",
                        lambda symbol, market: {"roe": 0.20, "fcf_positive": True})
    monkeypatch.setattr(picks._data, "fetch_profitable_years",
                        lambda symbol, market: None)
    monkeypatch.setattr(picks, "load_profiles",
                        lambda: _long_profile_with_profitable_years_gate(3))
    res = picks.build_picks_for_profile("long", "cn")
    # 数据缺失 → gate 不强制 → 候选存活 → 返回 pick(不是 None)
    assert res is not None


# ---- TODO A 上市时长代理 gate ----

def test_listing_gate_rejects_recent_proxy(monkeypatch):
    """TODO A: earliest_period 不到 3 年(min_listed_years=3)→ 拒。"""
    # 当前日期 2026-07-06;2024-12-31 ≈ 1.55 年 < 3
    monkeypatch.setattr(picks._data, "fetch_earliest_report_period",
                        lambda symbol, market: "2024-12-31")
    assert picks._passes_listing_gates("000001", "cn", min_days=None, min_years=3) is False


def test_listing_gate_passes_old_proxy(monkeypatch):
    """TODO A: earliest_period='1998-12-31' → 满足 min_listed_years=3。"""
    monkeypatch.setattr(picks._data, "fetch_earliest_report_period",
                        lambda symbol, market: "1998-12-31")
    assert picks._passes_listing_gates("600519", "cn", min_days=None, min_years=3) is True


def test_listing_gate_min_days(monkeypatch):
    """TODO A: min_listed_days 用 0.69 交易日系数。"""
    # 100 自然日前 ≈ 69 交易日 < 250 → 拒
    from datetime import datetime, timedelta
    recent = (datetime.now() - timedelta(days=100)).strftime("%Y-%m-%d")
    monkeypatch.setattr(picks._data, "fetch_earliest_report_period",
                        lambda symbol, market: recent)
    assert picks._passes_listing_gates("X", "cn", min_days=250, min_years=None) is False

    # 10 年前 ≫ 250 交易日 → 通过
    old = (datetime.now() - timedelta(days=3650)).strftime("%Y-%m-%d")
    monkeypatch.setattr(picks._data, "fetch_earliest_report_period",
                        lambda symbol, market: old)
    assert picks._passes_listing_gates("X", "cn", min_days=250, min_years=None) is True


def test_listing_gate_degrades_when_fetch_fails(monkeypatch):
    """TODO A 韧性: earliest fetch 返回 None → gate 跳过,通过。"""
    monkeypatch.setattr(picks._data, "fetch_earliest_report_period",
                        lambda symbol, market: None)
    assert picks._passes_listing_gates("X", "cn", min_days=250, min_years=3) is True


def test_listing_gate_skipped_when_no_thresholds():
    """无任何上市时长阈值 → 直接通过。"""
    assert picks._passes_listing_gates("X", "cn", None, None) is True


def test_swing_pick_pe_pb_even_without_valuation_factor(monkeypatch):
    """bug: swing 无 valuation 因子,但卡片 pe/pb 应从 spot 取(之前因 val 条件卡死为空)。"""
    spot = pd.DataFrame([{"代码": "000001", "名称": "X", "成交额": 1.0e9,
                          "市盈率-动态": 15.5, "市净率": 2.3}])
    monkeypatch.setattr(picks, "_spot_df", lambda market: spot)
    monkeypatch.setattr(picks._data, "fetch_history",
                        lambda symbol, market, days: _valid_history())
    monkeypatch.setattr(picks._data, "fetch_fundamentals",
                        lambda symbol, market: {})
    monkeypatch.setattr(picks, "load_profiles", lambda: _swing_profile())
    top = picks.build_picks_for_profile("swing", "cn")
    assert top is not None
    assert top["fundamentals"]["pe"] == 15.5  # 修复前 None,修复后 spot pe
    assert top["fundamentals"]["pb"] == 2.3
