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
