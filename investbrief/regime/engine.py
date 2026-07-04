"""经济环境四象限判定引擎(Browne 增长×通胀)。

模块级纯函数(_yoy_from_absolute / _direction_vote / _classify / _confidence /
_judge_from_series)不依赖 DB,可独立单测。RegimeEngine 类负责取数 + 切换确认(见 Task 3)。
"""
import logging

from investbrief.regime.config import (
    INFLATION_UP_THRESHOLD, DIRECTION_VOTE_MIN_AGREEING,
    VOTE_WINDOW_MONTHLY, VOTE_WINDOW_QUARTERLY,
    GDP_PERIOD_CN, GDP_PERIOD_US,
)

logger = logging.getLogger(__name__)

_GDP_PERIOD = {"cn": GDP_PERIOD_CN, "us": GDP_PERIOD_US}
_GDP_WINDOW = {"cn": VOTE_WINDOW_QUARTERLY, "us": VOTE_WINDOW_MONTHLY}

_GROWTH_LABEL = {"expansion": "扩张", "slowdown": "放缓", "unknown": "未知"}
_INFLATION_LABEL = {"up": "上行", "down": "下行", "unknown": "未知"}


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


def _judge_from_series(gdp_values: list[float], cpi_values: list[float], market: str) -> dict:
    """从原始 GDP 绝对值 + CPI 同比序列判定象限(纯函数,不读 DB)。"""
    period = _GDP_PERIOD.get(market, GDP_PERIOD_CN)
    gdp_window = _GDP_WINDOW.get(market, VOTE_WINDOW_MONTHLY)
    gdp_yoy = _yoy_from_absolute(gdp_values, period)
    gdp_dir_raw = _direction_vote(gdp_yoy, gdp_window, DIRECTION_VOTE_MIN_AGREEING)
    growth_dir = {"up": "expansion", "down": "slowdown"}.get(gdp_dir_raw, "unknown")

    inflation_dir = _direction_vote(cpi_values, VOTE_WINDOW_MONTHLY, DIRECTION_VOTE_MIN_AGREEING)
    cpi_latest = cpi_values[-1] if cpi_values else None

    quadrant = _classify(growth_dir, inflation_dir, cpi_latest)
    confidence = _confidence(growth_dir, inflation_dir, quadrant)

    indicators = {}
    if gdp_yoy:
        indicators["GDP_YOY"] = gdp_yoy[-1]
    if cpi_values:
        indicators["CPI_LATEST"] = cpi_latest

    return {
        "quadrant": quadrant,
        "confidence": confidence,
        "growth_axis": _GROWTH_LABEL.get(growth_dir, "未知"),
        "inflation_axis": _INFLATION_LABEL.get(inflation_dir, "未知"),
        "indicators": indicators,
    }
