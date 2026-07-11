# tests/test_picks_cap_shrink.py
"""picks build_picks_for_profile: 连续限流时空返回信号链 → futures 早停。

信号源: 数据层 fetch_history 限流时吞异常返回空 df,_process_candidate 在 hist
       空返回时累加 limit_hits(不嗅探 except 异常文案,因为限流根本到不了 except)。
早停: limit_hits 累加 ≥ _RATE_LIMIT_EARLY_STOP_HITS(25)→ futures 循环
       cancel 未启动 future + break。

注:原 _candidate_cap_for_run 多档降级 ladder 是死代码(唯一调用点恒传 0,
中间档永不触发),已删除;动态收缩实际由 futures 循环早停实现,本测试锁住该链路。
"""
import logging

import pandas as pd

from investbrief.pipelines import picks as picks_mod


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
        result = picks_mod.build_picks_for_profile("medium", "cn")

    # 候选全空 → rank_picks([]) 返回 [] → build 返回 None
    assert result is None
    # 早停 warning 必须出现(信号链:fetch_history 空 → _bump_limit → ≥25 → 早停 log)
    early_stop_msgs = [r.getMessage() for r in caplog.records
                       if "early-stop" in r.getMessage()]
    assert early_stop_msgs, (
        f"expected heavy rate-limit early-stop warning, got: "
        f"{[r.getMessage() for r in caplog.records]}"
    )
    # 早停 message 含当前空返回计数(应 ≥ _RATE_LIMIT_EARLY_STOP_HITS)
    import re
    m = re.search(r"hits=(\d+)", early_stop_msgs[0])
    assert m and int(m.group(1)) >= picks_mod._RATE_LIMIT_EARLY_STOP_HITS, (
        f"hits should be >= {picks_mod._RATE_LIMIT_EARLY_STOP_HITS}, msg: {early_stop_msgs[0]}"
    )


def test_empty_returns_do_not_trigger_early_stop_below_threshold(caplog, monkeypatch):
    """少量空返回(<25)→ 不触发早停 warning(边界正确性,防误触发)。"""
    # 候选数 < 阈值 → 即便全空返回,limit_hits 也达不到 25,不早停
    n_candidates = picks_mod._RATE_LIMIT_EARLY_STOP_HITS - 5
    fake_candidates = pd.DataFrame([
        {"代码": f"{i:06d}", "名称": f"S{i}", "成交额": 1.0e9 - i}
        for i in range(n_candidates)
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
        result = picks_mod.build_picks_for_profile("medium", "cn")

    # 候选全空 → 返回 None(没候选可 rank)
    assert result is None
    # 不应出现早停 warning(limit_hits 最高 n_candidates < 25)
    early_stop_msgs = [r.getMessage() for r in caplog.records
                       if "early-stop" in r.getMessage()]
    assert not early_stop_msgs, (
        f"unexpected early-stop at <{picks_mod._RATE_LIMIT_EARLY_STOP_HITS} hits: {early_stop_msgs}"
    )
