"""共享 indicator 基础设施: 取数 helper + cn/us 共享的技术指标。

market/<mkt>/indicators.py 的专属 indicator 与本模块的 TechnicalIndicator
都不 import risk —— config 由 pipeline 注入, 算法调 core.scoring。

TechnicalIndicator._ma50_deviation / _volume_shrinkage 逐字搬迁自
risk/indicators/technical.py, 仅适配 4 处依赖:
  1. self.data                            -> data_source 参数
  2. self._get_index_data(market, days, date) -> get_index_series(data_source, self._market, days, date)
  3. self._score_by_percentile(v, hist)   -> score_by_percentile(v, hist)  (本两方法未用到)
  4. self._score(v, name, market)         -> score_with_config(v, name, self._market, self._config)
计算逻辑(均线窗口/分位样本/缩量阈值)与 technical.py 逐字一致, 勿改算法。
"""
import logging

import pandas as pd

from investbrief.core.scoring import moving_average, normalize_score, safe_divide

logger = logging.getLogger(__name__)


def get_index_series(data_source, market: str, days: int = 100, date: str | None = None) -> pd.DataFrame:
    """取该市场主指数日序列(读 market_index_spec, 不依赖 data_source 属于哪个市场)。

    等价于 risk/indicators/base.py:BaseIndicator._get_index_data。
    """
    from investbrief.data import market_index_spec
    spec = market_index_spec(market)
    if spec["kind"] == "macro":
        base = (f"SELECT date, value AS close FROM macro_data "
                f"WHERE indicator='{spec['indicator']}' AND country='{spec['country']}' AND value IS NOT NULL")
        if date:
            return data_source.query(base + " AND date <= ? ORDER BY date DESC LIMIT ?",
                                     (date, days)).iloc[::-1]
        return data_source.query(base + " ORDER BY date DESC LIMIT ?", (days,)).iloc[::-1]
    table, code = spec["table"], spec["code"]
    if date:
        return data_source.query(
            f"SELECT * FROM {table} WHERE code = ? AND date <= ? ORDER BY date DESC LIMIT ?",
            (code, date, days)).iloc[::-1]
    return data_source.query(
        f"SELECT * FROM {table} WHERE code = ? ORDER BY date DESC LIMIT ?", (code, days)).iloc[::-1]


def score_with_config(value, name: str, market: str, config: dict):
    """按 indicator config 打分(等价于原 base.py BaseIndicator._score)。"""
    cfg = config.get(name, {})
    threshold = cfg.get("thresholds", {}).get(market, 0)
    low = cfg.get("low_thresholds", {}).get(market, 0)
    invert = cfg.get("invert", False)
    if invert:
        return normalize_score(value, threshold, threshold * 0.5, invert=True)
    return normalize_score(value, low, threshold)


class TechnicalIndicator:
    """cn/us 共享的技术指标(ma50_deviation, volume_shrinkage)。

    从 risk/indicators/technical.py 搬迁: _ma50_deviation + _volume_shrinkage
    方法体逐字保留, 仅适配取数与打分依赖。
    """

    def __init__(self, market: str, config: dict):
        self._market = market
        self._config = config

    def calculate(self, data_source, date: str | None = None) -> dict:
        results = {}
        results["ma50_deviation"] = self._ma50_deviation(data_source, date)
        results["volume_shrinkage"] = self._volume_shrinkage(data_source, date)
        return results

    def _ma50_deviation(self, data_source, date: str | None = None) -> dict:
        """(Close - MA50) / MA50。搬迁自 risk/indicators/technical.py:_ma50_deviation。"""
        try:
            df = get_index_series(data_source, self._market, 60, date)
            if len(df) < 50:
                return {"score": 5.0, "value": None, "percentile": None}

            close = df["close"].astype(float)
            ma50 = moving_average(close, 50)
            current_close = float(close.iloc[-1])
            current_ma50 = float(ma50.iloc[-1])

            deviation = safe_divide(current_close - current_ma50, current_ma50)
            score = score_with_config(deviation, "ma50_deviation", self._market, self._config)

            return {"score": score, "value": deviation, "percentile": None}
        except Exception as e:
            logger.error(f"Failed to calculate MA50 deviation: {e}")
            return {"score": 5.0, "value": None, "percentile": None}

    def _volume_shrinkage(self, data_source, date: str | None = None) -> dict:
        """5-day avg volume / 30-day avg volume (when index near highs)。

        搬迁自 risk/indicators/technical.py:_volume_shrinkage。
        """
        try:
            df = get_index_series(data_source, self._market, 40, date)
            if len(df) < 30:
                return {"score": 5.0, "value": None, "percentile": None}

            volume = df["volume"].astype(float)
            close = df["close"].astype(float)

            ma5_vol = moving_average(volume, 5)
            ma30_vol = moving_average(volume, 30)

            ratio = safe_divide(float(ma5_vol.iloc[-1]), float(ma30_vol.iloc[-1]))

            # Only score if index is near recent high (within 5% of 30-day high)
            high_30 = float(close.iloc[-30:].max())
            current = float(close.iloc[-1])
            near_high = current >= high_30 * 0.95

            if near_high:
                config = self._config.get("volume_shrinkage", {})
                threshold = config.get("thresholds", {}).get(self._market, 0.7)
                invert = config.get("invert", True)
                score = normalize_score(ratio, threshold * 1.5, threshold, invert=invert)
            else:
                score = 0.0  # Not near highs, no volume risk signal

            return {"score": score, "value": ratio, "percentile": None}
        except Exception as e:
            logger.error(f"Failed to calculate volume shrinkage: {e}")
            return {"score": 5.0, "value": None, "percentile": None}
