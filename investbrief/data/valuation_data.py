"""估值类宏观序列落库：ERP（Shiller PE + 美债10Y，来自 multpl）。

落 macro_data(country='us', 月度)：
  - SHILLER_PE   席勒市盈率 CAPE
  - US_10Y_BOND  10Y 美债收益率（%，月度，与 CAPE 同源同频）
  - ERP          = 1/CAPE*100 − 美债10Y（百分点）

DB-First：update_time 为今天则跳过（multpl 月度更新，单日多次跑只爬一次）。
"""
import logging

import pandas as pd

from investbrief.core.timeutil import now_cn
from investbrief.data.base import BaseData
from investbrief.datasources import multpl

logger = logging.getLogger(__name__)


class ValuationData(BaseData):
    market_code = "valuation"
    primary_index = ""
    primary_table = ""

    def update_all(self):
        self.update_erp()

    def update_incremental(self):
        self.update_erp()

    def update_erp(self) -> bool:
        """爬 multpl CAPE + 美债，merge 算 ERP，upsert 三条月度序列。

        DB-First：今天已爬过则跳过。失败返回 False（不抛，pipeline 不阻塞）。
        """
        today = now_cn().strftime("%Y-%m-%d")
        last_run = self.get_update_time("macro_data_erp_us")
        if last_run and str(last_run)[:10] == today:
            logger.info("ERP already fetched today, skip")
            return True
        try:
            pe_df = multpl.fetch_multpl_series("/shiller-pe")
            bond_df = multpl.fetch_multpl_series("/10-year-treasury-rate")
        except Exception as e:
            logger.warning(f"multpl fetch failed, ERP not updated: {e}")
            return False
        merged = pd.merge(pe_df, bond_df, on="date", suffixes=("_pe", "_bond"))
        merged = merged[merged["value_pe"] > 0]  # 防 CAPE=0 除零 → inf
        merged["erp"] = 1.0 / merged["value_pe"] * 100 - merged["value_bond"]
        rows = []
        for _, r in merged.iterrows():
            d = r["date"].strftime("%Y-%m-%d")
            rows.append({"indicator": "SHILLER_PE", "country": "us", "date": d, "value": float(r["value_pe"])})
            rows.append({"indicator": "US_10Y_BOND", "country": "us", "date": d, "value": float(r["value_bond"])})
            rows.append({"indicator": "ERP", "country": "us", "date": d, "value": round(float(r["erp"]), 4)})
        self.upsert_df("macro_data", pd.DataFrame(rows))
        latest_date = merged["date"].max().strftime("%Y-%m-%d")
        self.set_update_date("macro_data_erp_us", latest_date)
        logger.info(f"ERP updated: {len(rows) // 3} months, latest {latest_date}")
        return True
