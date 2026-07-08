"""共享 indicator 基础设施: 取数 helper + cn/us 共享的技术指标。

market/<mkt>/indicators.py 的专属 indicator 与本模块的 TechnicalIndicator
都不 import risk —— config 由 pipeline 注入, 算法调 core.scoring。

TechnicalIndicator._ma50_deviation / _volume_shrinkage 搬迁自
risk/indicators/technical.py, 仅适配 4 处依赖:
  1. self.data                            -> data_source 参数
  2. self._get_index_data(market, days, date) -> get_index_series(data_source, self._market, days, date)
  3. self._score_by_percentile(v, hist)   -> score_by_percentile(v, hist)  (本两方法未用到)
  4. self._score(v, name, market)         -> score_with_config(v, name, self._market, self._config)
ma50_deviation 已改为分位打分(近 3 年序列,与其他技术/估值指标口径一致);
volume_shrinkage 算法与 technical.py 一致, 勿改。
"""
import logging

import pandas as pd

from investbrief.core.scoring import moving_average, normalize_score, safe_divide

logger = logging.getLogger(__name__)


def get_index_series(data_source, market: str, days: int = 100, date: str | None = None) -> pd.DataFrame:
    """取该市场主指数日序列(读 market_index_spec, 不依赖 data_source 属于哪个市场)。

    等价于 risk/indicators/base.py:BaseIndicator._get_index_data。
    """
    from investbrief.data import market_index_spec
    spec = market_index_spec(market)
    if spec["kind"] == "macro":
        base = (f"SELECT date, value AS close FROM macro_data "
                f"WHERE indicator='{spec['indicator']}' AND country='{spec['country']}' AND value IS NOT NULL")
        if date:
            return data_source.query(base + " AND date <= ? ORDER BY date DESC LIMIT ?",
                                     (date, days)).iloc[::-1]
        return data_source.query(base + " ORDER BY date DESC LIMIT ?", (days,)).iloc[::-1]
    table, code = spec["table"], spec["code"]
    if date:
        return data_source.query(
            f"SELECT * FROM {table} WHERE code = ? AND date <= ? ORDER BY date DESC LIMIT ?",
            (code, date, days)).iloc[::-1]
    return data_source.query(
        f"SELECT * FROM {table} WHERE code = ? ORDER BY date DESC LIMIT ?", (code, days)).iloc[::-1]


def score_with_config(value, name: str, market: str, config: dict):
    """按 indicator config 打分(等价于原 base.py BaseIndicator._score)。"""
    cfg = config.get(name, {})
    threshold = cfg.get("thresholds", {}).get(market, 0)
    low = cfg.get("low_thresholds", {}).get(market, 0)
    invert = cfg.get("invert", False)
    if invert:
        return normalize_score(value, threshold, threshold * 0.5, invert=True)
    return normalize_score(value, low, threshold)


def percentile_score_from_series(
    data_source,
    table: str,
    column: str,
    where_clause: str,
    date: str | None = None,
    invert: bool = False,
    min_samples: int = 100,
    lookback_years: int = 10,
    round_value: int = 4,
) -> dict:
    """通用分位打分: 取 (table.column, where_clause) 序列的"当前值在近 N 年分位"。

    用于 sentiment_data 列(market_breadth / pledge_ratio / north_flow)和
    macro_data 单列(REAL_YIELD_10Y)——只要表有 date 列、where_clause 能选出唯一序列即可。

    当前值取 latest row(NULL-aware: 若 latest 行该列为 NULL -> value=None -> 退出加权,
    由 models.py:79 的现有机制自动处理)。这样 north_flow 在 2024-08 停发后的最新行
    (north_flow=NULL)自动退出加权, 无需特判。

    where_clause 由调用方硬编码(如 "market='cn'" / "indicator='REAL_YIELD_10Y' AND country='us'"),
    不接受外部输入——避免 SQL 注入。

    返回 dict 与其他 indicator 一致: {score, value, percentile, scoring}。
    """
    from datetime import datetime, timedelta
    import numpy as np
    from investbrief.core.scoring import score_by_percentile

    neutral = {"score": 5.0, "value": None, "percentile": None}
    try:
        ref = date or datetime.now().strftime('%Y-%m-%d')
        start = (datetime.strptime(ref, '%Y-%m-%d') - timedelta(days=365 * lookback_years)).strftime('%Y-%m-%d')

        # Step 1: latest value (NULL-aware — exits weighting when latest row's cell is NULL)
        latest_sql = f"SELECT {column} AS v FROM {table} WHERE {where_clause}"
        if date:
            latest_df = data_source.query(
                latest_sql + " AND date <= ? ORDER BY date DESC LIMIT 1", (date,),
            )
        else:
            latest_df = data_source.query(latest_sql + " ORDER BY date DESC LIMIT 1")
        if latest_df.empty:
            return neutral
        cur_raw = latest_df.iloc[0]["v"]
        if cur_raw is None or pd.isna(cur_raw):
            return neutral  # 停发/缺数 -> 退出加权
        cur = float(cur_raw)

        # Step 2: 历史样本(滤掉 NULL 行)
        hist_sql = (f"SELECT {column} AS v FROM {table} WHERE {where_clause} "
                    f"AND {column} IS NOT NULL AND date >= ?")
        if date:
            hist = data_source.query(hist_sql + " AND date <= ? ORDER BY date", (start, date))
        else:
            hist = data_source.query(hist_sql + " ORDER BY date", (start,))
        if hist.empty or len(hist) < min_samples:
            return neutral
        vals = hist["v"].astype(float).tolist()
        score = score_by_percentile(cur, vals, invert=invert, min_samples=min_samples)
        if score is None:
            return neutral
        pct = float((np.array(vals) < cur).mean() * 100)
        return {
            "score": score,
            "value": round(cur, round_value),
            "percentile": round(pct, 0),
            "scoring": f"近{lookback_years}年分位({len(vals)}点)",
        }
    except Exception as e:
        logger.error(f"percentile_score_from_series({table}.{column}) failed: {e}")
        return neutral


class TechnicalIndicator:
    """cn/us 共享的技术指标(ma50_deviation, volume_shrinkage)。

    从 risk/indicators/technical.py 搬迁: _ma50_deviation + _volume_shrinkage
    方法体逐字保留, 仅适配取数与打分依赖。
    """

    def __init__(self, market: str, config: dict):
        self._market = market
        self._config = config

    def calculate(self, data_source, date: str | None = None) -> dict:
        results = {}
        results["ma50_deviation"] = self._ma50_deviation(data_source, date)
        results["volume_shrinkage"] = self._volume_shrinkage(data_source, date)
        return results

    def _ma50_deviation(self, data_source, date: str | None = None) -> dict:
        """(Close - MA50) / MA50 当前值在近 3 年序列的分位 → 风险分。

        改造自固定阈值 normalize_score(dev, 0, 0.15) → 与其他技术/估值指标
        口径一致的分位打分(score_by_percentile)。"偏离 MA50 多少算超买"是相对的:
        牛市 +15% 常态、震荡市 +8% 罕见, 故用历史分位而非绝对阈值。

        样本: 近 3 年(~750 交易日)每日 ma50_deviation 序列(MA50 warmup 期 NaN 丢弃)。
        高偏离 = 高风险 = 高分(不 invert, 与原 normalize_score 方向一致)。
        样本不足(<100 点) → 回退中性 5.0(与其他 percentile 指标的缺失处理一致)。
        """
        from investbrief.core.scoring import score_by_percentile
        try:
            # 800 自然日 ≈ 750 交易日(~3 年); +50 缓冲 MA50 warmup
            df = get_index_series(data_source, self._market, 800, date)
            if len(df) < 100:
                return {"score": 5.0, "value": None, "percentile": None}

            close = df["close"].astype(float)
            ma50 = moving_average(close, 50)
            deviation = (close - ma50) / ma50
            dev_series = deviation.dropna()
            if len(dev_series) < 100:
                return {"score": 5.0, "value": None, "percentile": None}

            cur = float(dev_series.iloc[-1])
            score = score_by_percentile(cur, dev_series.tolist(), invert=False, min_samples=100)
            if score is None:
                return {"score": 5.0, "value": None, "percentile": None}
            import numpy as np
            pct = float((np.array(dev_series) < cur).mean() * 100)
            return {
                "score": score,
                "value": round(cur, 4),
                "percentile": round(pct, 0),
                "scoring": f"近3年分位({len(dev_series)}点)",
            }
        except Exception as e:
            logger.error(f"Failed to calculate MA50 deviation: {e}")
            return {"score": 5.0, "value": None, "percentile": None}

    def _volume_shrinkage(self, data_source, date: str | None = None) -> dict:
        """5-day avg volume / 30-day avg volume (when index near highs)。

        搬迁自 risk/indicators/technical.py:_volume_shrinkage。
        """
        try:
            df = get_index_series(data_source, self._market, 40, date)
            if len(df) < 30:
                return {"score": 5.0, "value": None, "percentile": None}

            volume = df["volume"].astype(float)
            close = df["close"].astype(float)

            ma5_vol = moving_average(volume, 5)
            ma30_vol = moving_average(volume, 30)

            ratio = safe_divide(float(ma5_vol.iloc[-1]), float(ma30_vol.iloc[-1]))

            # Only score if index is near recent high (within 5% of 30-day high)
            high_30 = float(close.iloc[-30:].max())
            current = float(close.iloc[-1])
            near_high = current >= high_30 * 0.95

            if near_high:
                config = self._config.get("volume_shrinkage", {})
                threshold = config.get("thresholds", {}).get(self._market, 0.7)
                invert = config.get("invert", True)
                score = normalize_score(ratio, threshold * 1.5, threshold, invert=invert)
            else:
                score = 0.0  # Not near highs, no volume risk signal

            return {"score": score, "value": ratio, "percentile": None}
        except Exception as e:
            logger.error(f"Failed to calculate volume shrinkage: {e}")
            return {"score": 5.0, "value": None, "percentile": None}
