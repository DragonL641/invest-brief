"""Liquidity indicators: margin, northbound, pledge (CN); credit spread (US)."""

from investbrief.risk.indicators.base import BaseIndicator
import logging

logger = logging.getLogger(__name__)


class LiquidityIndicator(BaseIndicator):
    """Calculates liquidity risk indicators."""

    def calculate(self, market: str, date: str | None = None) -> dict:
        results = {}
        if market == "cn":
            results["margin_growth"] = self._margin_growth(date)
            results["margin_level"] = self._margin_level(date)
        else:
            results["credit_spread"] = self._credit_spread(date)
        return results

    def _margin_growth(self, date: str | None = None) -> dict:
        """4周(20交易日)融资余额增速 = 杠杆加速度. 高增速=亢奋加杠杆=高风险.

        改自 margin_balance_ratio(占比): 避开 total_market_cap 历史稀疏(332点)的
        scaling坑, 改用增速(天然归一化), 且更贴合"杠杆加速冲顶比绝对高位更危险"。
        """
        try:
            from datetime import datetime, timedelta
            ref = date or datetime.now().strftime('%Y-%m-%d')
            start_10y = (datetime.strptime(ref, '%Y-%m-%d') - timedelta(days=3650)).strftime('%Y-%m-%d')
            if date:
                hist = self.data.query(
                    f"SELECT margin_balance FROM sentiment_data WHERE market='cn' "
                    f"AND margin_balance IS NOT NULL AND date >= '{start_10y}' AND date <= ? ORDER BY date",
                    (date,),
                )
            else:
                hist = self.data.query(
                    f"SELECT margin_balance FROM sentiment_data WHERE market='cn' "
                    f"AND margin_balance IS NOT NULL AND date >= '{start_10y}' ORDER BY date"
                )
            if hist.empty or len(hist) < 40:
                return {"score": 5.0, "value": None, "percentile": None}
            mb = hist["margin_balance"].astype(float).tolist()
            growths = [(mb[i] - mb[i - 20]) / mb[i - 20] for i in range(20, len(mb)) if mb[i - 20] > 0]
            if len(growths) < 100:
                return {"score": 5.0, "value": None, "percentile": None}
            cur = growths[-1]
            score = self._score_by_percentile(cur, growths)  # 增速高=高分(正常方向,不invert)
            if score is None:
                score = self._score(cur, "margin_growth", "cn")
                scoring = f"固定阈值(样本{len(growths)}不足)"
            else:
                scoring = f"近10年分位({len(growths)}点)"
            import numpy as np
            pct = float((np.array(growths) < cur).mean() * 100)
            return {"score": score, "value": round(cur * 100, 1), "percentile": round(pct, 0), "scoring": scoring}
        except Exception as e:
            logger.error(f"Failed to calculate margin growth: {e}")
            return {"score": 5.0, "value": None, "percentile": None}

    def _margin_level(self, date: str | None = None) -> dict:
        """融资余额绝对值的历史分位(杠杆水平). 高=杠杆重=高风险.

        与 margin_growth 互补: 增速管杠杆加速度(2015散户杠杆牛),
        水平管杠杆高位(2021机构抱团, 融资没加速但水平高)。
        绝对值口径避开 total_market_cap 历史稀疏的 scaling 坑。
        """
        try:
            from datetime import datetime, timedelta
            ref = date or datetime.now().strftime('%Y-%m-%d')
            start_10y = (datetime.strptime(ref, '%Y-%m-%d') - timedelta(days=3650)).strftime('%Y-%m-%d')
            if date:
                hist = self.data.query(
                    f"SELECT margin_balance FROM sentiment_data WHERE market='cn' "
                    f"AND margin_balance IS NOT NULL AND date >= '{start_10y}' AND date <= ? ORDER BY date",
                    (date,),
                )
            else:
                hist = self.data.query(
                    f"SELECT margin_balance FROM sentiment_data WHERE market='cn' "
                    f"AND margin_balance IS NOT NULL AND date >= '{start_10y}' ORDER BY date"
                )
            if hist.empty or len(hist) < 100:
                return {"score": 5.0, "value": None, "percentile": None}
            vals = hist["margin_balance"].astype(float).tolist()
            cur = vals[-1]
            score = self._score_by_percentile(cur, vals)  # 高=高分
            if score is None:
                score = self._score(cur, "margin_level", "cn")
                scoring = f"固定阈值(样本{len(vals)}不足)"
            else:
                scoring = f"近10年分位({len(vals)}点)"
            import numpy as np
            pct = float((np.array(vals) < cur).mean() * 100)
            return {"score": score, "value": round(cur, 0), "percentile": round(pct, 0), "scoring": scoring}
        except Exception as e:
            logger.error(f"Failed to calculate margin level: {e}")
            return {"score": 5.0, "value": None, "percentile": None}

    def _pledge_ratio(self, date: str | None = None) -> dict:
        """Market-wide average share pledge ratio (历史分位打分)."""
        try:
            if date:
                hist = self.data.query(
                    "SELECT pledge_ratio FROM sentiment_data WHERE market='cn' "
                    "AND pledge_ratio IS NOT NULL AND date <= ? ORDER BY date",
                    (date,),
                )
            else:
                hist = self.data.query(
                    "SELECT pledge_ratio FROM sentiment_data WHERE market='cn' "
                    "AND pledge_ratio IS NOT NULL ORDER BY date"
                )
            if hist.empty:
                return {"score": 5.0, "value": None, "percentile": None}

            # Handle percentage format (>1 当作百分数, 整序列统一转换)
            vals = [v / 100.0 if v > 1 else v for v in hist["pledge_ratio"].astype(float).tolist()]
            ratio = vals[-1]
            score = self._score_by_percentile(ratio, vals)
            if score is None:
                score = self._score(ratio, "pledge_ratio", "cn")  # 样本不足回退
                scoring = f"固定阈值(样本{len(vals)}不足)"
            else:
                scoring = f"近10年分位({len(vals)}点)"
            return {"score": score, "value": ratio, "percentile": round(score * 10, 0), "scoring": scoring}
        except Exception as e:
            logger.error(f"Failed to calculate pledge ratio: {e}")
            return {"score": 5.0, "value": None, "percentile": None}

    def _credit_spread(self, date: str | None = None) -> dict:
        """HYG相对国债的30日偏离代理(信用利差代理). 扩大=资金逃风险=高风险(正常方向).

        历史10年序列分位打分; 样本不足回退固定阈值(percentile=None, 避免假50%).
        """
        try:
            from datetime import datetime, timedelta
            import numpy as np
            ref = date or datetime.now().strftime('%Y-%m-%d')
            start_10y = (datetime.strptime(ref, '%Y-%m-%d') - timedelta(days=3650)).strftime('%Y-%m-%d')
            if date:
                hist = self.data.query(
                    f"SELECT credit_spread FROM sentiment_data WHERE market='us' "
                    f"AND credit_spread IS NOT NULL AND date >= '{start_10y}' AND date <= ? ORDER BY date",
                    (date,),
                )
            else:
                hist = self.data.query(
                    f"SELECT credit_spread FROM sentiment_data WHERE market='us' "
                    f"AND credit_spread IS NOT NULL AND date >= '{start_10y}' ORDER BY date"
                )
            if hist.empty or len(hist) < 100:
                return {"score": 5.0, "value": None, "percentile": None, "scoring": "固定阈值(样本不足)"}
            vals = hist["credit_spread"].astype(float).tolist()
            cur = vals[-1]
            score = self._score_by_percentile(cur, vals)  # 扩大=高风险,正常方向
            if score is None:
                score = self._score(cur, "credit_spread", "us")
                scoring = f"固定阈值(样本{len(vals)}不足)"
            else:
                scoring = f"近10年分位({len(vals)}点)"
            pct = float((np.array(vals) < cur).mean() * 100)
            return {"score": score, "value": round(cur, 4), "percentile": round(pct, 0), "scoring": scoring}
        except Exception as e:
            logger.error(f"Failed to calculate credit spread: {e}")
            return {"score": 5.0, "value": None, "percentile": None}
