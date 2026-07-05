# tests/test_picks_pipeline.py
"""picks pipeline: 编排韧性(各环节失败不阻塞,产出占位)。"""
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
