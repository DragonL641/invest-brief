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


import pandas as pd

from investbrief.regime.engine import RegimeEngine


class _FakeData:
    """Mock data_source:query 返回预设 macro_data DataFrame。

    rows: list of (indicator, country, date, value)。query 用 indicator+country 过滤。
    """

    def __init__(self, rows):
        self._df = pd.DataFrame(rows, columns=["indicator", "country", "date", "value"])

    def query(self, sql, params=()):
        indicator, country = params[0], params[1]
        sub = self._df[(self._df["indicator"] == indicator)
                       & (self._df["country"] == country)
                       & self._df["value"].notna()]
        return sub[["value"]].sort_index()  # 保持插入顺序(测试数据按日期升序构造)


class TestRegimeEngine:
    def _us_rows(self):
        """构造 US:GDP 月度加速上行(24 月,二次式保证同比单调升)+ CPI 下行(5 月)→ 繁荣。

        注:线性绝对值因基数效应会让同比下降(已由 test_us_prosperity_scenario 记录),
        故采用二次式。CPI 取 5 期以保证切换确认去掉末值后仍余 4 期(≥ window+1=4)。
        """
        gdp = [("GDP", "us", f"2024-{m:02d}-01", 100.0 + 0.1 * i * i)
               for i, m in enumerate(range(1, 13))] + \
              [("GDP", "us", f"2025-{m:02d}-01", 100.0 + 0.1 * (12 + i) * (12 + i))
               for i, m in enumerate(range(1, 13))]
        cpi = [("CPI", "us", "2025-03-01", 3.1),
               ("CPI", "us", "2025-04-01", 3.0),
               ("CPI", "us", "2025-05-01", 2.9),
               ("CPI", "us", "2025-06-01", 2.8),
               ("CPI", "us", "2025-07-01", 2.7)]
        return gdp + cpi

    def test_judge_us_prosperity(self):
        eng = RegimeEngine(_FakeData(self._us_rows()))
        r = eng.judge("us")
        assert r["quadrant"] == "繁荣"
        assert r["market"] == "us"
        assert "GDP_YOY" in r["indicators"]

    def test_judge_empty_data_neutral(self):
        eng = RegimeEngine(_FakeData([]))
        r = eng.judge("us")
        assert r["quadrant"] == "中性"
        assert r["confidence"] == 30

    def test_switch_confirmation_downgrades(self):
        """含末值与不含末值判定不一致 → 切换确认降级中性。

        将 _us_rows 末两期 CPI 替换为急升([3.5, 4.5]):
        - 含末值:最近 4 期 [3.0,2.9,3.5,4.5],diffs=[-0.1,+0.6,+1.0],up=2 → 通胀上行
          且 CPI 末值 4.5 > INFLATION_UP_THRESHOLD → 象限=通胀。
        - 去末值:最近 4 期 [3.1,3.0,2.9,3.5],diffs=[-0.1,-0.1,+0.6],up=1/down=2 → 下行 → 繁荣。
        两者(通胀 vs 繁荣)不一致 → 降级中性。
        """
        rows = [r for r in self._us_rows()
                if not (r[0] == "CPI" and r[2] in ("2025-06-01", "2025-07-01"))]
        rows += [("CPI", "us", "2025-06-01", 3.5),
                 ("CPI", "us", "2025-07-01", 4.5)]
        eng = RegimeEngine(_FakeData(rows))
        r = eng.judge("us")
        assert r["quadrant"] == "中性"

    def test_judge_cn_uses_quarterly_period(self):
        """CN GDP 季度(period=4):构造 8 个季度加速上行(二次式)+ CPI 下行(5 月)→ 繁荣。

        二次式保证同比单调升;CPI 取 5 期以保证切换确认去掉末值后仍余 4 期。
        """
        gdp = [("GDP", "cn", f"2024-Q{n}", 100.0 + 2 * i * i) for i, n in enumerate(range(1, 5))] + \
              [("GDP", "cn", f"2025-Q{n}", 100.0 + 2 * (4 + i) * (4 + i)) for i, n in enumerate(range(1, 5))]
        cpi = [("CPI", "cn", "2025-04-01", 1.1),
               ("CPI", "cn", "2025-05-01", 1.0),
               ("CPI", "cn", "2025-06-01", 0.9),
               ("CPI", "cn", "2025-07-01", 0.8),
               ("CPI", "cn", "2025-08-01", 0.7)]
        eng = RegimeEngine(_FakeData(gdp + cpi))
        r = eng.judge("cn")
        assert r["quadrant"] == "繁荣"
        assert r["market"] == "cn"
