"""RegimeEngine 纯函数 + 类的单测。

纯函数不依赖 DB,直接测试;RegimeEngine 类用 FakeData mock query。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from investbrief.regime.engine import (
    _yoy_from_absolute,
    _direction_vote,
    _classify,
    _confidence,
    _judge_from_series,
)


class TestYoyFromAbsolute:
    def test_quarterly_period_4(self):
        # 5 个季度,period=4 → 1 个同比点
        # values[4]/values[0]-1 = 110/100-1 = 0.10 → 10.0%
        assert _yoy_from_absolute([100, 105, 108, 109, 110], 4) == [10.0]

    def test_insufficient_returns_empty(self):
        assert _yoy_from_absolute([100, 105, 108], 4) == []

    def test_multiple_points(self):
        # 8 个季度 → 4 个同比点
        out = _yoy_from_absolute([100, 100, 100, 100, 110, 110, 110, 110], 4)
        assert out == [10.0, 10.0, 10.0, 10.0]


class TestDirectionVote:
    def test_up_majority(self):
        # 最近 4 个点(3 个 diff),2 升 1 降 → up
        assert _direction_vote([2.0, 2.1, 2.3, 2.2], 3, 2) == "up"

    def test_down_majority(self):
        assert _direction_vote([2.5, 2.4, 2.2, 2.3], 3, 2) == "down"

    def test_mixed_unknown(self):
        # 1 升 1 降 1 平 → 不达 2 → unknown
        assert _direction_vote([2.0, 2.1, 2.0, 2.0], 3, 2) == "unknown"

    def test_too_short_unknown(self):
        assert _direction_vote([2.0, 2.1], 3, 2) == "unknown"


class TestClassify:
    def test_prosperity(self):
        # 增长扩张 + 通胀下行 → 繁荣
        assert _classify("expansion", "down", 2.0) == "繁荣"

    def test_inflation_overheating(self):
        # 增长扩张 + 通胀上行 + CPI>2.5 → 通胀(过热)
        assert _classify("expansion", "up", 3.0) == "通胀"

    def test_inflation_below_threshold_is_prosperity(self):
        # 通胀方向 up 但 CPI 未超 2.5 → 仍算繁荣(稳)
        assert _classify("expansion", "up", 2.3) == "繁荣"

    def test_deflation(self):
        # 增长放缓 + 通胀下行 → 通缩
        assert _classify("slowdown", "down", 1.0) == "通缩"

    def test_stagflation(self):
        # 增长放缓 + 通胀上行 + CPI>2.5 → 滞胀
        assert _classify("slowdown", "up", 4.0) == "滞胀"

    def test_unknown_axis_returns_neutral(self):
        assert _classify("unknown", "up", 3.0) == "中性"
        assert _classify("expansion", "unknown", 2.0) == "中性"

    def test_slowdown_flat_inflation_neutral(self):
        # 增长放缓 + 通胀稳(非 up 非 down)→ 中性
        assert _classify("slowdown", "flat", 2.0) == "中性"


class TestConfidence:
    def test_neutral_low(self):
        assert _confidence("expansion", "up", "中性") == 30

    def test_both_clear_higher(self):
        c = _confidence("expansion", "down", "繁荣")
        assert c >= 75


class TestJudgeFromSeries:
    def test_us_prosperity_scenario(self):
        # US: GDP 月度(period=12),构造 24 个月加速上行 → 同比上行 → 扩张
        # CPI 构造下行 → 繁荣
        # 注:线性绝对值会得出同比下行(基数效应),需二次方才保证同比单调升
        gdp = [100 + 0.1 * i * i for i in range(24)]  # 加速上行 → 同比升
        cpi = [3.0, 2.9, 2.8, 2.7]  # 月度下行
        r = _judge_from_series(gdp, cpi, "us")
        assert r["quadrant"] == "繁荣"
        assert r["growth_axis"] == "扩张"
        assert r["inflation_axis"] == "下行"
        assert "GDP_YOY" in r["indicators"]
        assert "CPI_LATEST" in r["indicators"]

    def test_empty_series_returns_neutral(self):
        r = _judge_from_series([], [], "us")
        assert r["quadrant"] == "中性"
        assert r["growth_axis"] == "未知"
