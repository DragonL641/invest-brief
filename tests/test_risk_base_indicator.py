"""Tests for BaseIndicator helpers (② 分位数打分)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from investbrief.risk.indicators.base import BaseIndicator


class _ConcreteIndicator(BaseIndicator):
    """最小实现: 仅满足抽象约束, 供测试复用 BaseIndicator 的具体方法。"""

    def calculate(self, market: str, date: str | None = None) -> dict:
        return {}


def _ind():
    """BaseIndicator 实例(跳过 __init__, 不需 data_source)。"""
    return _ConcreteIndicator.__new__(_ConcreteIndicator)


class TestScoreByPercentile:
    def test_highest_value_scores_ten(self):
        assert _ind()._score_by_percentile(90, [10, 20, 30, 90], min_samples=0) == 10.0

    def test_mid_value(self):
        assert _ind()._score_by_percentile(15, [10, 20, 30, 90], min_samples=0) == 2.5

    def test_invert_flips_direction(self):
        assert _ind()._score_by_percentile(10, [10, 20, 30, 90], invert=True, min_samples=0) == 10.0

    def test_missing_returns_none(self):
        assert _ind()._score_by_percentile(None, [1, 2, 3], min_samples=0) is None
        assert _ind()._score_by_percentile(5, [], min_samples=0) is None

    def test_clamps_to_ten(self):
        assert _ind()._score_by_percentile(1000, [1, 2, 3], min_samples=0) == 10.0

    def test_insufficient_samples_returns_none(self):
        # 默认 min_samples=100, 少量历史点返回None -> 调用方回退固定阈值
        assert _ind()._score_by_percentile(5, [1, 2, 3]) is None
