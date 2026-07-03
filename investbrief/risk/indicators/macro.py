"""Macro indicators: CPI, yield curve inversion."""

from investbrief.risk.indicators.base import BaseIndicator
import logging

logger = logging.getLogger(__name__)


class MacroIndicator(BaseIndicator):
    """Calculates macro fundamental risk indicators."""

    def calculate(self, market: str, date: str | None = None) -> dict:
        results = {}
        if market == "us":
            results["yield_curve_inversion"] = self._yield_curve_inversion(date)
        return results

    def _cpi(self, market: str, date: str | None = None) -> dict:
        """CPI year-over-year inflation rate (历史分位打分)."""
        try:
            country = "cn" if market == "cn" else "us"
            if date:
                hist = self.data.query(
                    "SELECT value FROM macro_data WHERE indicator='CPI' AND country=? "
                    "AND date <= ? ORDER BY date",
                    (country, date),
                )
            else:
                hist = self.data.query(
                    "SELECT value FROM macro_data WHERE indicator='CPI' AND country=? "
                    "ORDER BY date",
                    (country,),
                )
            if hist.empty:
                return {"score": 5.0, "value": None, "percentile": None}

            cpi = float(hist.iloc[-1]["value"])
            sample = hist["value"].tolist()
            score = self._score_by_percentile(cpi, sample)
            if score is None:
                score = self._score(cpi, "cpi", market)  # 样本不足回退固定阈值
                scoring = f"固定阈值(样本{len(sample)}不足)"
            else:
                scoring = f"历史分位({len(sample)}点)"
            return {"score": score, "value": cpi, "percentile": round(score * 10, 0), "scoring": scoring}
        except Exception as e:
            logger.error(f"Failed to calculate CPI: {e}")
            return {"score": 5.0, "value": None, "percentile": None}

    def _yield_curve_inversion(self, date: str | None = None) -> dict:
        """10Y - 3M treasury yield spread. Negative = inverted = recession signal."""
        try:
            # Get 10Y and 3M yields
            tnx_df = self.data.query(
                "SELECT date, close FROM us_index_daily WHERE code='^TNX' "
                "ORDER BY date DESC LIMIT 60"
            )
            irx_df = self.data.query(
                "SELECT date, close FROM us_index_daily WHERE code='^IRX' "
                "ORDER BY date DESC LIMIT 60"
            )
            if tnx_df.empty or irx_df.empty:
                return {"score": 5.0, "value": None, "percentile": None}

            # Get current spread
            current_10y = float(tnx_df.iloc[0]["close"])
            current_3m = float(irx_df.iloc[0]["close"])
            current_spread = current_10y - current_3m

            # Check if inverted (spread < 0)
            if current_spread >= 0:
                # Not inverted - low risk
                return {"score": 0.0, "value": current_spread, "percentile": None}

            # Inverted - calculate severity
            # More negative = higher risk
            config = self._get_config("yield_curve_inversion", "us")
            threshold = config.get("thresholds", {}).get("us", 0.5)
            # Score based on how negative the spread is
            # -0.5 (50bp inversion) = threshold for high risk
            severity = abs(current_spread)
            from investbrief.risk.calc_utils import normalize_score
            score = normalize_score(severity, 0.0, threshold)

            return {"score": score, "value": current_spread, "percentile": None}
        except Exception as e:
            logger.error(f"Failed to calculate yield curve inversion: {e}")
            return {"score": 5.0, "value": None, "percentile": None}
