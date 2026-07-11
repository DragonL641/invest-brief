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
    _credit_direction,
    _apply_credit_confidence,
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


class TestCreditDirection:
    """CN 信用轴:M2_YOY(已是同比)+ SOCIAL_FIN(月度流量,先 YoY 去季节性)。"""

    def test_both_up_expansion(self):
        # M2_YOY 单调升 + SOCIAL_FIN 流量同比升 → expansion
        m2 = [7.0, 7.5, 8.0, 8.5, 9.0, 9.5]  # window=3, last 4 diff all up
        # SOCIAL_FIN 13 期流量(period=12 → 1 YoY 点,不够 vote)→ 需 16+ 期
        sf = [100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100,
              110, 110, 110]  # YoY: 末 4 期 [10, 10, 10, 10] 平 → 不参与(无方向)
        # 这里 SOCIAL_FIN YoY 全平 → 投票 unknown → 仅 M2 投票 → 仍判 expansion(单信号)
        r = _credit_direction({"M2_YOY": m2, "SOCIAL_FIN": sf}, 12, 3, 2)
        assert r == "expansion"

    def test_both_down_slowdown(self):
        m2 = [9.5, 9.0, 8.5, 8.0, 7.5, 7.0]
        # SOCIAL_FIN 流量:13+ 期,后段比前段低 → YoY 下行
        sf = [200, 200, 200, 200, 200, 200, 200, 200, 200, 200, 200, 200, 200,
              190, 180, 170]
        r = _credit_direction({"M2_YOY": m2, "SOCIAL_FIN": sf}, 12, 3, 2)
        assert r == "slowdown"

    def test_mixed_unknown(self):
        # M2 升 + SOCIAL_FIN YoY 降 → 混合 → unknown(不强改 confidence)
        m2 = [7.0, 7.5, 8.0, 8.5, 9.0, 9.5]
        sf = [200, 200, 200, 200, 200, 200, 200, 200, 200, 200, 200, 200, 200,
              190, 180, 170]
        r = _credit_direction({"M2_YOY": m2, "SOCIAL_FIN": sf}, 12, 3, 2)
        assert r == "unknown"

    def test_empty_unknown(self):
        assert _credit_direction({}, 12, 3, 2) == "unknown"

    def test_insufficient_samples_unknown(self):
        # 序列短于 window+1 → 不投票 → unknown
        assert _credit_direction({"M2_YOY": [8.0, 8.1]}, 12, 3, 2) == "unknown"

    def test_socialfin_seasonality_removed(self):
        """SOCIAL_FIN 月度流量有强季节性(1月巨量)。
        直接投票会被季节性误导;先 YoY 去季节性后才看趋势。
        构造:连续两年 1 月巨量、其他月小,但年度总量稳定 → YoY 平 → 不投票(unknown)。
        """
        # 24 个月,Jan=72000 其他月=5000(模拟季节性),两年完全相同 → YoY=0
        sf = []
        for year in range(2):
            for month in range(12):
                sf.append(72000 if month == 0 else 5000)
        m2 = [8.0, 8.5, 9.0, 9.5]  # M2 升 → 单信号 expansion
        r = _credit_direction({"M2_YOY": m2, "SOCIAL_FIN": sf}, 12, 3, 2)
        # SOCIAL_FIN YoY 全 0 → unknown;只剩 M2 → expansion
        assert r == "expansion"


class TestApplyCreditConfidence:
    def test_same_direction_expansion_boost(self):
        # growth 扩张 + 信用扩张 → +10
        c = _apply_credit_confidence(70, "expansion", "expansion")
        assert c == 80

    def test_same_direction_slowdown_boost(self):
        c = _apply_credit_confidence(70, "slowdown", "slowdown")
        assert c == 80

    def test_credit_turn_warns_expansion(self):
        # growth 扩张 + 信用放缓 → -10(拐点预警)
        c = _apply_credit_confidence(70, "expansion", "slowdown")
        assert c == 60

    def test_credit_turn_warns_slowdown_pre_recovery(self):
        # growth 放缓 + 信用扩张 → -10(复苏前置,GDP 可能跟随)
        c = _apply_credit_confidence(70, "slowdown", "expansion")
        assert c == 60

    def test_credit_unknown_no_change(self):
        assert _apply_credit_confidence(70, "expansion", "unknown") == 70

    def test_growth_unknown_no_change(self):
        # growth 不明 → 信用不足以强改
        assert _apply_credit_confidence(70, "unknown", "expansion") == 70

    def test_clamp_high(self):
        # 95 + 10 → clamp 95
        assert _apply_credit_confidence(95, "expansion", "expansion") == 95

    def test_clamp_low(self):
        # 20 - 10 → clamp 20
        assert _apply_credit_confidence(20, "expansion", "slowdown") == 20


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
        assert r["growth_axis"] == "信号不足"

    def test_cn_credit_axis_boosts_confidence_on_alignment(self):
        """CN: GDP 扩张 + 信用扩张 → confidence 比无信用时高 10。

        构造 GDP 季度加速上行(二次式,同比单调升)+ CPI 下行 + M2 同比单调升
        + SOCIAL_FIN 流量 YoY 单调升 → growth=扩张/inflation=下行 → 繁荣,
        信用同向 → confidence 90 → +10=95(clamp)。
        """
        # 8 季度 GDP 二次式
        gdp = [100.0 + 2 * i * i for i in range(8)]
        cpi = [3.0, 2.9, 2.8, 2.7]  # 月度下行
        # 不传信用 vs 传信用对比
        r_no_credit = _judge_from_series(gdp, cpi, "cn")
        assert r_no_credit["quadrant"] == "繁荣"
        base_conf = r_no_credit["confidence"]

        m2 = [7.0, 7.5, 8.0, 8.5, 9.0, 9.5]  # 同比升
        sf = [100] * 12 + [110, 110, 110, 110]  # 16 期:YoY=10% 平 → 不参与,仅 M2 投票
        r_with_credit = _judge_from_series(gdp, cpi, "cn",
                                           credit_series={"M2_YOY": m2, "SOCIAL_FIN": sf})
        assert r_with_credit["quadrant"] == "繁荣"  # 象限不变
        assert r_with_credit["credit_axis"] == "扩张"
        assert r_with_credit["confidence"] == min(95, base_conf + 10)
        # 信用末值应进 indicators
        assert "M2_YOY" in r_with_credit["indicators"]
        assert r_with_credit["indicators"]["M2_YOY"] == 9.5

    def test_cn_credit_axis_warns_on_divergence(self):
        """CN: GDP 扩张 + 信用放缓 → confidence -10(拐点预警)。"""
        gdp = [100.0 + 2 * i * i for i in range(8)]  # GDP 加速 → 扩张
        cpi = [3.0, 2.9, 2.8, 2.7]
        r_base = _judge_from_series(gdp, cpi, "cn")
        # 信用放缓:M2 + 社融 YoY 都下行
        m2 = [9.5, 9.0, 8.5, 8.0, 7.5, 7.0]
        sf = [200] * 12 + [190, 180, 170, 160]
        r = _judge_from_series(gdp, cpi, "cn",
                               credit_series={"M2_YOY": m2, "SOCIAL_FIN": sf})
        assert r["quadrant"] == "繁荣"  # 象限仍由 GDP×CPI 决定
        assert r["credit_axis"] == "放缓"
        assert r["confidence"] == max(20, r_base["confidence"] - 10)

    def test_cn_credit_mixed_no_change(self):
        """CN: 信用混合(M2 升 + 社融降)→ credit_axis=未知 → confidence 不变。"""
        gdp = [100.0 + 2 * i * i for i in range(8)]
        cpi = [3.0, 2.9, 2.8, 2.7]
        r_base = _judge_from_series(gdp, cpi, "cn")
        m2 = [7.0, 7.5, 8.0, 8.5, 9.0, 9.5]  # 升
        sf = [200] * 12 + [190, 180, 170, 160]  # 降
        r = _judge_from_series(gdp, cpi, "cn",
                               credit_series={"M2_YOY": m2, "SOCIAL_FIN": sf})
        assert r["credit_axis"] == "信号不足"
        assert r["confidence"] == r_base["confidence"]

    def test_us_never_has_credit_axis(self):
        """US 不传 credit_series → credit_axis=None(永远 None,即使 market='us')。"""
        gdp = [100 + 0.1 * i * i for i in range(24)]
        cpi = [3.0, 2.9, 2.8, 2.7]
        r = _judge_from_series(gdp, cpi, "us")
        assert r["credit_axis"] is None
        assert "M2_YOY" not in r["indicators"]


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

    def test_judge_cn_reads_credit_series(self):
        """CN judge 自动读 macro_data 的 M2_YOY + SOCIAL_FIN → credit_axis 不为 None。

        构造 GDP 扩张 + CPI 下行 + M2 同比单调升 → credit_axis='扩张',confidence 提升。
        """
        gdp = [("GDP", "cn", f"2024-Q{n}", 100.0 + 2 * i * i) for i, n in enumerate(range(1, 5))] + \
              [("GDP", "cn", f"2025-Q{n}", 100.0 + 2 * (4 + i) * (4 + i)) for i, n in enumerate(range(1, 5))]
        cpi = [("CPI", "cn", "2025-04-01", 1.1),
               ("CPI", "cn", "2025-05-01", 1.0),
               ("CPI", "cn", "2025-06-01", 0.9),
               ("CPI", "cn", "2025-07-01", 0.8),
               ("CPI", "cn", "2025-08-01", 0.7)]
        # M2 同比 6 月单调升 → 投票 up
        m2 = [("M2_YOY", "cn", f"2026-{m:02d}-01", 7.0 + 0.5 * i)
              for i, m in enumerate(range(1, 7))]
        rows = gdp + cpi + m2
        eng = RegimeEngine(_FakeData(rows))
        r = eng.judge("cn")
        assert r["quadrant"] == "繁荣"
        assert r["credit_axis"] == "扩张"  # M2 单调升(无 SOCIAL_FIN → 单信号也确认)
        assert "M2_YOY" in r["indicators"]

    def test_judge_cn_no_credit_data_degrades_gracefully(self):
        """CN 无 M2/社融 数据 → credit_axis='未知',confidence 不变(优雅降级)。"""
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
        assert r["credit_axis"] == "信号不足"  # 无信用数据

    def test_cn_switch_runs_1_no_lookback_downgrade(self):
        """CN: SWITCH_CONFIRMATION_RUNS_CN=1 → 不回看,即使末值象限跳变也不降级。

        构造 CN GDP + CPI:含末值判通胀(末值 CPI 跳升>阈值),去末值判繁荣。
        若 RUNS=2 会降级中性;RUNS=1 → 保持通胀。
        """
        gdp = [("GDP", "cn", f"2024-Q{n}", 100.0 + 2 * i * i) for i, n in enumerate(range(1, 5))] + \
              [("GDP", "cn", f"2025-Q{n}", 100.0 + 2 * (4 + i) * (4 + i)) for i, n in enumerate(range(1, 5))]
        # CPI 末两期急升:CPI=4.5>INFLATION_UP_THRESHOLD=2.5 → 通胀上行象限
        cpi = [("CPI", "cn", "2025-04-01", 1.1),
               ("CPI", "cn", "2025-05-01", 1.0),
               ("CPI", "cn", "2025-06-01", 0.9),
               ("CPI", "cn", "2025-07-01", 3.5),
               ("CPI", "cn", "2025-08-01", 4.5)]
        eng = RegimeEngine(_FakeData(gdp + cpi))
        r = eng.judge("cn")
        # RUNS=1 → 不回看 → 保持末值判定(通胀)
        assert r["quadrant"] == "通胀"

    def test_us_switch_runs_2_still_lookback_downgrades(self):
        """US: SWITCH_CONFIRMATION_RUNS_US=2 → 回看,象限跳变降级中性(已有测试 + 此对照)。"""
        # 复用 _us_rows 末两期 CPI 跳升 → 末值通胀 vs 去末值繁荣 → 降级
        rows = [r for r in self._us_rows()
                if not (r[0] == "CPI" and r[2] in ("2025-06-01", "2025-07-01"))]
        rows += [("CPI", "us", "2025-06-01", 3.5),
                 ("CPI", "us", "2025-07-01", 4.5)]
        eng = RegimeEngine(_FakeData(rows))
        r = eng.judge("us")
        assert r["quadrant"] == "中性"
