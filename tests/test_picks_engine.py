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


# ---- TODO D 行业中性化 ----

def _cand(symbol, raw_factors, industry):
    return {"symbol": symbol, "name": symbol, "market": "cn",
            "raw_factors": raw_factors, "industry": industry}


def test_industry_neutralization_changes_ordering():
    """TODO D: 4 候选 × 2 行业,基本面因子行业内 clustered。
    Industry X 整体高 quality(median=80),Industry Y 整体低(median=40)。
    不做中性化:X 组全员碾压;中性化后:X 内部 leader 仍领先,但 Y 内的相对
    leader 应当被提升到接近 X leader 的水平(因为减去各组中位数后两边
    leader 的"超出中位数"幅度直接可比)。
    """
    profile = {"factors": {"quality": {"weight": 1.0}},
               "standardize": "rank_percentile", "industry_neutralize": True, "top_n": 4}
    cands = [
        _cand("X1", {"quality": 90.0}, "X"),   # X 内 leader
        _cand("X2", {"quality": 80.0}, "X"),   # X 内 median
        _cand("Y1", {"quality": 50.0}, "Y"),   # Y 内 leader
        _cand("Y2", {"quality": 40.0}, "Y"),   # Y 内 median
    ]

    # 基线: 不中性化 → 排名 X1 > X2 > Y1 > Y2
    no_neut_profile = {**profile, "industry_neutralize": False}
    no_neut = engine.rank_picks(cands, no_neut_profile, market="cn")
    syms_no = [r["symbol"] for r in no_neut]
    assert syms_no == ["X1", "X2", "Y1", "Y2"]

    # 中性化: 减去组中位数 → X1=10, X2=0, Y1=10, Y2=0
    # → X1 与 Y1 并列(都"组内 +10");X2 与 Y2 并列(都"组内 +0")
    neut = engine.rank_picks(cands, profile, market="cn")
    by_sym = {r["symbol"]: r for r in neut}
    # X1 与 Y1 应当 composite 相同(并列)
    assert by_sym["X1"]["composite"] == by_sym["Y1"]["composite"]
    # X2 与 Y2 应当 composite 相同
    assert by_sym["X2"]["composite"] == by_sym["Y2"]["composite"]
    # leader 组(中位数超出值=10)应当严格优于 median 组(超出=0)
    assert by_sym["X1"]["composite"] > by_sym["X2"]["composite"]
    # 关键不变量: Y1(原 quality=50,行业低)不再是中性化前的第 3 名
    assert syms_no.index("Y1") == 2   # 不中性化时 Y1 第 3
    # 中性化后 Y1 进入前 2(与 X1 并列 leader)
    neut_syms = [r["symbol"] for r in neut]
    assert neut_syms.index("Y1") <= 1


def test_neutralization_noop_when_no_industry():
    """TODO D 韧性: 全部 industry=None → 中性化无害 no-op,排序与关闭中性化一致。"""
    profile_on = {"factors": {"quality": {"weight": 1.0}},
                  "standardize": "rank_percentile", "industry_neutralize": True, "top_n": 3}
    profile_off = {**profile_on, "industry_neutralize": False}
    cands = [
        _cand("A", {"quality": 0.9}, None),
        _cand("B", {"quality": 0.5}, None),
        _cand("C", {"quality": 0.1}, None),
    ]
    on = engine.rank_picks(cands, profile_on, market="cn")
    off = engine.rank_picks(cands, profile_off, market="cn")
    # 全 None → _has_industry_groups False → 直接跳过中性化路径,结果一致
    assert [r["symbol"] for r in on] == [r["symbol"] for r in off]
    assert [r["composite"] for r in on] == [r["composite"] for r in off]


def test_neutralization_only_fundamental_category():
    """TODO D: 中性化只作用于 FACTOR_CATEGORY='fundamental' 因子,
    technical 因子应保留 raw 值排序。"""
    # quality=fundamental, ma20_deviation=technical(此 test 用 f_tech 名占位也行,但
    # 直接用真实 key 可同时验证 FACTOR_CATEGORY 查表)
    profile = {
        "factors": {
            "quality": {"weight": 0.5},
            "momentum_60d_ex5": {"weight": 0.5},
        },
        "standardize": "rank_percentile",
        "industry_neutralize": True,
        "top_n": 4,
    }
    # 构造: 2 个行业,quality 行业聚集,momentum 反向聚集(确保 momentum 不被中性化)
    cands = [
        _cand("X1", {"quality": 100.0, "momentum_60d_ex5": 0.0}, "X"),
        _cand("X2", {"quality": 90.0, "momentum_60d_ex5": 0.0}, "X"),
        _cand("Y1", {"quality": 50.0, "momentum_60d_ex5": 100.0}, "Y"),
        _cand("Y2", {"quality": 40.0, "momentum_60d_ex5": 100.0}, "Y"),
    ]
    res = engine.rank_picks(cands, profile, market="cn")
    # momentum 不中性化: Y1=Y2=100 → 都拿 100th pct;X1=X2=0 → 都拿低 pct
    # quality 中性化: X1=10,X2=0,Y1=10,Y2=0 → X1=Y1 高 pct;X2=Y2 低 pct
    # 综合两因子的对称性: X1 和 Y1 都得到 (quality高 + momentum低) 或 (quality低 + momentum高)
    # 实际: X1=quality高 + momentum低;Y1=quality高(中性化后)+ momentum高
    # → Y1 应当胜出(momentum 高 + quality 中性化后仍并列 leader)
    assert res[0]["symbol"] == "Y1"
