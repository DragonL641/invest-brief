"""Gold valuation indicators (方案A 轻量版 3 指标).

迁移自 gold_valuation.py 的 z-score 方法论, 适配主系统 BaseIndicator 框架:
  - gold_gdp_ratio:       全部黄金价值/全球GDP 占比(原 gold_valuation 货币黄金/M2, 改全球GDP
                          分母以避开 2020 放水期 M2 失真)
  - gold_real_price:      金价/CPI 实际金价的历史 z-score
  - gold_ma200_deviation: 金价相对 MA200 偏离度 (技术面, 用 SGE 日频元/克, 币种无关)
"""
from datetime import date as _date

import numpy as np
import pandas as pd

from investbrief.data.gold_data import (
    GOLD_PRICE_HIST, WORLD_GDP_HIST,
    GOLD_STOCK_2024, TONNES_TO_OZ,
)
from investbrief.risk.indicators.base import BaseIndicator

import logging

logger = logging.getLogger(__name__)

NEUTRAL = {"score": 5.0, "value": None, "percentile": None}


class GoldIndicator(BaseIndicator):
    """Gold-specific valuation/risk indicators."""

    def calculate(self, market, date=None):
        if market != "gold":
            return {}
        return {
            "gold_gdp_ratio": self._gold_gdp_ratio(date),
            "gold_real_price": self._real_price(date),
            "gold_ma200_deviation": self._ma200_deviation(date),
        }

    # ---------- helpers ----------

    @staticmethod
    def _neutral():
        return dict(NEUTRAL)

    def _latest(self, indicator, country, date=None):
        sql = (f"SELECT value FROM macro_data WHERE indicator='{indicator}' "
               f"AND country='{country}' AND value IS NOT NULL")
        if date:
            sql += f" AND date <= '{date}'"
        sql += " ORDER BY date DESC LIMIT 1"
        df = self.data.query(sql)
        return float(df.iloc[0]["value"]) if not df.empty else None

    def _gold_price_yearly(self, date=None):
        """年度金价序列(USD/oz): 硬编码历史(1990-2024) + 库里当年值."""
        sql = ("SELECT date, value FROM macro_data WHERE indicator='GOLD_PRICE' "
               "AND country='global' AND value IS NOT NULL")
        if date:
            sql += f" AND date <= '{date}'"
        sql += " ORDER BY date"
        df = self.data.query(sql)
        series = {y: GOLD_PRICE_HIST[y] for y in range(1990, 2025)}
        if not df.empty:
            df["year"] = pd.to_datetime(df["date"]).dt.year
            for y, v in df.groupby("year")["value"].last().items():
                series[int(y)] = float(v)
        return series

    # ---------- indicator 1: 黄金GDP占比 (UP主方法) ----------

    def _gold_gdp_ratio(self, date=None):
        """全部黄金价值 / 全球GDP（UP主方法）。

        全球GDP 分母不受单国货币政策干扰（修复货币黄金/M2 在2020放水期漏判）。
        value=占比%, 均值约9%, 历史峰14-18%。
        """
        try:
            cur_price = self._latest("GOLD_PRICE", "global", date)
            if cur_price is None:
                return self._neutral()
            cur_year = (_date.fromisoformat(date[:10]).year if date else _date.today().year)

            # 历史年度占比序列
            years = sorted(set(GOLD_PRICE_HIST) & set(WORLD_GDP_HIST))
            ratios = []
            for y in years:
                stock = GOLD_STOCK_2024 / (1.017 ** (2024 - y))
                gold_val = stock * TONNES_TO_OZ * GOLD_PRICE_HIST[y] / 1e12  # 万亿USD
                ratios.append(gold_val / WORLD_GDP_HIST[y] * 100)

            # 追加当年（用库里最新全球GDP，失败回退硬编码最新年）
            cur_gdp = self._latest("WORLD_GDP", "global", date) or WORLD_GDP_HIST[max(WORLD_GDP_HIST)]
            stock_now = GOLD_STOCK_2024 * (1.017 ** (cur_year - 2024))
            cur_ratio = stock_now * TONNES_TO_OZ * cur_price / 1e12 / cur_gdp * 100
            ratios.append(cur_ratio)

            r = np.array(ratios)
            pct = float((r < cur_ratio).mean() * 100)
            score = round(max(0.0, min(10.0, pct / 10.0)), 1)
            return {"score": score, "value": round(float(cur_ratio), 1), "percentile": round(pct, 0), "scoring": f"历史分位({len(ratios)}点)"}
        except Exception as e:
            logger.error(f"gold_gdp_ratio failed: {e}")
            return self._neutral()

    # ---------- indicator 2: 实际金价 z-score (金价/CPI) ----------

    def _real_price(self, date=None):
        """金价/CPI(指数) 实际金价的历史 z-score."""
        try:
            price_series = self._gold_price_yearly(date)
            cpi = self.data.query(
                "SELECT date, value FROM macro_data WHERE indicator='CPI_INDEX' "
                "AND country='us' AND value IS NOT NULL ORDER BY date"
            )
            if cpi.empty:
                return self._neutral()
            cpi["year"] = pd.to_datetime(cpi["date"]).dt.year
            yearly_cpi = cpi.groupby("year")["value"].last()

            years = sorted(set(price_series.keys()) & set(int(y) for y in yearly_cpi.index))
            if len(years) < 5:
                return self._neutral()
            real = np.array([price_series[y] / float(yearly_cpi[y]) for y in years])
            z = float((real[-1] - real.mean()) / real.std(ddof=0))
            pct = float((real < real[-1]).mean() * 100)
            score = round(max(0.0, min(10.0, pct / 10.0)), 1)
            return {"score": score, "value": round(z, 2), "percentile": round(pct, 0), "scoring": f"历史分位({len(years)}点)"}
        except Exception as e:
            logger.error(f"gold_real_price failed: {e}")
            return self._neutral()

    # ---------- indicator 3: 金价 MA200 偏离度 ----------

    def _ma200_deviation(self, date=None):
        """(金价 - MA200) / MA200, 用 SGE 日频元/克(币种无关)."""
        try:
            df = self._get_index_data("gold", 250, date)
            if df.empty or len(df) < 30:
                return self._neutral()
            window = min(200, len(df))
            ma = df["close"].rolling(window).mean().iloc[-1]
            cur = float(df["close"].iloc[-1])
            if pd.isna(ma) or ma <= 0:
                return self._neutral()
            dev = (cur - float(ma)) / float(ma)
            score = self._score(dev, "gold_ma200_deviation", "gold")
            return {"score": score, "value": round(float(dev), 3), "percentile": None}
        except Exception as e:
            logger.error(f"gold_ma200_deviation failed: {e}")
            return self._neutral()
