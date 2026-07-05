# investbrief/picks/engine.py
"""截面 rank percentile 标准化 + profile 权重加权 + Top N 排名。

输入: candidates = [{symbol,name,market,raw_factors:{f:float|None},industry}]
输出: 按 composite 降序的 pick 列表(含 factor_scores/triggers 等,见数据契约)。
"""
from __future__ import annotations
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd


def rank_picks(candidates: list[dict], profile: dict, market: str) -> list[dict]:
    """对候选池做截面打分排名,返回 pick 列表(已按 composite 降序,带 rank)。"""
    if not candidates:
        return []
    factor_cfg = profile["factors"]
    factor_keys = list(factor_cfg.keys())

    # 收集每个因子的有效值序列
    series = {f: [c["raw_factors"].get(f) for c in candidates] for f in factor_keys}

    # rank percentile(0-100),invert 处理
    pct = {}
    for f in factor_keys:
        vals = pd.Series(series[f], dtype="float64")
        valid = vals.dropna()
        if valid.empty:
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
    """挑出 percentile ≥ 70 的因子作为买入逻辑条目(人读)。"""
    out = []
    for f, sc in factor_scores.items():
        p = sc.get("pct")
        if p is not None and p >= 70:
            out.append(f"{f} 处于池内前 {100 - p:.0f}%")
    return out
