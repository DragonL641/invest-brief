# investbrief/picks/engine.py
"""截面 rank percentile 标准化 + profile 权重加权 + Top N 排名。

输入: candidates = [{symbol,name,market,raw_factors:{f:float|None},industry}]
输出: 按 composite 降序的 pick 列表(含 factor_scores/triggers 等,见数据契约)。
"""
from __future__ import annotations
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from investbrief.picks.factors import FACTOR_CATEGORY, FACTOR_LABELS  # 同域 picks→picks,OK


def rank_picks(candidates: list[dict], profile: dict, market: str) -> list[dict]:
    """对候选池做截面打分排名,返回 pick 列表(已按 composite 降序,带 rank)。"""
    if not candidates:
        return []
    factor_cfg = profile["factors"]
    factor_keys = list(factor_cfg.keys())
    neutralize = bool(profile.get("industry_neutralize"))

    # 收集每个因子的有效值序列(可能在行业中性化后被改写)
    industries = [c.get("industry") for c in candidates]
    series = {}
    for f in factor_keys:
        raw_vals = [c["raw_factors"].get(f) for c in candidates]
        if (neutralize and FACTOR_CATEGORY.get(f) == "fundamental"
                and _has_industry_groups(industries)):
            raw_vals = _neutralize_by_industry(raw_vals, industries)
        series[f] = raw_vals

    # rank percentile(0-100),invert 处理
    pct = {}
    for f in factor_keys:
        vals = pd.Series(series[f], dtype="float64")
        valid = vals.dropna()
        if len(valid) < 3:
            # 太稀疏(含全 None):百分位无统计意义,该因子全员贡献 0(同 all-None 路径)
            pct[f] = [None] * len(candidates)
            continue
        ranked = vals.rank(pct=True) * 100   # NaN 保持 NaN
        if factor_cfg[f].get("invert"):
            ranked = 100 - ranked
        pct[f] = ranked.tolist()

    now = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M")
    results = []
    for i, c in enumerate(candidates):
        factor_scores = {}
        composite = 0.0
        for f in factor_keys:
            raw = c["raw_factors"].get(f)
            p = pct[f][i]
            weight = factor_cfg[f]["weight"]
            # NaN-safe: p == p is False when p is NaN
            weighted = (p * weight) if (p is not None and p == p) else 0.0
            composite += weighted
            factor_scores[f] = {
                "raw": raw,
                "pct": (None if (p is None or p != p) else round(p, 1)),
                "weighted": round(weighted, 2),
            }
        results.append({
            "symbol": c["symbol"], "name": c.get("name", c["symbol"]),
            "market": market, "profile": _profile_name(profile),
            "composite": round(composite, 2),
            "factor_scores": factor_scores,
            "triggers": _triggers(factor_scores, factor_cfg),
            "industry": c.get("industry"),
            "data_time": now,
        })

    results.sort(key=lambda r: r["composite"], reverse=True)
    for idx, r in enumerate(results, 1):
        r["rank"] = idx
    top_n = profile.get("top_n", 1)
    return results[:top_n]


def _profile_name(profile: dict) -> str | None:
    return profile.get("_name")


def _triggers(factor_scores: dict, factor_cfg: dict) -> list[str]:
    """挑出 percentile ≥ 70 的因子作为买入逻辑条目(中文可读)。"""
    out = []
    for f, sc in factor_scores.items():
        p = sc.get("pct")
        if p is not None and p >= 70:
            label = FACTOR_LABELS.get(f, f)
            out.append(f"{label} 居池内前 {100 - p:.0f}%")
    return out


# ---- TODO D 行业中性化 ----

def _has_industry_groups(industries: list) -> bool:
    """是否至少有一个非 None 的行业标签(否则中性化是 no-op,跳过省成本)。"""
    return any(x is not None for x in industries)


def _neutralize_by_industry(values: list, industries: list) -> list:
    """对每个候选:v' = v - industry_group_median(v)。

    - 行业标签 None 的候选自成一组(或等价地用全局中位数)
    - NaN 候选保持 NaN(不参与中位数计算)
    - 全是 NaN 的组:中位数 NaN,减后所有候选变 NaN → rank 时全员无值,等价于稀疏降级
      (实际不会发生,因为外层先检查 len(valid) < 3)
    """
    s = pd.Series(values, dtype="float64")
    ind = pd.Series(industries, dtype="object")
    # 按行业分组求中位数(NaN-skipped);None 行业会形成单独的 NaN 组
    med = s.groupby(ind, dropna=False).transform("median")
    return (s - med).tolist()
