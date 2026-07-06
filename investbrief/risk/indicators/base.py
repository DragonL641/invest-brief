"""Base class for indicator calculations."""

from abc import ABC, abstractmethod

import pandas as pd

from investbrief.risk.calc_utils import normalize_score
import logging

logger = logging.getLogger(__name__)


class BaseIndicator(ABC):
    """Abstract base for indicator calculators."""

    def __init__(self, data_source):
        self.data = data_source

    def _get_config(self, name: str, market: str) -> dict:
        """Get indicator config for given market (by risk_group)."""
        from investbrief.risk.config import load_indicators
        return load_indicators(market).get(name, {})

    def _score(self, value: float, indicator_name: str, market: str) -> float:
        """Calculate 0-10 risk score for an indicator value."""
        config = self._get_config(indicator_name, market)
        threshold = config.get("thresholds", {}).get(market, 0)
        low = config.get("low_thresholds", {}).get(market, 0)
        invert = config.get("invert", False)

        if invert:
            return normalize_score(value, threshold, threshold * 0.5, invert=True)
        else:
            return normalize_score(value, low, threshold)

    def _score_by_percentile(self, value, history, invert: bool = False, min_samples: int = 100):
        """分位数打分 — 转发 core.scoring。"""
        from investbrief.core.scoring import score_by_percentile
        return score_by_percentile(value, history, invert=invert, min_samples=min_samples)

    def _get_index_data(self, market: str, days: int = 100, date: str | None = None) -> "pd.DataFrame":
        """Get index daily data via market_index_spec (no hardcoded table/code)."""
        from investbrief.data import market_index_spec
        spec = market_index_spec(market)
        if spec["kind"] == "macro":
            base = (f"SELECT date, value AS close FROM macro_data "
                    f"WHERE indicator='{spec['indicator']}' AND country='{spec['country']}' AND value IS NOT NULL")
            if date:
                return self.data.query(base + " AND date <= ? ORDER BY date DESC LIMIT ?",
                                       (date, days)).iloc[::-1]
            return self.data.query(base + " ORDER BY date DESC LIMIT ?", (days,)).iloc[::-1]

        table, code = spec["table"], spec["code"]
        if date:
            sql = f"SELECT * FROM {table} WHERE code = ? AND date <= ? ORDER BY date DESC LIMIT ?"
            return self.data.query(sql, (code, date, days)).iloc[::-1]
        sql = f"SELECT * FROM {table} WHERE code = ? ORDER BY date DESC LIMIT ?"
        return self.data.query(sql, (code, days)).iloc[::-1]

    @abstractmethod
    def calculate(self, market: str, date: str | None = None) -> dict:
        """Calculate indicator(s) and return {name: {score, value, percentile}}."""
