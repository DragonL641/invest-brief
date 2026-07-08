"""US 市场专属 risk indicator + 工厂。

从 risk/indicators/{valuation,liquidity,sentiment,macro}.py 搬迁 us 方法体
(逐字保留, 仅适配依赖)。不 import risk —— config 由 pipeline 注入, 算法调 core。

迁移范式(适用于所有搬迁方法):
  1. self.data                          -> data_source 参数
  2. self._score_by_percentile(v, hist) -> score_by_percentile(v, hist)  (core.scoring)
  3. self._score(v, name, market)       -> score_with_config(v, name, self._market, self._config)
                                              (core.indicators)
  4. self._get_config(name, market)     -> self._config.get(name, {})
  5. self._index_pe(market, date)       -> self._pe_us(data_source, date)  (内部互调)
注: 本 5 方法均用裸 SQL 取数, 不经过 _get_index_data, 故 get_index_series 未使用。
"""
import logging

from investbrief.core.scoring import score_by_percentile, normalize_score
from investbrief.core.indicators import (
    score_with_config, TechnicalIndicator, percentile_score_from_series,
)

logger = logging.getLogger(__name__)


class UsValuationIndicator:
    """US 估值: index_pe / sp500_erp。

    _pe_us / _sp500_erp 方法体逐字搬迁自 risk/indicators/valuation.py,
    仅适配取数与打分依赖。_buffett_us 不搬(calculate 从未调用, 死代码, 丢弃)。
    """

    def __init__(self, config: dict):
        self._market = "us"
        self._config = config

    def calculate(self, data_source, date: str | None = None) -> dict:
        results = {}
        results["index_pe"] = self._pe_us(data_source, date)
        results["sp500_erp"] = self._sp500_erp(data_source, date)
        return results

    def _pe_us(self, data_source, date: str | None = None) -> dict:
        # 当前值=最新pe_ratio(SPY当天优先, date更大); 分位样本=纯Shiller月度(length(date)=7).
        # SPY当天点不入分位 -> 分位完全由Shiller一次性历史决定, 不依赖SPY逐日积累.
        if date:
            latest = data_source.query(
                "SELECT pe_ratio FROM sentiment_data WHERE market='us' "
                "AND pe_ratio IS NOT NULL AND date <= ? ORDER BY date DESC LIMIT 1",
                (date,),
            )
            samp = data_source.query(
                "SELECT pe_ratio FROM sentiment_data WHERE market='us' "
                "AND pe_ratio IS NOT NULL AND length(date)=7 AND date <= ? ORDER BY date",
                (date,),
            )
        else:
            latest = data_source.query(
                "SELECT pe_ratio FROM sentiment_data WHERE market='us' "
                "AND pe_ratio IS NOT NULL ORDER BY date DESC LIMIT 1"
            )
            samp = data_source.query(
                "SELECT pe_ratio FROM sentiment_data WHERE market='us' "
                "AND pe_ratio IS NOT NULL AND length(date)=7 ORDER BY date"
            )
        if latest.empty:
            return {"score": 5.0, "value": None, "percentile": None}

        pe = float(latest.iloc[0]["pe_ratio"])
        sample = samp["pe_ratio"].tolist()
        score = score_by_percentile(pe, sample)
        if score is None:
            score = score_with_config(pe, "index_pe", self._market, self._config)  # 样本不足回退固定阈值
            scoring = f"固定阈值(样本{len(sample)}不足)"
            pct = None
        else:
            scoring = f"全历史分位({len(sample)}点)"
            import numpy as np
            pct = round(float((np.array(sample) < pe).mean() * 100), 0)
        return {"score": score, "value": pe, "percentile": pct, "scoring": scoring}

    def _sp500_erp(self, data_source, date: str | None = None) -> dict:
        """标普500 ERP = 1/PE - 10Y国债(差值法, 与A股ERP完全同一口径). 高ERP=股便宜=低风险.

        当前值: SPY当天PE - ^TNX当天; 分位样本: Shiller月度PE配^TNX月末的全历史ERP.
        """
        import numpy as np
        try:
            pe_now = self._pe_us(data_source, date)["value"]
            if date:
                tnx_df = data_source.query(
                    "SELECT close FROM us_index_daily WHERE code='^TNX' AND date <= ? "
                    "ORDER BY date DESC LIMIT 1", (date,)
                )
            else:
                tnx_df = data_source.query(
                    "SELECT close FROM us_index_daily WHERE code='^TNX' "
                    "ORDER BY date DESC LIMIT 1"
                )
            if pe_now is None or pe_now <= 0 or tnx_df.empty:
                return {"score": 5.0, "value": None, "percentile": None}
            cur_erp = 1.0 / float(pe_now) - float(tnx_df.iloc[0]["close"]) / 100.0

            # 分位样本: Shiller月度PE(length(date)=7) 配 ^TNX月末, 按YYYY-MM对齐
            pe_hist = data_source.query(
                "SELECT date, pe_ratio FROM sentiment_data WHERE market='us' "
                "AND pe_ratio IS NOT NULL AND length(date)=7 ORDER BY date"
            )
            tnx_hist = data_source.query(
                "SELECT date, close FROM us_index_daily WHERE code='^TNX' ORDER BY date"
            )
            if pe_hist.empty or tnx_hist.empty or len(pe_hist) < 100:
                score = score_with_config(cur_erp, "sp500_erp", self._market, self._config)
                return {"score": score, "value": round(cur_erp * 100, 2), "percentile": None,
                        "scoring": f"固定阈值(样本{len(pe_hist)}不足)"}
            pe_hist = pe_hist.copy()
            pe_hist["ym"] = pe_hist["date"].str[:7]
            tnx_hist = tnx_hist.copy()
            tnx_hist["ym"] = tnx_hist["date"].str[:7]
            tnx_m = tnx_hist.groupby("ym", as_index=False)["close"].last()  # 月末收益率
            m = pe_hist.merge(tnx_m, on="ym").dropna(subset=["pe_ratio", "close"])
            sample = (1.0 / m["pe_ratio"] - m["close"] / 100.0).tolist()
            score = score_by_percentile(cur_erp, sample, invert=True)
            if score is None:
                score = score_with_config(cur_erp, "sp500_erp", self._market, self._config)
                scoring = f"固定阈值(样本{len(sample)}不足)"
                pct = None
            else:
                scoring = f"全历史分位({len(sample)}点)"
                pct = round(float((np.array(sample) < cur_erp).mean() * 100), 0)
            return {"score": score, "value": round(cur_erp * 100, 2), "percentile": pct, "scoring": scoring}
        except Exception as e:
            logger.error(f"Failed to calculate sp500 ERP: {e}")
            return {"score": 5.0, "value": None, "percentile": None}


class UsLiquidityIndicator:
    """US 流动性: credit_spread。

    方法体逐字搬迁自 risk/indicators/liquidity.py, 仅适配取数与打分依赖。
    """

    def __init__(self, config: dict):
        self._market = "us"
        self._config = config

    def calculate(self, data_source, date: str | None = None) -> dict:
        results = {}
        results["credit_spread"] = self._credit_spread(data_source, date)
        return results

    def _credit_spread(self, data_source, date: str | None = None) -> dict:
        """HYG相对国债的30日偏离代理(信用利差代理). 扩大=资金逃风险=高风险(正常方向).

        历史10年序列分位打分; 样本不足回退固定阈值(percentile=None, 避免假50%).
        """
        try:
            from datetime import datetime, timedelta
            import numpy as np
            ref = date or datetime.now().strftime('%Y-%m-%d')
            start_10y = (datetime.strptime(ref, '%Y-%m-%d') - timedelta(days=3650)).strftime('%Y-%m-%d')
            if date:
                hist = data_source.query(
                    f"SELECT credit_spread FROM sentiment_data WHERE market='us' "
                    f"AND credit_spread IS NOT NULL AND date >= '{start_10y}' AND date <= ? ORDER BY date",
                    (date,),
                )
            else:
                hist = data_source.query(
                    f"SELECT credit_spread FROM sentiment_data WHERE market='us' "
                    f"AND credit_spread IS NOT NULL AND date >= '{start_10y}' ORDER BY date"
                )
            if hist.empty or len(hist) < 100:
                return {"score": 5.0, "value": None, "percentile": None, "scoring": "固定阈值(样本不足)"}
            vals = hist["credit_spread"].astype(float).tolist()
            cur = vals[-1]
            score = score_by_percentile(cur, vals)  # 扩大=高风险,正常方向
            if score is None:
                score = score_with_config(cur, "credit_spread", self._market, self._config)
                scoring = f"固定阈值(样本{len(vals)}不足)"
            else:
                scoring = f"近10年分位({len(vals)}点)"
            pct = float((np.array(vals) < cur).mean() * 100)
            return {"score": score, "value": round(cur, 4), "percentile": round(pct, 0), "scoring": scoring}
        except Exception as e:
            logger.error(f"Failed to calculate credit spread: {e}")
            return {"score": 5.0, "value": None, "percentile": None}


class UsSentimentIndicator:
    """US 情绪: vix / market_breadth。

    _vix 方法体逐字搬迁自 risk/indicators/sentiment.py, 仅适配取数与打分依赖。
    _market_breadth 新增: 上涨家数占比的历史分位(invert: 低广度=高风险)。
    """

    def __init__(self, config: dict):
        self._market = "us"
        self._config = config

    def calculate(self, data_source, date: str | None = None) -> dict:
        results = {}
        results["vix"] = self._vix(data_source, date)
        results["market_breadth"] = self._market_breadth(data_source, date)
        return results

    def _market_breadth(self, data_source, date: str | None = None) -> dict:
        """上涨家数占比(0-1)的近10年分位; invert: 低广度=高风险(指数高位+广度收缩=顶部前兆)."""
        return percentile_score_from_series(
            data_source, "sentiment_data", "market_breadth", "market='us'",
            date=date, invert=True, round_value=4,
        )

    def _vix(self, data_source, date: str | None = None) -> dict:
        """VIX收盘值的近10年分位. 高位=市场恐慌(模型计为高风险, 与_score同向).

        样本不足回退固定阈值(percentile=None).
        """
        try:
            from datetime import datetime, timedelta
            import numpy as np
            ref = date or datetime.now().strftime('%Y-%m-%d')
            start_10y = (datetime.strptime(ref, '%Y-%m-%d') - timedelta(days=3650)).strftime('%Y-%m-%d')
            if date:
                hist = data_source.query(
                    f"SELECT vix FROM sentiment_data WHERE market='us' "
                    f"AND vix IS NOT NULL AND date >= '{start_10y}' AND date <= ? ORDER BY date",
                    (date,),
                )
            else:
                hist = data_source.query(
                    f"SELECT vix FROM sentiment_data WHERE market='us' "
                    f"AND vix IS NOT NULL AND date >= '{start_10y}' ORDER BY date"
                )
            if hist.empty or len(hist) < 100:
                return {"score": 5.0, "value": None, "percentile": None, "scoring": "固定阈值(样本不足)"}
            vals = hist["vix"].astype(float).tolist()
            cur = vals[-1]
            score = score_by_percentile(cur, vals)  # VIX高位=高分
            if score is None:
                score = score_with_config(cur, "vix", self._market, self._config)
                scoring = f"固定阈值(样本{len(vals)}不足)"
            else:
                scoring = f"近10年分位({len(vals)}点)"
            pct = float((np.array(vals) < cur).mean() * 100)
            return {"score": score, "value": round(cur, 2), "percentile": round(pct, 0), "scoring": scoring}
        except Exception as e:
            logger.error(f"Failed to calculate VIX: {e}")
            return {"score": 5.0, "value": None, "percentile": None}


class UsMacroIndicator:
    """US 宏观: yield_curve_inversion。

    方法体逐字搬迁自 risk/indicators/macro.py, 仅适配取数与打分依赖。
    _cpi 不搬(calculate 从未调用, 死代码, 丢弃)。
    """

    def __init__(self, config: dict):
        self._market = "us"
        self._config = config

    def calculate(self, data_source, date: str | None = None) -> dict:
        results = {}
        results["yield_curve_inversion"] = self._yield_curve_inversion(data_source, date)
        return results

    def _yield_curve_inversion(self, data_source, date: str | None = None) -> dict:
        """10Y - 3M treasury yield spread. Negative = inverted = recession signal."""
        try:
            # Get 10Y and 3M yields
            tnx_df = data_source.query(
                "SELECT date, close FROM us_index_daily WHERE code='^TNX' "
                "ORDER BY date DESC LIMIT 60"
            )
            irx_df = data_source.query(
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
            config = self._config.get("yield_curve_inversion", {})
            threshold = config.get("thresholds", {}).get("us", 0.5)
            # Score based on how negative the spread is
            # -0.5 (50bp inversion) = threshold for high risk
            severity = abs(current_spread)
            score = normalize_score(severity, 0.0, threshold)

            return {"score": score, "value": current_spread, "percentile": None}
        except Exception as e:
            logger.error(f"Failed to calculate yield curve inversion: {e}")
            return {"score": 5.0, "value": None, "percentile": None}


def us_indicators(data_source, config: dict) -> list:
    """US 市场的全部 indicator 实例(config 由 pipeline 从 load_indicators('us') 注入)。

    顺序对应 risk/models.py 对 us 的编排: valuation -> technical -> liquidity
    -> sentiment -> macro。
    """
    return [
        UsValuationIndicator(config),
        TechnicalIndicator(market="us", config=config),
        UsLiquidityIndicator(config),
        UsSentimentIndicator(config),
        UsMacroIndicator(config),
    ]
