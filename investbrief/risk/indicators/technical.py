"""Technical indicators: 50MA deviation, Volume shrinkage."""

from investbrief.risk.indicators.base import BaseIndicator
from investbrief.risk.calc_utils import moving_average, safe_divide
import logging

logger = logging.getLogger(__name__)


class TechnicalIndicator(BaseIndicator):
    """Calculates technical risk indicators."""

    def calculate(self, market: str, date: str | None = None) -> dict:
        results = {}
        results["ma50_deviation"] = self._ma50_deviation(market, date)
        results["volume_shrinkage"] = self._volume_shrinkage(market, date)
        return results

    def _ma50_deviation(self, market: str, date: str | None = None) -> dict:
        """(Close - MA50) / MA50."""
        try:
            df = self._get_index_data(market, 60, date)
            if len(df) < 50:
                return {"score": 5.0, "value": None, "percentile": None}

            close = df["close"].astype(float)
            ma50 = moving_average(close, 50)
            current_close = float(close.iloc[-1])
            current_ma50 = float(ma50.iloc[-1])

            deviation = safe_divide(current_close - current_ma50, current_ma50)
            score = self._score(deviation, "ma50_deviation", market)

            return {"score": score, "value": deviation, "percentile": None}
        except Exception as e:
            logger.error(f"Failed to calculate MA50 deviation: {e}")
            return {"score": 5.0, "value": None, "percentile": None}

    def _volume_shrinkage(self, market: str, date: str | None = None) -> dict:
        """5-day avg volume / 30-day avg volume (when index near highs)."""
        try:
            df = self._get_index_data(market, 40, date)
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
                config = self._get_config("volume_shrinkage", market)
                threshold = config.get("thresholds", {}).get(market, 0.7)
                invert = config.get("invert", True)
                from investbrief.risk.calc_utils import normalize_score
                score = normalize_score(ratio, threshold * 1.5, threshold, invert=True)
            else:
                score = 0.0  # Not near highs, no volume risk signal

            return {"score": score, "value": ratio, "percentile": None}
        except Exception as e:
            logger.error(f"Failed to calculate volume shrinkage: {e}")
            return {"score": 5.0, "value": None, "percentile": None}
