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


def test_get_config_by_group(monkeypatch):
    """_get_config 应按 group 取(不依赖 market 字符串分发)。"""
    from investbrief.risk.indicators.base import BaseIndicator
    from investbrief.risk.config import load_indicators

    class _Dummy(BaseIndicator):
        def calculate(self, market, date=None):
            return {}

    d = _Dummy(data_source=None)
    cn_cfg = d._get_config("ma50_deviation", "cn")
    assert cn_cfg == load_indicators("cn").get("ma50_deviation", {})
    us_cfg = d._get_config("index_pe", "us")
    assert us_cfg == load_indicators("us").get("index_pe", {})
    gold_cfg = d._get_config("gold_gdp_ratio", "gold")
    assert gold_cfg == load_indicators("gold").get("gold_gdp_ratio", {})
    assert d._get_config("nope", "cn") == {}
