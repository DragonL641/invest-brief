"""Gold market data acquisition: gold price (akshare SGE) + US M2/CPI (FRED).

数据落 macro_data 表（零改表结构）:
  - GOLD_PRICE  country='global'  日频(近期) + 年度(1990-2024 历史)  USD/oz
  - M2          country='us'       月频(FRED, 2000+)                   万亿美元
  - CPI         country='us'       月频(FRED, 2000+)                   指数

依赖: akshare (金价/汇率), requests (FRED)
迁移自 gold-valuation-backtest/gold_valuation.py。
"""

from io import StringIO

import pandas as pd
import requests

from investbrief.data.base import BaseData
import logging

logger = logging.getLogger(__name__)

# ============================================================
# 硬编码历史基准 (1990-2024, 不变数据; GoldIndicator 算 z-score 时用)
# ============================================================

GOLD_PRICE_HIST = {
    1980: 612.0, 1981: 460.0, 1982: 376.0, 1983: 424.0, 1984: 361.0,
    1985: 317.0, 1986: 368.0, 1987: 447.0, 1988: 437.0, 1989: 381.0,
    1990: 386.20, 1991: 353.15, 1992: 333.00, 1993: 391.75, 1994: 383.25,
    1995: 387.00, 1996: 369.00, 1997: 287.05, 1998: 288.70, 1999: 290.25,
    2000: 272.65, 2001: 276.50, 2002: 342.75, 2003: 417.25, 2004: 435.60,
    2005: 513.00, 2006: 635.70, 2007: 836.50, 2008: 869.75, 2009: 1087.50,
    2010: 1420.25, 2011: 1531.00, 2012: 1664.00, 2013: 1204.50, 2014: 1199.25,
    2015: 1060.00, 2016: 1151.70, 2017: 1302.30, 2018: 1281.65, 2019: 1517.10,
    2020: 1898.32, 2021: 1798.89, 2022: 1801.87, 2023: 2062.92, 2024: 2378.83,
}

US_M2_HIST = {  # 万亿美元, 年末值, 来源 FRED M2SL
    1990: 3.27, 1991: 3.37, 1992: 3.42, 1993: 3.47, 1994: 3.49,
    1995: 3.63, 1996: 3.82, 1997: 4.03, 1998: 4.38, 1999: 4.64,
    2000: 4.93, 2001: 5.43, 2002: 5.77, 2003: 6.07, 2004: 6.42,
    2005: 6.68, 2006: 7.07, 2007: 7.47, 2008: 8.19, 2009: 8.50,
    2010: 8.80, 2011: 9.66, 2012: 10.46, 2013: 11.04, 2014: 11.69,
    2015: 12.35, 2016: 13.21, 2017: 13.85, 2018: 14.36, 2019: 15.31,
    2020: 19.10, 2021: 21.50, 2022: 21.31, 2023: 20.75, 2024: 21.49,
}

MONETARY_PCT_HIST = {  # 货币黄金占官方储备比例 %
    1990: 41.7, 1991: 40.8, 1992: 40.4, 1993: 40.0, 1994: 39.2,
    1995: 38.9, 1996: 38.5, 1997: 38.2, 1998: 38.0, 1999: 38.2,
    2000: 38.5, 2001: 38.9, 2002: 38.6, 2003: 38.4, 2004: 38.8,
    2005: 38.6, 2006: 38.7, 2007: 39.3, 2008: 40.8, 2009: 41.9,
    2010: 42.1, 2011: 43.0, 2012: 43.6, 2013: 44.1, 2014: 42.8,
    2015: 41.9, 2016: 42.2, 2017: 41.6, 2018: 41.7, 2019: 41.3,
    2020: 42.8, 2021: 41.6, 2022: 41.8, 2023: 41.8, 2024: 41.1,
}

GOLD_STOCK_2024 = 216265  # 吨, 2024 年末黄金存量

WORLD_GDP_HIST = {  # 万亿美元, nominal current USD, 来源 IMF WEO WEOWORLD
    1980: 11.3, 1981: 11.6, 1982: 11.4, 1983: 11.7, 1984: 12.1,
    1985: 12.6, 1986: 14.9, 1987: 17.2, 1988: 19.3, 1989: 20.3,
    1990: 22.9, 1991: 24.4, 1992: 25.5, 1993: 26.2, 1994: 28.2,
    1995: 31.4, 1996: 32.4, 1997: 32.3, 1998: 32.1, 1999: 33.2,
    2000: 34.3, 2001: 34.1, 2002: 35.2, 2003: 39.5, 2004: 44.4,
    2005: 48.2, 2006: 52.2, 2007: 58.9, 2008: 64.7, 2009: 61.3,
    2010: 67.1, 2011: 74.5, 2012: 76.0, 2013: 78.3, 2014: 80.5,
    2015: 75.9, 2016: 77.2, 2017: 82.1, 2018: 87.2, 2019: 88.5,
    2020: 86.2, 2021: 98.4, 2022: 102.7, 2023: 107.2, 2024: 111.6,
    2025: 118.2,
}
TONNES_TO_OZ = 32151
GRAMS_PER_OZ = 31.1035
FRED_TIMEOUT = 30


class GoldData(BaseData):
    """Gold market data acquisition. Stores into the existing macro_data table."""

    market_code = "gold"
    primary_index = ""                       # gold 不走 *_index_daily
    primary_table = ""
    primary_indicator = ("GOLD_PRICE_CNY", "cn")  # 日频金价存于 macro_data

    def update_all(self):
        """Full download: seed annual + daily history + fetch latest M2/CPI/USDCNY/gold."""
        logger.info("Starting gold data download")
        self._seed_gold_history()        # 年度金价(USD/oz, 1990-2024) for z-score
        self._seed_gold_daily_sge()      # 日频金价(元/克, SGE) for MA200
        self.update_fred_series("M2SL", "M2", "us")
        self.update_fred_series("CPIAUCSL", "CPI_INDEX", "us")  # 指数, 与 us_data 同比% CPI 分开
        self.update_fred_series("DFII10", "REAL_YIELD_10Y", "us")  # 10Y TIPS 实际利率
        self.update_world_gdp()
        self.update_fred_series("DEXCHUS", "USDCNY", "global")  # 汇率先入库
        self.update_gold_price()  # 用库里最新汇率换算当日金价(USD/oz)
        logger.info("Gold data download complete")

    def update_world_gdp(self):
        """拉 IMF WEO 全球名义GDP -> macro_data WORLD_GDP. 失败则依赖硬编码 WORLD_GDP_HIST."""
        try:
            import json
            r = requests.get(
                "https://www.imf.org/external/datamapper/api/v1/NGDPD/OEMDC/ADVEC/WEOWORLD",
                timeout=30,
            )
            w = json.loads(r.text)["values"]["NGDPD"]["WEOWORLD"]
            rows = [{
                "indicator": "WORLD_GDP", "country": "global",
                "date": f"{y}-12-31", "value": float(w[y]) / 1000,  # 十亿->万亿
            } for y in w if w[y] is not None]
            self.upsert_df("macro_data", pd.DataFrame(rows))
            logger.info(f"World GDP: {len(rows)} rows (IMF WEO)")
        except Exception as e:
            logger.warning(f"IMF GDP failed, fallback to hardcoded WORLD_GDP_HIST: {e}")

    def _seed_gold_daily_sge(self):
        """Seed SGE daily gold price (元/克) for MA200 technical indicator.

        存 macro_data(indicator=GOLD_PRICE_CNY, country=cn)。幂等(INSERT OR IGNORE)。
        MA200 偏离度是比例, 币种无关, 故直接存元/克不必转 USD。
        """
        try:
            import akshare as ak

            df = self._retry_api(lambda: ak.spot_golden_benchmark_sge())
            if df is None or df.empty:
                return
            rows = []
            for _, r in df.iterrows():
                d = r.iloc[0]
                d = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)[:10]
                price = r.iloc[2] if pd.notna(r.iloc[2]) else r.iloc[1]  # 早盘/晚盘 元/克
                rows.append({
                    "indicator": "GOLD_PRICE_CNY", "country": "cn",
                    "date": d, "value": float(price),
                })
            self.upsert_df("macro_data", pd.DataFrame(rows))
            logger.info(f"SGE daily gold seeded: {len(rows)} rows (GOLD_PRICE_CNY)")
        except Exception as e:
            logger.error(f"Failed to seed SGE daily gold: {e}")

    def update_incremental(self):
        self.update_all()

    # ---------- gold price (akshare SGE) ----------

    def update_gold_price(self):
        """akshare 上海金交所最新金价(元/克) -> USD/oz -> macro_data GOLD_PRICE."""
        try:
            import akshare as ak

            df = self._retry_api(lambda: ak.spot_golden_benchmark_sge())
            if df is None or df.empty:
                return
            # akshare 帧顺序不可信(CLAUDE.md)，按交易时间列(第0列)升序后再取最新行，
            # 否则降序帧会把最旧金价当最新 upsert
            df = df.sort_values(by=df.columns[0], kind="stable").reset_index(drop=True)
            latest = df.iloc[-1]
            # 列顺序: 交易时间, 晚盘价, 早盘价
            early = latest.iloc[2] if pd.notna(latest.iloc[2]) else latest.iloc[1]
            price_cny_per_gram = float(early)
            trade_date = str(latest.iloc[0])
            if len(trade_date) == 8:
                trade_date = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}"
            else:
                trade_date = trade_date[:10]

            usdcny = self._get_usdcny()
            if not usdcny or usdcny <= 0:
                logger.warning("USD/CNY unavailable, skip gold price update")
                return

            price_usd = price_cny_per_gram / usdcny * GRAMS_PER_OZ  # 元/克 -> USD/oz
            row = pd.DataFrame([{
                "indicator": "GOLD_PRICE", "country": "global",
                "date": trade_date, "value": round(price_usd, 2),
            }])
            self.upsert_df("macro_data", row)
            self.set_update_date("macro_data_gold_price", trade_date)
            logger.info(f"Gold price updated: ${price_usd:.0f}/oz @ {trade_date} (CNY {price_cny_per_gram:.2f}/g, USD/CNY {usdcny:.3f})")
        except Exception as e:
            logger.error(f"Failed to update gold price: {e}")

    def _get_usdcny(self):
        """从 macro_data 查最新 USD/CNY 汇率（来源 FRED DEXCHUS, CNY per USD）。

        弃用 akshare fx_spot_quote：实测该接口对 USD/CNY 返回 nan。FRED DEXCHUS 稳定。
        """
        df = self.query(
            "SELECT value FROM macro_data WHERE indicator='USDCNY' "
            "AND value IS NOT NULL ORDER BY date DESC LIMIT 1"
        )
        if df.empty:
            return None
        return float(df.iloc[0]["value"])

    # ---------- FRED M2 / CPI ----------

    def update_fred_series(self, series_id, indicator, country, cosd=None):
        """Fetch a FRED series into macro_data. M2 单位转为 万亿美元.

        cosd=None 时按 macro_data 中该 indicator 的 last_update_date 增量取（首跑全量自 2000）。
        """
        if cosd is None:
            last = self.get_update_date(f"macro_data_{indicator.lower()}_{country}")
            cosd = last or "2000-01-01"
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={cosd}"
        try:
            r = requests.get(url, timeout=FRED_TIMEOUT)
            if r.status_code != 200:
                logger.warning(f"FRED {series_id} returned HTTP {r.status_code}")
                return
            df = pd.read_csv(StringIO(r.text)).dropna()
            if df.empty:
                return
            rows = []
            for _, r2 in df.iterrows():
                val = float(r2.iloc[1])
                if indicator == "M2":
                    val = val / 1000  # 十亿 -> 万亿美元
                rows.append({
                    "indicator": indicator, "country": country,
                    "date": str(r2.iloc[0]), "value": val,
                })
            inserted = self.upsert_df("macro_data", pd.DataFrame(rows))
            self.set_update_date(f"macro_data_{indicator.lower()}_{country}", str(df.iloc[-1, 0]))
            logger.info(f"FRED {series_id} -> {indicator}: {inserted} rows stored")
        except Exception as e:
            logger.error(f"Failed FRED {series_id}: {e}")

    # ---------- history seeding ----------

    def _seed_gold_history(self):
        """Seed annual gold price history (1990-2024) as z-score baseline.

        Idempotent: INSERT OR IGNORE on PK (indicator, country, date); 年度 12-31 与日频不冲突.
        """
        rows = [{
            "indicator": "GOLD_PRICE", "country": "global",
            "date": f"{y}-12-31", "value": float(p),
        } for y, p in GOLD_PRICE_HIST.items()]
        self.upsert_df("macro_data", pd.DataFrame(rows))
