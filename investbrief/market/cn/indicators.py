"""CN 市场专属 risk indicator + 工厂。

从 risk/indicators/{valuation,liquidity}.py 搬迁 cn 方法体(逐字保留, 仅适配依赖)。
不 import risk —— config 由 pipeline 注入, 算法调 core。

迁移范式(适用于所有搬迁方法):
  1. self.data                          -> data_source 参数
  2. self._score_by_percentile(v, hist) -> score_by_percentile(v, hist)  (core.scoring)
  3. self._score(v, name, market)       -> score_with_config(v, name, self._market, self._config)
                                              (core.indicators)
注: 本 5 方法均用裸 SQL 取数, 不经过 _get_index_data / _get_config, 故范式 4/5 不适用。
"""
import logging

from investbrief.core.scoring import score_by_percentile
from investbrief.core.indicators import (
    score_with_config, TechnicalIndicator, percentile_score_from_series,
)

logger = logging.getLogger(__name__)


class CnValuationIndicator:
    """CN 估值: hsh300_erp / zz500_erp / structural_divergence。

    _erp_for_index / _structural_divergence 方法体逐字搬迁自
    risk/indicators/valuation.py, 仅适配取数与打分依赖。
    _buffett_cn / _pe_cn 不搬(calculate 从未调用, 死代码, 丢弃)。
    """

    def __init__(self, config: dict):
        self._market = "cn"
        self._config = config

    def calculate(self, data_source, date: str | None = None) -> dict:
        results = {}
        results["hsh300_erp"] = self._erp_for_index(data_source, "HSH300_PE", date)
        results["zz500_erp"] = self._erp_for_index(data_source, "ZZ500_PE", date)
        results["structural_divergence"] = self._structural_divergence(data_source, date)
        return results

    def _erp_for_index(self, data_source, pe_indicator: str, date: str | None = None) -> dict:
        """ERP = (1/PE) - 10Y国债收益率(差值法). 高ERP=股便宜=低风险(invert分位).

        用沪深300/中证500的PE与国债同期配对, 算每日ERP的历史分位。
        """
        try:
            from datetime import datetime, timedelta
            ref = date or datetime.now().strftime('%Y-%m-%d')
            start_10y = (datetime.strptime(ref, '%Y-%m-%d') - timedelta(days=3650)).strftime('%Y-%m-%d')
            pe_sql = (f"SELECT date, value AS pe FROM macro_data WHERE indicator='{pe_indicator}' "
                      f"AND country='cn' AND value IS NOT NULL AND date >= '{start_10y}'")
            bsql = (f"SELECT date, value AS bond FROM macro_data WHERE indicator='10Y_TREASURY' "
                    f"AND country='cn' AND value IS NOT NULL AND date >= '{start_10y}'")
            if date:
                pe_sql += f" AND date <= '{date}'"
                bsql += f" AND date <= '{date}'"
            pe_df = data_source.query(pe_sql + " ORDER BY date")
            bond_df = data_source.query(bsql + " ORDER BY date")
            if pe_df.empty or bond_df.empty:
                return {"score": 5.0, "value": None, "percentile": None}
            m = pe_df.merge(bond_df, on="date").dropna()
            sample = (1.0 / m["pe"] - m["bond"] / 100.0).tolist()
            if len(sample) < 100:
                return {"score": 5.0, "value": None, "percentile": None}
            cur = sample[-1]
            score = score_by_percentile(cur, sample, invert=True)  # ERP高=低风险
            if score is None:
                score = 5.0
                scoring = f"样本不足({len(sample)})"
            else:
                scoring = f"近10年分位({len(sample)}点)"
            import numpy as np
            pct = float((np.array(sample) < cur).mean() * 100)  # ERP实际分位(高=便宜)
            return {"score": score, "value": round(cur * 100, 2), "percentile": round(pct, 0), "scoring": scoring}
        except Exception as e:
            logger.error(f"Failed ERP for {pe_indicator}: {e}")
            return {"score": 5.0, "value": None, "percentile": None}

    def _structural_divergence(self, data_source, date: str | None = None) -> dict:
        """沪深300等权PE/加权PE 比值 = 结构分化. 高=少数股泡沫(抱团/小盘疯)=风险."""
        try:
            from datetime import datetime, timedelta
            ref = date or datetime.now().strftime('%Y-%m-%d')
            start_10y = (datetime.strptime(ref, '%Y-%m-%d') - timedelta(days=3650)).strftime('%Y-%m-%d')
            eq_sql = (f"SELECT date, value AS eq FROM macro_data WHERE indicator='HSH300_PE' "
                      f"AND country='cn' AND value IS NOT NULL AND date >= '{start_10y}'")
            w_sql = (f"SELECT date, value AS w FROM macro_data WHERE indicator='HSH300_PE_W' "
                     f"AND country='cn' AND value IS NOT NULL AND date >= '{start_10y}'")
            if date:
                eq_sql += f" AND date <= '{date}'"
                w_sql += f" AND date <= '{date}'"
            eq_df = data_source.query(eq_sql + " ORDER BY date")
            w_df = data_source.query(w_sql + " ORDER BY date")
            if eq_df.empty or w_df.empty:
                return {"score": 5.0, "value": None, "percentile": None}
            m = eq_df.merge(w_df, on="date").dropna()
            ratios = (m["eq"] / m["w"]).tolist()
            if len(ratios) < 100:
                return {"score": 5.0, "value": None, "percentile": None}
            cur = ratios[-1]
            score = score_by_percentile(cur, ratios)  # 比值高=高分
            if score is None:
                score = 5.0
                scoring = f"样本不足({len(ratios)})"
            else:
                scoring = f"近10年分位({len(ratios)}点)"
            import numpy as np
            pct = float((np.array(ratios) < cur).mean() * 100)
            return {"score": score, "value": round(cur, 2), "percentile": round(pct, 0), "scoring": scoring}
        except Exception as e:
            logger.error(f"Failed structural divergence: {e}")
            return {"score": 5.0, "value": None, "percentile": None}


class CnLiquidityIndicator:
    """CN 流动性: margin_growth / margin_level。

    方法体逐字搬迁自 risk/indicators/liquidity.py, 仅适配取数与打分依赖。
    """

    def __init__(self, config: dict):
        self._market = "cn"
        self._config = config

    def calculate(self, data_source, date: str | None = None) -> dict:
        results = {}
        results["margin_growth"] = self._margin_growth(data_source, date)
        results["margin_level"] = self._margin_level(data_source, date)
        results["north_flow"] = self._north_flow(data_source, date)
        return results

    def _north_flow(self, data_source, date: str | None = None) -> dict:
        """北向资金净流入(亿)的近10年分位. invert: 大流出=高风险(外资撤离信号).

        数据 2024-08-16 起停发, 之后最新行 north_flow=NULL -> value None -> 退出加权
        (不影响当日分数); 历史回测窗口内(<=2024-08-16)正常生效。
        """
        return percentile_score_from_series(
            data_source, "sentiment_data", "north_flow", "market='cn'",
            date=date, invert=True, round_value=2,
        )

    def _margin_growth(self, data_source, date: str | None = None) -> dict:
        """4周(20交易日)融资余额增速 = 杠杆加速度. 高增速=亢奋加杠杆=高风险.

        改自 margin_balance_ratio(占比): 避开 total_market_cap 历史稀疏(332点)的
        scaling坑, 改用增速(天然归一化), 且更贴合"杠杆加速冲顶比绝对高位更危险"。
        """
        try:
            from datetime import datetime, timedelta
            ref = date or datetime.now().strftime('%Y-%m-%d')
            start_10y = (datetime.strptime(ref, '%Y-%m-%d') - timedelta(days=3650)).strftime('%Y-%m-%d')
            if date:
                hist = data_source.query(
                    f"SELECT margin_balance FROM sentiment_data WHERE market='cn' "
                    f"AND margin_balance IS NOT NULL AND date >= '{start_10y}' AND date <= ? ORDER BY date",
                    (date,),
                )
            else:
                hist = data_source.query(
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
            score = score_by_percentile(cur, growths)  # 增速高=高分(正常方向,不invert)
            if score is None:
                score = score_with_config(cur, "margin_growth", self._market, self._config)
                scoring = f"固定阈值(样本{len(growths)}不足)"
            else:
                scoring = f"近10年分位({len(growths)}点)"
            import numpy as np
            pct = float((np.array(growths) < cur).mean() * 100)
            return {"score": score, "value": round(cur * 100, 1), "percentile": round(pct, 0), "scoring": scoring}
        except Exception as e:
            logger.error(f"Failed to calculate margin growth: {e}")
            return {"score": 5.0, "value": None, "percentile": None}

    def _margin_level(self, data_source, date: str | None = None) -> dict:
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
                hist = data_source.query(
                    f"SELECT margin_balance FROM sentiment_data WHERE market='cn' "
                    f"AND margin_balance IS NOT NULL AND date >= '{start_10y}' AND date <= ? ORDER BY date",
                    (date,),
                )
            else:
                hist = data_source.query(
                    f"SELECT margin_balance FROM sentiment_data WHERE market='cn' "
                    f"AND margin_balance IS NOT NULL AND date >= '{start_10y}' ORDER BY date"
                )
            if hist.empty or len(hist) < 100:
                return {"score": 5.0, "value": None, "percentile": None}
            vals = hist["margin_balance"].astype(float).tolist()
            cur = vals[-1]
            score = score_by_percentile(cur, vals)  # 高=高分
            if score is None:
                score = score_with_config(cur, "margin_level", self._market, self._config)
                scoring = f"固定阈值(样本{len(vals)}不足)"
            else:
                scoring = f"近10年分位({len(vals)}点)"
            import numpy as np
            pct = float((np.array(vals) < cur).mean() * 100)
            return {"score": score, "value": round(cur, 0), "percentile": round(pct, 0), "scoring": scoring}
        except Exception as e:
            logger.error(f"Failed to calculate margin level: {e}")
            return {"score": 5.0, "value": None, "percentile": None}


class CnSentimentIndicator:
    """CN 情绪: market_breadth / pledge_ratio。

    market_breadth: 上涨家数占比(0-1)的近10年分位; invert=True(低广度=高风险,
        指数高位 + 广度收缩 = 顶部前兆)。
    pledge_ratio: A股质押比例%的近10年分位; 正向(高质押 + 下跌 = 强平连锁尾部风险)。

    两者最新值 NULL -> value None -> 退出加权(见 models.py:79)。
    """

    def __init__(self, config: dict):
        self._market = "cn"
        self._config = config

    def calculate(self, data_source, date: str | None = None) -> dict:
        results = {}
        results["market_breadth"] = self._market_breadth(data_source, date)
        results["pledge_ratio"] = self._pledge_ratio(data_source, date)
        return results

    def _market_breadth(self, data_source, date: str | None = None) -> dict:
        return percentile_score_from_series(
            data_source, "sentiment_data", "market_breadth", "market='cn'",
            date=date, invert=True, round_value=4,
        )

    def _pledge_ratio(self, data_source, date: str | None = None) -> dict:
        return percentile_score_from_series(
            data_source, "sentiment_data", "pledge_ratio", "market='cn'",
            date=date, invert=False, round_value=4,
        )


def cn_indicators(data_source, config: dict) -> list:
    """CN 市场的全部 indicator 实例(config 由 pipeline 从 load_indicators('cn') 注入)。

    顺序对应 risk/models.py 对 cn 的编排: valuation -> technical -> liquidity -> sentiment。
    """
    return [
        CnValuationIndicator(config),
        TechnicalIndicator(market="cn", config=config),
        CnLiquidityIndicator(config),
        CnSentimentIndicator(config),
    ]
