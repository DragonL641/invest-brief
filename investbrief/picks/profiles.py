# investbrief/picks/profiles.py
"""加载并校验 strategies/pick_profiles.yaml。"""
from __future__ import annotations
from functools import lru_cache

from investbrief.core import strategy_loader as _strategy

_REQUIRED_PROFILES = ("swing", "medium", "long")


@lru_cache(maxsize=1)
def load_profiles() -> dict:
    """返回 {profile_name: profile_dict}。校验失败抛 ValueError。"""
    raw = _strategy.load_strategy("pick_profiles")
    profiles = raw.get("profiles") or {}
    for name in _REQUIRED_PROFILES:
        if name not in profiles:
            raise ValueError(f"pick_profiles.yaml missing profile: {name}")
        _validate(name, profiles[name])
    return {k: profiles[k] for k in _REQUIRED_PROFILES}


def _validate(name: str, p: dict):
    for key in ("universe", "factors", "top_n"):
        if key not in p:
            raise ValueError(f"profile {name} missing required key: {key}")
    std = p.get("standardize", "rank_percentile")
    if std != "rank_percentile":
        raise ValueError(f"profile {name}: standardize='{std}' not supported (use rank_percentile)")
    weights = [f.get("weight") for f in p["factors"].values()]
    if any(not isinstance(w, (int, float)) for w in weights):
        raise ValueError(f"profile {name}: every factor needs a numeric weight")
    if abs(sum(weights) - 1.0) > 1e-6:
        raise ValueError(f"profile {name}: factor weights must sum to 1.0 (got {sum(weights):.4f})")
    if "industry_neutralize" not in p:
        raise ValueError(f"profile {name}: industry_neutralize is required (true/false)")
