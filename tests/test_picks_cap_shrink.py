# tests/test_picks_cap_shrink.py
"""picks build_picks_for_profile: 连续限流时 _candidate_cap 渐进收缩 + 早停。

参数语义: limit_hits = 原始"空返回"计数(限流代理信号,非档位索引)。
阈值 (10, 25): [0,10) 保持基线; [10,25) → 中档; ≥25 → 底档。
信号源: 数据层 fetch_history 限流时吞异常返回空 df,_process_candidate 在 hist
       空返回时累加 limit_hits(不嗅探 except 异常文案,因为限流根本到不了 except)。
"""
import logging

import pandas as pd

from investbrief.pipelines import picks as picks_mod


# ---------- 纯函数测试 ----------

def test_candidate_cap_shrinks_on_rate_limit():
    """_candidate_cap_for_run(profile, limit_hits) 随原始"空返回"命中数收缩。"""
    # 基线 (limit_hits < 10)
    assert picks_mod._candidate_cap_for_run("medium", 0) == 80
    assert picks_mod._candidate_cap_for_run("swing", 0) == 60
    assert picks_mod._candidate_cap_for_run("long", 0) == 60
    # 中档 (10 ≤ limit_hits < 25)
    assert picks_mod._candidate_cap_for_run("medium", 10) == 30
    assert picks_mod._candidate_cap_for_run("medium", 15) == 30
    # 底档 (limit_hits ≥ 25)
    assert picks_mod._candidate_cap_for_run("medium", 25) == 15
    assert picks_mod._candidate_cap_for_run("medium", 30) == 15
    assert picks_mod._candidate_cap_for_run("swing", 30) == 15


def test_rate_limit_thresholds():
    """两档降级阈值固定 (10, 25)。"""
    assert picks_mod._RATE_LIMIT_DOWNGRADE_THRESHOLDS == (10, 25)


def test_cap_ladder_values():
    """cap 收缩档位: 30 (中档) / 15 (底档)。"""
    assert picks_mod._CAP_LADDER == (30, 15)


def test_candidate_cap_for_run_reuses_candidate_cap():
    """_candidate_cap_for_run 基线复用 _candidate_cap(唯一真相源,无 _CAP_BASE 重复)。"""
    # _CAP_BASE 常量已删除(DRY),基线由 _candidate_cap 提供
    assert not hasattr(picks_mod, "_CAP_BASE")
    for prof in ("swing", "medium", "long"):
        assert picks_mod._candidate_cap_for_run(prof, 0) == picks_mod._candidate_cap(prof)


def test_candidate_cap_for_run_boundary_at_thresholds():
    """边界值: 9→基线 / 10→中档 / 24→中档 / 25→底档。"""
    assert picks_mod._candidate_cap_for_run("medium", 9) == 80
    assert picks_mod._candidate_cap_for_run("medium", 10) == 30
    assert picks_mod._candidate_cap_for_run("medium", 24) == 30
    assert picks_mod._candidate_cap_for_run("medium", 25) == 15


def test_candidate_cap_for_run_unknown_profile_falls_back():
    """未知 profile → _candidate_cap fallback 60,同样参与收缩。"""
    assert picks_mod._candidate_cap_for_run("unknown", 0) == 60
    assert picks_mod._candidate_cap_for_run("unknown", 15) == 30
    assert picks_mod._candidate_cap_for_run("unknown", 30) == 15


# ---------- 集成测试:空返回信号链 → 早停(锁住 C1 修法,防回归) ----------

def _empty_history_stub(*args, **kwargs):
    """模拟限流:数据层吞异常后返回空 df(代理信号源)。"""
    return pd.DataFrame()


def test_empty_returns_trigger_early_stop(caplog, monkeypatch):
    """fetch_history 全空(限流代理)→ limit_hits 累加 ≥25 → futures 早停 warning。

    防回归:C1 的根因是空返回路径未被计数。本测试锁住"空返回 → _bump_limit → 早停"信号链。
    """
    # 30 个假候选(>25 阈值,确保早停触发);列含 coarse_filter 下游所需的 代码/名称/成交额
    fake_candidates = pd.DataFrame([
        {"代码": f"{i:06d}", "名称": f"S{i}", "成交额": 1.0e9 - i}
        for i in range(30)
    ])
    # 喂给 _process_candidate 的 row 还会读 代码/名称;_valuation_for/_industry_for 都被
    # factors=[] + universe={} 跳过,无需额外 mock。
    monkeypatch.setattr(picks_mod, "_spot_df", lambda market: pd.DataFrame())
    monkeypatch.setattr(picks_mod._universe, "coarse_filter",
                        lambda spot, prof, market: fake_candidates)
    monkeypatch.setattr(picks_mod, "load_profiles",
                        lambda: {"medium": {"universe": {}, "factors": [],
                                            "top_n": 1,
                                            "standardize": "rank_percentile",
                                            "industry_neutralize": False}})
    monkeypatch.setattr(picks_mod._data, "fetch_history", _empty_history_stub)

    with caplog.at_level(logging.WARNING, logger="investbrief.pipelines.picks"):
        result = picks_mod.build_picks_for_profile("medium", "us")

    # 候选全空 → rank_picks([]) 返回 [] → build 返回 None
    assert result is None
    # 早停 warning 必须出现(信号链:fetch_history 空 → _bump_limit → ≥25 → 早停 log)
    early_stop_msgs = [r.getMessage() for r in caplog.records
                       if "early-stop" in r.getMessage()]
    assert early_stop_msgs, (
        f"expected heavy rate-limit early-stop warning, got: "
        f"{[r.getMessage() for r in caplog.records]}"
    )
    # 早停 message 含当前空返回计数(应 ≥25)
    import re
    m = re.search(r"hits=(\d+)", early_stop_msgs[0])
    assert m and int(m.group(1)) >= 25, f"hits should be >=25, msg: {early_stop_msgs[0]}"


def test_empty_returns_do_not_trigger_early_stop_below_threshold(caplog, monkeypatch):
    """少量空返回(<25)→ 不触发早停 warning(边界正确性,防误触发)。"""
    # 20 个假候选(<25 阈值)→ 即便全空返回,limit_hits 只到 20,不早停
    fake_candidates = pd.DataFrame([
        {"代码": f"{i:06d}", "名称": f"S{i}", "成交额": 1.0e9 - i}
        for i in range(20)
    ])
    monkeypatch.setattr(picks_mod, "_spot_df", lambda market: pd.DataFrame())
    monkeypatch.setattr(picks_mod._universe, "coarse_filter",
                        lambda spot, prof, market: fake_candidates)
    monkeypatch.setattr(picks_mod, "load_profiles",
                        lambda: {"medium": {"universe": {}, "factors": [],
                                            "top_n": 1,
                                            "standardize": "rank_percentile",
                                            "industry_neutralize": False}})
    monkeypatch.setattr(picks_mod._data, "fetch_history", _empty_history_stub)

    with caplog.at_level(logging.WARNING, logger="investbrief.pipelines.picks"):
        result = picks_mod.build_picks_for_profile("medium", "us")

    # 候选全空 → 返回 None(没候选可 rank)
    assert result is None
    # 不应出现早停 warning(limit_hits 最高 20 < 25)
    early_stop_msgs = [r.getMessage() for r in caplog.records
                       if "early-stop" in r.getMessage()]
    assert not early_stop_msgs, f"unexpected early-stop at <25 hits: {early_stop_msgs}"
