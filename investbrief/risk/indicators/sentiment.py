"""Sentiment indicators: market breadth, new accounts (CN); VIX (US)."""

from investbrief.risk.indicators.base import BaseIndicator
import logging

logger = logging.getLogger(__name__)


class SentimentIndicator(BaseIndicator):
    """Calculates sentiment risk indicators."""

    def calculate(self, market: str, date: str | None = None) -> dict:
        results = {}
        # cn: new_account_growth 已移除(数据源滞后2023-08); market_breadth 早前已移除
        if market == "us":
            results["vix"] = self._vix(date)
        return results

    def _market_breadth(self, market: str, date: str | None = None) -> dict:
        """Up stocks / total stocks ratio."""
        try:
            if market == "cn":
                if date:
                    df = self.data.query(
                        "SELECT market_breadth FROM sentiment_data WHERE market='cn' "
                        "AND market_breadth IS NOT NULL AND date <= ? ORDER BY date DESC LIMIT 1",
                        (date,),
                    )
                else:
                    df = self.data.query(
                        "SELECT market_breadth FROM sentiment_data WHERE market='cn' "
                        "AND market_breadth IS NOT NULL ORDER BY date DESC LIMIT 1"
                    )
                if df.empty:
                    return {"score": 5.0, "value": None, "percentile": None}

                breadth = float(df.iloc[0]["market_breadth"])
                score = self._score(breadth, "market_breadth", "cn")
                return {"score": score, "value": breadth, "percentile": None}
            else:
                # US: read from sentiment_data
                if date:
                    df = self.data.query(
                        "SELECT market_breadth FROM sentiment_data WHERE market='us' "
                        "AND market_breadth IS NOT NULL AND date <= ? ORDER BY date DESC LIMIT 1",
                        (date,),
                    )
                else:
                    df = self.data.query(
                        "SELECT market_breadth FROM sentiment_data WHERE market='us' "
                        "AND market_breadth IS NOT NULL ORDER BY date DESC LIMIT 1"
                    )
                if df.empty:
                    return {"score": 5.0, "value": None, "percentile": None}

                breadth = float(df.iloc[0]["market_breadth"])
                score = self._score(breadth, "market_breadth", "us")
                return {"score": score, "value": breadth, "percentile": None}
        except Exception as e:
            logger.error(f"Failed to calculate market breadth: {e}")
            return {"score": 5.0, "value": None, "percentile": None}

    def _vix(self, date: str | None = None) -> dict:
        """VIX收盘值的近10年分位. 高位=市场恐慌(模型计为高风险, 与_score同向).

        样本不足回退固定阈值(percentile=None).
        """
        try:
            from datetime import datetime, timedelta
            import numpy as np
            ref = date or datetime.now().strftime('%Y-%m-%d')
            start_10y = (datetime.strptime(ref, '%Y-%m-%d') - timedelta(days=3650)).strftime('%Y-%m-%d')
            if date:
                hist = self.data.query(
                    f"SELECT vix FROM sentiment_data WHERE market='us' "
                    f"AND vix IS NOT NULL AND date >= '{start_10y}' AND date <= ? ORDER BY date",
                    (date,),
                )
            else:
                hist = self.data.query(
                    f"SELECT vix FROM sentiment_data WHERE market='us' "
                    f"AND vix IS NOT NULL AND date >= '{start_10y}' ORDER BY date"
                )
            if hist.empty or len(hist) < 100:
                return {"score": 5.0, "value": None, "percentile": None, "scoring": "固定阈值(样本不足)"}
            vals = hist["vix"].astype(float).tolist()
            cur = vals[-1]
            score = self._score_by_percentile(cur, vals)  # VIX高位=高分
            if score is None:
                score = self._score(cur, "vix", "us")
                scoring = f"固定阈值(样本{len(vals)}不足)"
            else:
                scoring = f"近10年分位({len(vals)}点)"
            pct = float((np.array(vals) < cur).mean() * 100)
            return {"score": score, "value": round(cur, 2), "percentile": round(pct, 0), "scoring": scoring}
        except Exception as e:
            logger.error(f"Failed to calculate VIX: {e}")
            return {"score": 5.0, "value": None, "percentile": None}
