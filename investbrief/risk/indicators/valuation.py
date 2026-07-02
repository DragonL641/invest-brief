"""Valuation indicators: Buffett, Index PE, Equity-Bond ratio."""

from investbrief.risk.indicators.base import BaseIndicator
from investbrief.risk.calc_utils import safe_divide
import logging

logger = logging.getLogger(__name__)


class ValuationIndicator(BaseIndicator):
    """Calculates valuation risk indicators."""

    def calculate(self, market: str, date: str | None = None) -> dict:
        results = {}
        if market == "cn":
            results["hsh300_erp"] = self._hsh300_erp(market, date)
            results["zz500_erp"] = self._zz500_erp(market, date)
            results["structural_divergence"] = self._structural_divergence(market, date)
        else:
            results["index_pe"] = self._index_pe(market, date)
            results["sp500_erp"] = self._sp500_erp(market, date)
        return results

    def _buffett_indicator(self, market: str, date: str | None = None) -> dict:
        """Market cap / GDP ratio."""
        try:
            if market == "cn":
                return self._buffett_cn(date)
            else:
                return self._buffett_us(date)
        except Exception as e:
            logger.error(f"Failed to calculate Buffett indicator for {market}: {e}")
            return {"score": 5.0, "value": None, "percentile": None}

    def _buffett_cn(self, date: str | None) -> dict:
        # Get latest market cap from sentiment_data
        if date:
            cap_df = self.data.query(
                "SELECT total_market_cap FROM sentiment_data WHERE market='cn' "
                "AND total_market_cap IS NOT NULL AND date <= ? ORDER BY date DESC LIMIT 1",
                (date,),
            )
        else:
            cap_df = self.data.query(
                "SELECT total_market_cap FROM sentiment_data WHERE market='cn' "
                "AND total_market_cap IS NOT NULL ORDER BY date DESC LIMIT 1"
            )
        if cap_df.empty:
            return {"score": 5.0, "value": None, "percentile": None}

        market_cap = float(cap_df.iloc[0]["total_market_cap"])

        # 取最近全年GDP(12-31累计值)作TTM近似。
        # 注: GDP季度数据是年内累计(Q1/H1/前三季/全年), 直接sum最近4条会重复
        # 计算(全年已含各季), 跨年时cumulative判断也失效 -> GDP虚高 -> ratio偏低。
        gdp_df = self.data.query(
            "SELECT date, value FROM macro_data WHERE indicator='GDP' AND country='cn' "
            "AND date LIKE '%-12-31' ORDER BY date DESC LIMIT 1"
        )
        if gdp_df.empty:
            gdp_df = self.data.query(
                "SELECT date, value FROM macro_data WHERE indicator='GDP' AND country='cn' "
                "ORDER BY date DESC LIMIT 1"
            )
        if gdp_df.empty:
            return {"score": 5.0, "value": None, "percentile": None}
        gdp_total = float(gdp_df.iloc[0]["value"])

        ratio = safe_divide(market_cap, gdp_total)
        score = self._score(ratio, "buffett_indicator", "cn")

        return {"score": score, "value": ratio, "percentile": None}

    def _buffett_us(self, date: str | None) -> dict:
        # US Buffett: S&P 500 market cap estimate / GDP
        idx_df = self._get_index_data("us", 5, date)
        if idx_df.empty:
            return {"score": 5.0, "value": None, "percentile": None}

        sp500_level = float(idx_df.iloc[-1]["close"])

        gdp_df = self.data.query(
            "SELECT value FROM macro_data WHERE indicator='GDP' AND country='us' "
            "ORDER BY date DESC LIMIT 1"
        )
        if gdp_df.empty:
            return {"score": 5.0, "value": None, "percentile": None}

        gdp_trillion = float(gdp_df.iloc[0]["value"])
        # S&P 500 total market cap ≈ index level * 8.5B (approximate divisor)
        # Then divide by GDP in trillion to get Buffett ratio
        sp500_mcap = sp500_level * 8.5  # rough trillion USD estimate
        ratio = safe_divide(sp500_mcap, gdp_trillion * 1000)
        # S&P at 5300 → mcap ~45T, GDP 27T → ratio ~1.67 (realistic Buffett ~170%)
        score = self._score(ratio, "buffett_indicator", "us")

        return {"score": score, "value": ratio, "percentile": None}

    def _index_pe(self, market: str, date: str | None = None) -> dict:
        """Current PE ratio of the market index."""
        try:
            if market == "cn":
                return self._pe_cn(date)
            else:
                return self._pe_us(date)
        except Exception as e:
            logger.error(f"Failed to calculate Index PE for {market}: {e}")
            return {"score": 5.0, "value": None, "percentile": None}

    def _pe_cn(self, date: str | None) -> dict:
        if date:
            hist = self.data.query(
                "SELECT pe_ratio FROM sentiment_data WHERE market='cn' "
                "AND pe_ratio IS NOT NULL AND date <= ? ORDER BY date",
                (date,),
            )
        else:
            hist = self.data.query(
                "SELECT pe_ratio FROM sentiment_data WHERE market='cn' "
                "AND pe_ratio IS NOT NULL ORDER BY date"
            )
        if hist.empty:
            return {"score": 5.0, "value": None, "percentile": None}

        pe = float(hist.iloc[-1]["pe_ratio"])
        sample = hist["pe_ratio"].tolist()
        score = self._score_by_percentile(pe, sample)
        if score is None:
            score = self._score(pe, "index_pe", "cn")  # 样本不足回退固定阈值
            scoring = f"固定阈值(样本{len(sample)}不足)"
            pct = None
        else:
            scoring = f"历史分位({len(sample)}点)"
            import numpy as np
            pct = round(float((np.array(sample) < pe).mean() * 100), 0)
        return {"score": score, "value": pe, "percentile": pct, "scoring": scoring}

    def _pe_us(self, date: str | None) -> dict:
        # 当前值=最新pe_ratio(SPY当天优先, date更大); 分位样本=纯Shiller月度(length(date)=7).
        # SPY当天点不入分位 -> 分位完全由Shiller一次性历史决定, 不依赖SPY逐日积累.
        if date:
            latest = self.data.query(
                "SELECT pe_ratio FROM sentiment_data WHERE market='us' "
                "AND pe_ratio IS NOT NULL AND date <= ? ORDER BY date DESC LIMIT 1",
                (date,),
            )
            samp = self.data.query(
                "SELECT pe_ratio FROM sentiment_data WHERE market='us' "
                "AND pe_ratio IS NOT NULL AND length(date)=7 AND date <= ? ORDER BY date",
                (date,),
            )
        else:
            latest = self.data.query(
                "SELECT pe_ratio FROM sentiment_data WHERE market='us' "
                "AND pe_ratio IS NOT NULL ORDER BY date DESC LIMIT 1"
            )
            samp = self.data.query(
                "SELECT pe_ratio FROM sentiment_data WHERE market='us' "
                "AND pe_ratio IS NOT NULL AND length(date)=7 ORDER BY date"
            )
        if latest.empty:
            return {"score": 5.0, "value": None, "percentile": None}

        pe = float(latest.iloc[0]["pe_ratio"])
        sample = samp["pe_ratio"].tolist()
        score = self._score_by_percentile(pe, sample)
        if score is None:
            score = self._score(pe, "index_pe", "us")  # 样本不足回退固定阈值
            scoring = f"固定阈值(样本{len(sample)}不足)"
            pct = None
        else:
            scoring = f"全历史分位({len(sample)}点)"
            import numpy as np
            pct = round(float((np.array(sample) < pe).mean() * 100), 0)
        return {"score": score, "value": pe, "percentile": pct, "scoring": scoring}

    def _sp500_erp(self, market: str, date: str | None = None) -> dict:
        """标普500 ERP = 1/PE - 10Y国债(差值法, 与A股ERP完全同一口径). 高ERP=股便宜=低风险.

        当前值: SPY当天PE - ^TNX当天; 分位样本: Shiller月度PE配^TNX月末的全历史ERP.
        """
        import numpy as np
        try:
            pe_now = self._index_pe(market, date)["value"]
            if date:
                tnx_df = self.data.query(
                    "SELECT close FROM us_index_daily WHERE code='^TNX' AND date <= ? "
                    "ORDER BY date DESC LIMIT 1", (date,)
                )
            else:
                tnx_df = self.data.query(
                    "SELECT close FROM us_index_daily WHERE code='^TNX' "
                    "ORDER BY date DESC LIMIT 1"
                )
            if pe_now is None or pe_now <= 0 or tnx_df.empty:
                return {"score": 5.0, "value": None, "percentile": None}
            cur_erp = 1.0 / float(pe_now) - float(tnx_df.iloc[0]["close"]) / 100.0

            # 分位样本: Shiller月度PE(length(date)=7) 配 ^TNX月末, 按YYYY-MM对齐
            pe_hist = self.data.query(
                "SELECT date, pe_ratio FROM sentiment_data WHERE market='us' "
                "AND pe_ratio IS NOT NULL AND length(date)=7 ORDER BY date"
            )
            tnx_hist = self.data.query(
                "SELECT date, close FROM us_index_daily WHERE code='^TNX' ORDER BY date"
            )
            if pe_hist.empty or tnx_hist.empty or len(pe_hist) < 100:
                score = self._score(cur_erp, "sp500_erp", "us")
                return {"score": score, "value": round(cur_erp * 100, 2), "percentile": None,
                        "scoring": f"固定阈值(样本{len(pe_hist)}不足)"}
            pe_hist = pe_hist.copy()
            pe_hist["ym"] = pe_hist["date"].str[:7]
            tnx_hist = tnx_hist.copy()
            tnx_hist["ym"] = tnx_hist["date"].str[:7]
            tnx_m = tnx_hist.groupby("ym", as_index=False)["close"].last()  # 月末收益率
            m = pe_hist.merge(tnx_m, on="ym").dropna(subset=["pe_ratio", "close"])
            sample = (1.0 / m["pe_ratio"] - m["close"] / 100.0).tolist()
            score = self._score_by_percentile(cur_erp, sample, invert=True)
            if score is None:
                score = self._score(cur_erp, "sp500_erp", "us")
                scoring = f"固定阈值(样本{len(sample)}不足)"
                pct = None
            else:
                scoring = f"全历史分位({len(sample)}点)"
                pct = round(float((np.array(sample) < cur_erp).mean() * 100), 0)
            return {"score": score, "value": round(cur_erp * 100, 2), "percentile": pct, "scoring": scoring}
        except Exception as e:
            logger.error(f"Failed to calculate sp500 ERP: {e}")
            return {"score": 5.0, "value": None, "percentile": None}

    def _erp_for_index(self, pe_indicator: str, market: str, date: str | None = None) -> dict:
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
            pe_df = self.data.query(pe_sql + " ORDER BY date")
            bond_df = self.data.query(bsql + " ORDER BY date")
            if pe_df.empty or bond_df.empty:
                return {"score": 5.0, "value": None, "percentile": None}
            m = pe_df.merge(bond_df, on="date").dropna()
            sample = (1.0 / m["pe"] - m["bond"] / 100.0).tolist()
            if len(sample) < 100:
                return {"score": 5.0, "value": None, "percentile": None}
            cur = sample[-1]
            score = self._score_by_percentile(cur, sample, invert=True)  # ERP高=低风险
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

    def _hsh300_erp(self, market: str, date: str | None = None) -> dict:
        return self._erp_for_index("HSH300_PE", market, date)

    def _zz500_erp(self, market: str, date: str | None = None) -> dict:
        return self._erp_for_index("ZZ500_PE", market, date)

    def _structural_divergence(self, market: str, date: str | None = None) -> dict:
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
            eq_df = self.data.query(eq_sql + " ORDER BY date")
            w_df = self.data.query(w_sql + " ORDER BY date")
            if eq_df.empty or w_df.empty:
                return {"score": 5.0, "value": None, "percentile": None}
            m = eq_df.merge(w_df, on="date").dropna()
            ratios = (m["eq"] / m["w"]).tolist()
            if len(ratios) < 100:
                return {"score": 5.0, "value": None, "percentile": None}
            cur = ratios[-1]
            score = self._score_by_percentile(cur, ratios)  # 比值高=高分
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
