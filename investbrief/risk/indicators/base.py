"""Base class for indicator calculations."""

from abc import ABC, abstractmethod
from datetime import datetime

import pandas as pd

from investbrief.risk.config import CN_ALL_INDICATORS, US_ALL_INDICATORS, GOLD_ALL_INDICATORS
from investbrief.risk.calc_utils import normalize_score
import logging

logger = logging.getLogger(__name__)


class BaseIndicator(ABC):
    """Abstract base for indicator calculators."""

    def __init__(self, data_source):
        self.data = data_source

    def _get_config(self, name: str, market: str) -> dict:
        """Get indicator config for given market."""
        if market == "cn":
            indicators = CN_ALL_INDICATORS
        elif market == "us":
            indicators = US_ALL_INDICATORS
        elif market == "gold":
            indicators = GOLD_ALL_INDICATORS
        else:
            indicators = {}
        return indicators.get(name, {})

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
        """分位数打分: value 在 history 序列中的分位 -> 0-10 score。

        正常指标: 分位越高=风险越高=score越高(分位85% -> 8.5)。
        invert指标(低值=高风险, 如股债比): 分位越低=score越高。
        value None / history 空 / 样本<min_samples -> None(调用方回退固定阈值)。
        注: 全样本分位继承平稳性假设(见 docs/methodology.html「分位数的陷阱」);
            样本不足时返回None让调用方回退固定阈值, 避免少量历史点导致分位失真。
        """
        import numpy as np
        if value is None:
            return None
        try:
            arr = np.array([float(x) for x in history if x is not None], dtype=float)
        except (TypeError, ValueError):
            return None
        arr = arr[~np.isnan(arr)]
        if len(arr) == 0 or len(arr) < min_samples:
            return None
        value_f = float(value)
        pct = float((arr < value_f).mean() * 100)
        # 边界修正: 历史 max -> 100分位, min -> 0分位(避免 ties 导致极值打不到顶/底)
        if value_f >= float(arr.max()):
            pct = 100.0
        elif value_f <= float(arr.min()):
            pct = 0.0
        if invert:
            pct = 100.0 - pct
        return round(max(0.0, min(10.0, pct / 10.0)), 1)

    def _get_index_data(self, market: str, days: int = 100, date: str | None = None) -> "pd.DataFrame":
        """Get index daily data for calculation."""
        # gold: 日频金价存于 macro_data(GOLD_PRICE_CNY, 元/克), 不走 index_daily
        if market == "gold":
            base = ("SELECT date, value AS close FROM macro_data "
                    "WHERE indicator='GOLD_PRICE_CNY' AND country='cn' AND value IS NOT NULL")
            if date:
                return self.data.query(base + " AND date <= ? ORDER BY date DESC LIMIT ?",
                                       (date, days)).iloc[::-1]
            return self.data.query(base + " ORDER BY date DESC LIMIT ?", (days,)).iloc[::-1]

        table = "cn_index_daily" if market == "cn" else "us_index_daily"
        code = "sh000001" if market == "cn" else "^GSPC"

        if date:
            sql = f"SELECT * FROM {table} WHERE code = ? AND date <= ? ORDER BY date DESC LIMIT ?"
            return self.data.query(sql, (code, date, days)).iloc[::-1]
        else:
            sql = f"SELECT * FROM {table} WHERE code = ? ORDER BY date DESC LIMIT ?"
            return self.data.query(sql, (code, days)).iloc[::-1]

    @abstractmethod
    def calculate(self, market: str, date: str | None = None) -> dict:
        """Calculate indicator(s) and return {name: {score, value, percentile}}."""
