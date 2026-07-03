"""Common calculation utilities."""

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
