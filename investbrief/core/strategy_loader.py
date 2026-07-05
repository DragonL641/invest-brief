"""Unified strategy YAML loader: lru_cache + schema validation + friendly errors.

Strategy files live in investbrief/strategies/. They are static after startup,
so lru_cache is safe. Call load_strategy.cache_clear() in tests if you mutate.
"""
import logging
from functools import cache
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

STRATEGIES_DIR = Path(__file__).resolve().parent.parent / "strategies"


@cache
def load_strategy(name: str) -> dict:
    """Load strategies/<name>.yaml (cached). Raises FileNotFoundError / ValueError."""
    path = STRATEGIES_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Strategy file not found: {path}")
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict) or not data:
        raise ValueError(f"Invalid or empty strategy file: {path}")
    return data
