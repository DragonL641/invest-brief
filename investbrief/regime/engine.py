"""经济环境四象限判定引擎(Browne 增长×通胀)。

模块级纯函数(_yoy_from_absolute / _direction_vote / _classify / _confidence /
_credit_direction / _apply_credit_confidence / _judge_from_series)不依赖 DB,
可独立单测。RegimeEngine 类负责取数 + 切换确认。
"""
import logging

from investbrief.regime.config import (
    INFLATION_UP_THRESHOLD, DIRECTION_VOTE_MIN_AGREEING,
    VOTE_WINDOW_MONTHLY, VOTE_WINDOW_QUARTERLY,
    GDP_PERIOD_CN, GDP_PERIOD_US,
    SWITCH_CONFIRMATION_RUNS_CN, SWITCH_CONFIRMATION_RUNS_US,
    GROWTH_INDICATOR, INFLATION_INDICATOR,
    CREDIT_INDICATORS_CN, CREDIT_PERIOD_CN,
)

logger = logging.getLogger(__name__)

_GDP_PERIOD = {"cn": GDP_PERIOD_CN, "us": GDP_PERIOD_US}
_GDP_WINDOW = {"cn": VOTE_WINDOW_QUARTERLY, "us": VOTE_WINDOW_MONTHLY}
_SWITCH_RUNS = {"cn": SWITCH_CONFIRMATION_RUNS_CN, "us": SWITCH_CONFIRMATION_RUNS_US}

_GROWTH_LABEL = {"expansion": "扩张", "slowdown": "放缓", "unknown": "未知"}
_INFLATION_LABEL = {"up": "上行", "down": "下行", "unknown": "未知"}
_CREDIT_LABEL = {"expansion": "扩张", "slowdown": "放缓", "unknown": "未知"}


def _yoy_from_absolute(values: list[float], period: int) -> list[float]:
    """绝对值序列 → 同比序列(%)。values 需升序、等频率;period=一年期数(季度 4/月度 12)。

    数据不足以回看一年 → 返回 []。
    """
    if len(values) <= period:
        return []
    return [round((values[i] / values[i - period] - 1) * 100, 3)
            for i in range(period, len(values))]


def _direction_vote(series: list[float], window: int, min_agreeing: int) -> str:
    """最近 window 期逐期变化方向投票 → 'up'/'down'/'unknown'。

    取最近 window+1 个点算 window 个逐期 diff,统计上升/下降计数;
    任一方向计数 ≥ min_agreeing 才确认,否则 'unknown'(去噪层 1:趋势投票)。
    """
    if len(series) < window + 1:
        return "unknown"
    recent = series[-(window + 1):]
    diffs = [recent[i] - recent[i - 1] for i in range(1, len(recent))]
    up = sum(1 for d in diffs if d > 0)
    down = sum(1 for d in diffs if d < 0)
    if up >= min_agreeing:
        return "up"
    if down >= min_agreeing:
        return "down"
    return "unknown"


def _classify(growth_dir: str, inflation_dir: str, cpi_latest: float | None) -> str:
    """增长×通胀方向 → 象限名(繁荣/通胀/通缩/滞胀/中性)。

    通胀上行象限额外要求 CPI 同比 > INFLATION_UP_THRESHOLD(去噪层 2:水平门槛)。
    """
    if growth_dir == "unknown" or inflation_dir == "unknown":
        return "中性"
    inflation_up = (inflation_dir == "up"
                    and cpi_latest is not None
                    and cpi_latest > INFLATION_UP_THRESHOLD)
    inflation_down = inflation_dir == "down"
    if inflation_up:
        return "通胀" if growth_dir == "expansion" else "滞胀"
    if inflation_down:
        return "繁荣" if growth_dir == "expansion" else "通缩"
    # 通胀稳(非 up 非 down,或 up 但未超阈值)
    return "繁荣" if growth_dir == "expansion" else "中性"


def _confidence(growth_dir: str, inflation_dir: str, quadrant: str) -> int:
    """象限置信度(0-100,粗粒度)。中性低置信;两轴都明确则高。"""
    if quadrant == "中性":
        return 30
    conf = 55
    if growth_dir != "unknown":
        conf += 20
    if inflation_dir != "unknown":
        conf += 20
    return min(90, conf)


def _credit_direction(
    credit_series: dict, period: int, window: int, min_agreeing: int,
    seasonal_indicators: tuple = ("SOCIAL_FIN",),
) -> str:
    """信用序列(M2_YOY + SOCIAL_FIN)→ 综合信用方向 'expansion'/'slowdown'/'unknown'。

    M2_YOY 已是同比,直接 _direction_vote;seasonal_indicators 中的序列(默认 SOCIAL_FIN)
    是月度流量(强季节性),先 _yoy_from_absolute(period) 去季节性再投票。
    多序列投票一致才确认;混合信号 → 'unknown'(中性,不强改 confidence)。

    Args:
        credit_series: {indicator: values_list},例如 {"M2_YOY": [...], "SOCIAL_FIN": [...]}
        period: 流量序列的 YoY 偏移周期(月度=12);已是同比的序列不受影响
        window: _direction_vote 窗口
        min_agreeing: _direction_vote 最少一致期数
    """
    votes = []
    for ind, vals in credit_series.items():
        series = vals
        if ind in seasonal_indicators:
            series = _yoy_from_absolute(vals, period)
        if len(series) < window + 1:
            continue
        votes.append(_direction_vote(series, window, min_agreeing))
    # 过滤 'unknown' 投票:某指标"不确定"不应否决其他指标的明确信号
    votes = [v for v in votes if v != "unknown"]
    if not votes:
        return "unknown"
    if all(v == "up" for v in votes):
        return "expansion"
    if all(v == "down" for v in votes):
        return "slowdown"
    return "unknown"  # 真正混合(有 up 有 down)→ 中性


def _apply_credit_confidence(base: int, growth_dir: str, credit_dir: str) -> int:
    """信用方向对 confidence 的修正(不改 quadrant,五象限语义保持)。

    信用是 GDP 的领先指标:
    - 同向(信用+GDP 都扩张 or 都放缓):confidence +10(确认趋势)
    - 反向(信用拐头 vs GDP 当下):confidence -10(拐点预警,GDP 可能跟随信用转向)
    - credit_dir='unknown':不修正
    """
    if credit_dir == "unknown":
        return base
    if (credit_dir == "expansion" and growth_dir == "expansion") or \
       (credit_dir == "slowdown" and growth_dir == "slowdown"):
        delta = 10
    elif (credit_dir == "expansion" and growth_dir == "slowdown") or \
         (credit_dir == "slowdown" and growth_dir == "expansion"):
        delta = -10
    else:
        delta = 0  # growth_dir='unknown' 时信用不足以强改
    return max(20, min(95, base + delta))


def _judge_from_series(
    gdp_values: list[float],
    cpi_values: list[float],
    market: str,
    credit_series: dict | None = None,
) -> dict:
    """从原始 GDP 绝对值 + CPI 同比序列判定象限(纯函数,不读 DB)。

    CN 额外读 credit_series(M2_YOY + SOCIAL_FIN)作 growth 前置确认:
    仅修正 confidence + 暴露 credit_axis 字段,不改 quadrant(避免破坏五象限语义)。
    US 不传 credit_series(无合适序列)。
    """
    period = _GDP_PERIOD.get(market, GDP_PERIOD_CN)
    gdp_window = _GDP_WINDOW.get(market, VOTE_WINDOW_MONTHLY)
    gdp_yoy = _yoy_from_absolute(gdp_values, period)
    gdp_dir_raw = _direction_vote(gdp_yoy, gdp_window, DIRECTION_VOTE_MIN_AGREEING)
    growth_dir = {"up": "expansion", "down": "slowdown"}.get(gdp_dir_raw, "unknown")

    inflation_dir = _direction_vote(cpi_values, VOTE_WINDOW_MONTHLY, DIRECTION_VOTE_MIN_AGREEING)
    cpi_latest = cpi_values[-1] if cpi_values else None

    quadrant = _classify(growth_dir, inflation_dir, cpi_latest)
    confidence = _confidence(growth_dir, inflation_dir, quadrant)

    # CN 信用轴(M2 + 社融):growth 的领先指标,仅调 confidence(不改象限)
    credit_dir = "unknown"
    if market == "cn" and credit_series:
        credit_dir = _credit_direction(
            credit_series, CREDIT_PERIOD_CN, VOTE_WINDOW_MONTHLY, DIRECTION_VOTE_MIN_AGREEING,
        )
        confidence = _apply_credit_confidence(confidence, growth_dir, credit_dir)

    indicators = {}
    if gdp_yoy:
        indicators["GDP_YOY"] = gdp_yoy[-1]
    if cpi_values:
        indicators["CPI_LATEST"] = cpi_latest
    if credit_dir != "unknown":
        # 暴露信用末值,让 Claude 看到具体 M2/社融 而非只看 credit_axis 标签
        for ind, vals in (credit_series or {}).items():
            if vals:
                indicators[ind] = vals[-1]

    return {
        "quadrant": quadrant,
        "confidence": confidence,
        "growth_axis": _GROWTH_LABEL.get(growth_dir, "未知"),
        "inflation_axis": _INFLATION_LABEL.get(inflation_dir, "未知"),
        "credit_axis": _CREDIT_LABEL.get(credit_dir, "未知") if market == "cn" else None,
        "indicators": indicators,
    }


class RegimeEngine:
    """经济环境四象限判定引擎。

    data_source 须实现 query(sql, params) → DataFrame(复用 BaseData)。
    judge() 取 GDP/CPI 序列 → 纯函数判定 → 切换确认(去噪层 3)。
    """

    def __init__(self, data_source):
        self.data = data_source

    def judge(self, market: str) -> dict:
        gdp_values = self._fetch_series(GROWTH_INDICATOR, market)
        cpi_values = self._fetch_series(INFLATION_INDICATOR, market)

        # CN 额外读信用序列(M2_YOY + SOCIAL_FIN)作 growth 前置确认;US 不读
        credit_series = None
        if market == "cn":
            collected = {}
            for ind in CREDIT_INDICATORS_CN:
                vals = self._fetch_series(ind, "cn")
                if vals:
                    collected[ind] = vals
            if collected:
                credit_series = collected

        result = _judge_from_series(gdp_values, cpi_values, market, credit_series)

        # 去噪层 3:切换确认期(无状态回看,按 market 数据频率选 RUNS)
        # CN 季度 GDP 稀疏 → RUNS=1(不回看);US 月度密 → RUNS=2(去 1 期重判)
        # 注:回看只重判 quadrant,credit 不影响象限 → credit_series=None 传入(语义更纯)
        runs = _SWITCH_RUNS.get(market, SWITCH_CONFIRMATION_RUNS_US)
        lookback = runs - 1
        if (lookback > 0 and result["quadrant"] != "中性"
                and len(gdp_values) > lookback and len(cpi_values) > lookback):
            prev = _judge_from_series(gdp_values[:-lookback], cpi_values[:-lookback], market)
            if prev["quadrant"] != result["quadrant"]:
                result["quadrant"] = "中性"
                result["confidence"] = 30

        result["market"] = market
        return result

    def _fetch_series(self, indicator: str, country: str) -> list[float]:
        """从 macro_data 取某 (indicator, country) 的全部值序列(按日期升序)。"""
        try:
            df = self.data.query(
                "SELECT value FROM macro_data WHERE indicator=? AND country=? "
                "AND value IS NOT NULL ORDER BY date",
                (indicator, country),
            )
        except Exception as e:
            logger.warning(f"Regime fetch {indicator}/{country} failed: {e}")
            return []
        if df.empty:
            return []
        return [float(v) for v in df["value"].tolist() if v is not None]
