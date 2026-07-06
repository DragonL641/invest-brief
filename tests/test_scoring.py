"""core.scoring 纯函数算法回归。

从 risk/calc_utils.py + risk/indicators/base.py 提炼, 逻辑必须逐字一致
(否则 risk 分数漂移)。

注: percentile_rank 沿用现有 risk/calc_utils.py 实现 — 仅接受 pd.Series
(生产调用方 risk/models.py 传 DataFrame 列)。测试用 pd.Series 构造。
score_by_percentile 沿用现有 _score_by_percentile — 内部 np.array 化,
接受任意 1D iterable, 测试用 list。
"""
import pandas as pd

from investbrief.core.scoring import (
    percentile_rank, normalize_score, safe_divide, score_by_percentile,
)


class TestPercentileRank:
    def test_value_above_all(self):
        assert percentile_rank(100, pd.Series([1, 2, 3])) == 100.0

    def test_value_below_all(self):
        assert percentile_rank(0, pd.Series([1, 2, 3])) == 0.0

    def test_empty_series(self):
        assert percentile_rank(5, pd.Series([])) == 50.0


class TestNormalizeScore:
    def test_normal_low(self):
        assert normalize_score(0, 10, 20) == 0.0

    def test_normal_high(self):
        assert normalize_score(20, 10, 20) == 10.0

    def test_invert(self):
        assert normalize_score(20, 10, 5, invert=True) == 0.0
        assert normalize_score(0, 10, 5, invert=True) == 10.0


class TestSafeDivide:
    def test_zero_denominator(self):
        assert safe_divide(10, 0) == 0.0

    def test_normal(self):
        assert safe_divide(10, 2) == 5.0


class TestScoreByPercentile:
    def test_insufficient_samples(self):
        assert score_by_percentile(5, [1, 2, 3], min_samples=100) is None

    def test_max_value(self):
        history = list(range(100))
        assert score_by_percentile(99, history) == 10.0

    def test_invert(self):
        history = list(range(100))
        # value 处于历史 min -> pct=0 -> invert -> 100 -> score 10.0
        # (value=1 时实际得分 9.9, 非极值; 现有 _score_by_percentile 行为)
        assert score_by_percentile(0, history, invert=True) == 10.0
