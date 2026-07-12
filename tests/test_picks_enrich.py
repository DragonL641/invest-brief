# tests/test_picks_enrich.py
"""run_picks_report 三阶段 enrich 集成测试(A2/A3 重构回归网)。

填补 _enrich_with_holdings 零覆盖缺口(Explore 确认 test_pipeline_cache 把 _safe_build
mock 成 None、test_picks_pipeline 直接测 build_picks_for_profile, 都到不了 enrich 循环)。

验证三阶段编排(对齐 holdings.py:52-64):
① 机构调研 batch 用 Top1 symbol 集合一次预取(1×90 次/run, 替代每只 90 次单股 fallback)
② set_research_batch 把 batch 注入 analyzer
③ analyze_one 对每只非 None Top1 调一次
④ 全部 Top1=None(限流早停场景)时不预取 batch 也不 enrich
"""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock


def _frozen_now():
    return datetime(2026, 7, 10, 9, 0)


def _fake_top1(symbol, profile):
    return {"symbol": symbol, "market": "cn", "name": f"T-{symbol}",
            "profile": profile, "composite": 80.0,
            "factor_scores": {}, "triggers": [], "industry": None,
            "data_time": "2026-07-10 09:00"}


def _base_mocks(monkeypatch, picks_mod, picks_map):
    """公共 mock:dry-run 路径所需依赖。picks_map: {profile: Top1 dict | None}。"""
    monkeypatch.setattr(picks_mod, "now_cn", _frozen_now)
    monkeypatch.setattr(picks_mod, "load_config",
                        lambda: {"recipients": [{"email": "a@b.com", "name": "A",
                                                  "active": True, "language": "zh-CN"}]})
    monkeypatch.setattr(picks_mod, "_data", MagicMock())  # init_cache no-op
    monkeypatch.setattr(picks_mod, "_renderer",
                        MagicMock(render_pick_section=lambda *a, **k: ""))
    monkeypatch.setattr(picks_mod, "_brief", MagicMock())  # skip_summary=True 不调, mock 兜底
    monkeypatch.setattr(picks_mod, "_safe_build", lambda prof, mkt: picks_map[prof])
    # run_picks_report 内函数级 import → patch 源模块而非 picks_mod
    monkeypatch.setattr("investbrief.holdings.analyzer.init_cache", lambda *a, **k: None)


def test_run_picks_report_batch_prefetch_and_enrich(monkeypatch, capsys):
    """swing/medium 返 Top1 + long 返 None → batch 用 2 symbols 预取, enrich 调 2 次。"""
    from investbrief.pipelines import picks as picks_mod

    picks_map = {"swing": _fake_top1("000001", "swing"),
                 "medium": _fake_top1("600000", "medium"),
                 "long": None}
    _base_mocks(monkeypatch, picks_mod, picks_map)

    # analyzer: 记录 set_research_batch + analyze_one 调用
    fake_analyzer = MagicMock()
    analyze_calls = []

    def fake_analyze_one(symbol, market, type_, *, with_ai=True):
        analyze_calls.append(symbol)
        return SimpleNamespace(rating={"buy": 5}, forecast={"target": 10.0},
                               ai_conclusion="ok")
    fake_analyzer.analyze_one = fake_analyze_one
    monkeypatch.setattr("investbrief.holdings.analyzer.HoldingsAnalyzer",
                        lambda: fake_analyzer)

    # AKShareClient.get_institutional_research_batch: 记录 symbols/days
    batch_calls = {}

    def fake_batch(symbols, days=90):
        batch_calls["symbols"] = list(symbols)
        batch_calls["days"] = days
        return {s: [{"date": "2026-07-01"}] for s in symbols}
    fake_ak = MagicMock()
    fake_ak.get_institutional_research_batch = fake_batch
    monkeypatch.setattr("investbrief.datasources.akshare.AKShareClient",
                        lambda: fake_ak)

    args = MagicMock(force=False, skip_summary=True, dry_run=True, preview=False)
    picks_mod.run_picks_report(args)

    # ① batch 用 2 只 Top1 symbol(按 _PROFILES 出现顺序 swing→medium, long=None 剔除)+ days=90
    assert batch_calls.get("symbols") == ["000001", "600000"], \
        f"batch 应接收 2 只 Top1 symbol, 实际 {batch_calls.get('symbols')}"
    assert batch_calls.get("days") == 90
    # ② set_research_batch 注入(batch 非空)
    fake_analyzer.set_research_batch.assert_called_once()
    injected = fake_analyzer.set_research_batch.call_args[0][0]
    assert set(injected.keys()) == {"000001", "600000"}
    # ③ analyze_one 对每只非 None Top1 调一次(long=None 不调)
    assert sorted(analyze_calls) == ["000001", "600000"], \
        f"analyze_one 应调 2 次, 实际 {analyze_calls}"
    # ④ dry-run JSON 含 enrich 后的 Top1
    out = capsys.readouterr().out
    assert "000001" in out and "600000" in out


def test_run_picks_report_no_top1_skips_batch_and_enrich(monkeypatch):
    """全部 profile Top1=None(限流早停)→ 不预取 batch, 不 enrich。"""
    from investbrief.pipelines import picks as picks_mod

    picks_map = {"swing": None, "medium": None, "long": None}
    _base_mocks(monkeypatch, picks_mod, picks_map)

    fake_analyzer = MagicMock()
    monkeypatch.setattr("investbrief.holdings.analyzer.HoldingsAnalyzer",
                        lambda: fake_analyzer)

    batch_calls = {"n": 0}

    def fake_batch(symbols, days=90):
        batch_calls["n"] += 1
        return {}
    fake_ak = MagicMock()
    fake_ak.get_institutional_research_batch = fake_batch
    monkeypatch.setattr("investbrief.datasources.akshare.AKShareClient",
                        lambda: fake_ak)

    args = MagicMock(force=False, skip_summary=True, dry_run=True, preview=False)
    picks_mod.run_picks_report(args)

    assert batch_calls["n"] == 0, "无 Top1 不应预取 batch"
    fake_analyzer.analyze_one.assert_not_called()
    fake_analyzer.set_research_batch.assert_not_called()
