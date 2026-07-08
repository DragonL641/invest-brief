"""Gold market 专属 risk indicator + 工厂。

整体搬迁自 risk/indicators/gold.py 的 GoldIndicator 类 + helper + 模块常量 NEUTRAL
(逐字保留计算逻辑, 仅适配依赖)。不 import risk —— config 由 pipeline 注入,
算法调 core.indicators / data 域取数。

迁移范式(适用于本文件所有方法):
  1. self.data                                   -> data_source 参数
  2. self._get_index_data("gold", 250, date)     -> get_index_series(data_source, "gold", 250, date)
                                                    (core.indicators)
  3. self._score(v, name, "gold")                -> score_with_config(v, name, "gold", self._config)
                                                    (core.indicators)
  4. __init__ 从无参改为 __init__(config: dict | None = None), 存 self._config
  5. calculate 签名从 (market, date) 改为 (data_source, date); 删除 market guard
     (gold 子包只服务 gold, 无需再判断)
注: _gold_gdp_ratio / _real_price 的打分仍是内联分位算法(非 _score/_score_by_percentile),
     故不动; 仅 _ma200_deviation 用 _score -> score_with_config。
"""
from datetime import date as _date

import numpy as np
import pandas as pd

from investbrief.data.gold_data import (
    GOLD_PRICE_HIST, WORLD_GDP_HIST,
    GOLD_STOCK_2024, TONNES_TO_OZ,
)
from investbrief.core.indicators import (
    get_index_series, score_with_config, percentile_score_from_series,
)

import logging

logger = logging.getLogger(__name__)

NEUTRAL = {"score": 5.0, "value": None, "percentile": None}


class GoldIndicator:
    """Gold-specific valuation/risk indicators。

    方法体逐字搬迁自 risk/indicators/gold.py, 仅适配取数与打分依赖。
    """

    def __init__(self, config: dict | None = None):
        self._config = config or {}

    def calculate(self, data_source, date=None):
        return {
            "gold_gdp_ratio": self._gold_gdp_ratio(data_source, date),
            "gold_real_price": self._real_price(data_source, date),
            "gold_ma200_deviation": self._ma200_deviation(data_source, date),
            "real_yield": self._real_yield(data_source, date),
        }

    # ---------- indicator 4: 10Y 实际利率 (TIPS) ----------

    def _real_yield(self, data_source, date=None):
        """10Y TIPS 实际利率(macro_data.REAL_YIELD_10Y / country='us')的近10年分位。

        金融逻辑: 实际利率是金价的核心负相关驱动(低实际利率 -> 持金机会成本低 -> 利多金价)。
        对 gold risk 视角: 实际利率处于历史极低分位 = 金价支撑强但可能已透支 = 风险累积,
        故 invert=True(低实际利率 -> 高风险分)。
        """
        return percentile_score_from_series(
            data_source, "macro_data", "value",
            "indicator='REAL_YIELD_10Y' AND country='us'",
            date=date, invert=True, round_value=3,
        )

    # ---------- helpers ----------

    @staticmethod
    def _neutral():
        return dict(NEUTRAL)

    def _latest(self, data_source, indicator, country, date=None):
        sql = (f"SELECT value FROM macro_data WHERE indicator='{indicator}' "
               f"AND country='{country}' AND value IS NOT NULL")
        if date:
            sql += f" AND date <= '{date}'"
        sql += " ORDER BY date DESC LIMIT 1"
        df = data_source.query(sql)
        return float(df.iloc[0]["value"]) if not df.empty else None

    def _gold_price_yearly(self, data_source, date=None):
        """年度金价序列(USD/oz): 硬编码历史(1990-2024) + 库里当年值."""
        sql = ("SELECT date, value FROM macro_data WHERE indicator='GOLD_PRICE' "
               "AND country='global' AND value IS NOT NULL")
        if date:
            sql += f" AND date <= '{date}'"
        sql += " ORDER BY date"
        df = data_source.query(sql)
        series = {y: GOLD_PRICE_HIST[y] for y in range(1990, 2025)}
        if not df.empty:
            df["year"] = pd.to_datetime(df["date"]).dt.year
            for y, v in df.groupby("year")["value"].last().items():
                series[int(y)] = float(v)
        return series

    # ---------- indicator 1: 黄金GDP占比 (UP主方法) ----------

    def _gold_gdp_ratio(self, data_source, date=None):
        """全部黄金价值 / 全球GDP（UP主方法）。

        全球GDP 分母不受单国货币政策干扰（修复货币黄金/M2 在2020放水期漏判）。
        value=占比%, 均值约9%, 历史峰14-18%。
        """
        try:
            cur_price = self._latest(data_source, "GOLD_PRICE", "global", date)
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
            cur_gdp = self._latest(data_source, "WORLD_GDP", "global", date) or WORLD_GDP_HIST[max(WORLD_GDP_HIST)]
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

    def _real_price(self, data_source, date=None):
        """金价/CPI(指数) 实际金价的历史 z-score."""
        try:
            price_series = self._gold_price_yearly(data_source, date)
            cpi = data_source.query(
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

    def _ma200_deviation(self, data_source, date=None):
        """(金价 - MA200) / MA200, 用 SGE 日频元/克(币种无关)."""
        try:
            df = get_index_series(data_source, "gold", 250, date)
            if df.empty or len(df) < 30:
                return self._neutral()
            window = min(200, len(df))
            ma = df["close"].rolling(window).mean().iloc[-1]
            cur = float(df["close"].iloc[-1])
            if pd.isna(ma) or ma <= 0:
                return self._neutral()
            dev = (cur - float(ma)) / float(ma)
            score = score_with_config(dev, "gold_ma200_deviation", "gold", self._config)
            return {"score": score, "value": round(float(dev), 3), "percentile": None}
        except Exception as e:
            logger.error(f"gold_ma200_deviation failed: {e}")
            return self._neutral()


def gold_indicators(data_source, config: dict | None = None) -> list:
    """Gold 市场的全部 indicator 实例(config 由 pipeline 从 load_indicators('gold') 注入)。

    顺序对应 risk/models.py 对 gold 的编排: 仅 GoldIndicator 一个。
    data_source 参数保留以与 cn_indicators/us_indicators 工厂签名一致(GoldIndicator
    自身不持有 data_source, calculate 时显式传入)。
    """
    return [GoldIndicator(config or {})]
