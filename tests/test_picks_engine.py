# tests/test_picks_engine.py
"""picks.engine: rank percentile 标准化 + 加权 + Top N。"""
from investbrief.picks import engine


def _candidate(symbol, raw_factors: dict):
    return {"symbol": symbol, "name": symbol, "market": "cn",
            "raw_factors": raw_factors, "industry": "银行"}


def test_top1_picks_highest_composite():
    profile = {
        "factors": {"f1": {"weight": 1.0}},
        "standardize": "rank_percentile",
        "industry_neutralize": False,
        "top_n": 1,
    }
    cands = [
        _candidate("A", {"f1": 0.9}),
        _candidate("B", {"f1": 0.1}),
        _candidate("C", {"f1": 0.5}),
    ]
    res = engine.rank_picks(cands, profile, market="cn")
    assert res[0]["symbol"] == "A"
    assert res[0]["rank"] == 1
    assert res[0]["composite"] == 100.0   # 最高分对应 100 百分位


def test_invert_factor_lower_better():
    profile = {
        "factors": {"f1": {"weight": 1.0, "invert": True}},
        "standardize": "rank_percentile", "industry_neutralize": False, "top_n": 1,
    }
    cands = [_candidate("A", {"f1": 0.9}), _candidate("B", {"f1": 0.1}), _candidate("C", {"f1": 0.5})]
    res = engine.rank_picks(cands, profile, market="cn")
    assert res[0]["symbol"] == "B"   # invert: 最小的 0.1 排前(I4 阈值要求 ≥3 有效值)


def test_empty_candidates_returns_empty():
    profile = {"factors": {"f1": {"weight": 1.0}}, "standardize": "rank_percentile",
               "industry_neutralize": False, "top_n": 1}
    assert engine.rank_picks([], profile, market="cn") == []


def test_missing_factor_values_degrade():
    """某因子全 None → 该因子贡献 0,不阻塞。"""
    profile = {"factors": {"f1": {"weight": 0.5}, "f2": {"weight": 0.5}},
               "standardize": "rank_percentile", "industry_neutralize": False, "top_n": 1}
    cands = [_candidate("A", {"f1": 0.9, "f2": None}), _candidate("B", {"f1": 0.1, "f2": None})]
    res = engine.rank_picks(cands, profile, market="cn")
    assert res[0]["symbol"] == "A"


def test_sparse_factor_degrades():
    """I4: 因子仅 1/3 候选有值 → 太稀疏,该因子全员 pct=None,无效满权重加成。"""
    profile = {"factors": {"f1": {"weight": 1.0}},
               "standardize": "rank_percentile", "industry_neutralize": False, "top_n": 3}
    cands = [
        _candidate("A", {"f1": 0.9}),       # 唯一有值
        _candidate("B", {"f1": None}),
        _candidate("C", {"f1": None}),
    ]
    res = engine.rank_picks(cands, profile, market="cn")
    by_sym = {r["symbol"]: r for r in res}
    # A 不应获得 100th percentile 满权重加成
    assert by_sym["A"]["factor_scores"]["f1"]["pct"] is None
    assert by_sym["B"]["factor_scores"]["f1"]["pct"] is None
    assert by_sym["C"]["factor_scores"]["f1"]["pct"] is None
    # 全员该因子贡献 0 → composite 同为 0.0(不再偏向 A)
    assert by_sym["A"]["composite"] == by_sym["B"]["composite"] == by_sym["C"]["composite"] == 0.0
