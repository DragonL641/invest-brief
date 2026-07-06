"""市场无关的打分纯函数。

从 risk/calc_utils.py 与 risk/indicators/base.py 提炼。
任何改动都会导致 risk 分数漂移 — 仅在确认等价后修改。

零回归约束: 本模块的 percentile_rank / normalize_score / safe_divide /
moving_average / exponential_moving_average / calculate_macd / consecutive_count
逐字等价于 risk/calc_utils.py 现有实现; score_by_percentile 逐字等价于
risk/indicators/base.py:BaseIndicator._score_by_percentile。
Task 4 会把 risk/ 改为从本模块 import, 届时删除 risk/calc_utils.py。
"""
import pandas as pd


def moving_average(series: pd.Series, window: int) -> pd.Series:
    """Simple moving average."""
    return series.rolling(window=window, min_periods=window).mean()


def exponential_moving_average(series: pd.Series, span: int) -> pd.Series:
    """Exponential moving average."""
    return series.ewm(span=span, adjust=False).mean()


def calculate_macd(
    series: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Calculate MACD indicator.

    Returns: (macd_line, signal_line, histogram)
    """
    ema_fast = exponential_moving_average(series, fast)
    ema_slow = exponential_moving_average(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = exponential_moving_average(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def percentile_rank(value: float, series: pd.Series) -> float:
    """Calculate percentile rank of value within series (0-100)."""
    if len(series) == 0:
        return 50.0
    return float((series < value).sum() / len(series) * 100)


def normalize_score(
    value: float,
    low_threshold: float,
    high_threshold: float,
    invert: bool = False,
) -> float:
    """Normalize a value to 0-10 risk score using linear interpolation.

    Args:
        value: The raw metric value
        low_threshold: Below this, score = 0 (or 10 if invert)
        high_threshold: At or above this, score = 10 (or 0 if invert)
        invert: If True, higher raw values = lower risk scores

    Returns:
        Risk score from 0.0 to 10.0
    """
    if invert:
        # Higher value = lower risk (e.g., equity-bond ratio)
        if value >= low_threshold:
            return 0.0
        if value <= high_threshold:
            return 10.0
        score = (low_threshold - value) / (low_threshold - high_threshold) * 10.0
    else:
        # Higher value = higher risk (e.g., PE, CPI)
        if value <= low_threshold:
            return 0.0
        if value >= high_threshold:
            return 10.0
        score = (value - low_threshold) / (high_threshold - low_threshold) * 10.0

    return round(max(0.0, min(10.0, score)), 2)


def consecutive_count(series: pd.Series, condition_fn) -> int:
    """Count consecutive items from the end of series matching condition.

    Args:
        series: pandas Series
        condition_fn: function that takes a value and returns bool

    Returns:
        Count of consecutive matching items from the end
    """
    count = 0
    for val in reversed(series.values):
        if condition_fn(val):
            count += 1
        else:
            break
    return count


def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Safe division that returns default on zero denominator."""
    if denominator == 0 or pd.isna(denominator) or pd.isna(numerator):
        return default
    return numerator / denominator


def score_by_percentile(value, history, invert: bool = False, min_samples: int = 100):
    """分位数打分: value 在 history 序列中的分位 -> 0-10 score。

    正常指标: 分位越高=风险越高=score越高(分位85% -> 8.5)。
    invert指标(低值=高风险, 如股债比): 分位越低=score越高。
    value None / history 空 / 样本<min_samples -> None(调用方回退固定阈值)。
    注: 全样本分位继承平稳性假设(见 docs/methodology.html「分位数的陷阱」);
        样本不足时返回None让调用方回退固定阈值, 避免少量历史点导致分位失真。

    逐字等价于 risk/indicators/base.py:BaseIndicator._score_by_percentile。
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
