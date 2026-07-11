"""Weighted risk scoring model with state mapping and historical analysis."""

import logging
from datetime import datetime, timedelta

import pandas as pd

from investbrief.risk.config import (
    MARKET_STATE_MAP,
    FIVE_DIMENSIONS, score_to_risk_level,
)
from investbrief.core.scoring import percentile_rank

logger = logging.getLogger(__name__)


class RiskModel:
    """Core risk scoring model that aggregates all indicators.

    Indicators MUST be injected by the caller (assembled per-market by the
    pipeline via ``market/<mkt>/indicators.py`` factories). The legacy
    in-class indicator instantiation was removed together with the old
    ``risk/indicators/`` package.
    """

    def __init__(self, data_source, indicators: list):
        if indicators is None:
            raise ValueError(
                "RiskModel now requires injected indicators "
                "(see pipelines/macro.py:_build_indicators)"
            )
        self.data = data_source
        self._injected_indicators = indicators

    def _primary_series_sql(self, market: str) -> tuple[str, str]:
        """返回 (trading_days_sql, kind)，kind ∈ {'index','macro'}。

        表名/code 从 market_index_spec(market) 查, 不依赖 self.data 属于哪个市场
        (RiskModel 用单一 data_source 算多市场, 表名只能靠 market 选)。
        """
        from investbrief.data import market_index_spec
        spec = market_index_spec(market)
        if spec["kind"] == "macro":
            return (
                f"SELECT DISTINCT date FROM macro_data WHERE indicator='{spec['indicator']}' "
                f"AND country='{spec['country']}' AND date >= ? AND date <= ? ORDER BY date",
                "macro",
            )
        return (
            f"SELECT DISTINCT date FROM {spec['table']} WHERE code = ? "
            f"AND date >= ? AND date <= ? ORDER BY date",
            "index",
        )

    def calculate_score(self, market: str, date: str | None = None) -> dict:
        """Calculate full risk assessment for a market on a given date.

        Returns dict with: total_score, state, crash_prob, expected_return,
        action, dimensions, indicators.
        """
        # Indicators are injected; each implements calculate(data_source, date).
        from investbrief.risk.config import load_indicators
        indicators_config = load_indicators(market)
        all_results = {}
        for ind in self._injected_indicators:
            try:
                all_results.update(ind.calculate(self.data, date))
            except Exception as e:
                logger.warning(f"Indicator {type(ind).__name__} failed: {e}")

        # Weighted sum: 缺失数据(value=None)的指标彻底退出加权, 而非默认5.0中性
        # (历史点很多指标无数据, 若算5.0会稀释顶部该有的高分)
        weighted_sum = 0.0
        total_weight = 0.0
        missing_indicators = []
        spike_indicators = []  # ⑥ 95+分位极端指标
        for name, config in indicators_config.items():
            ind = all_results.get(name)
            if ind is None or ind.get("value") is None:
                # 数据缺失 -> 退出加权 + 记录(供报告显眼标注, 见 docs/methodology ⑦)
                missing_indicators.append({
                    "key": name,
                    "name": config.get("name", name),
                    "weight": config["weight"],
                })
                continue
            score = ind.get("score", 5.0)
            weight = config["weight"]
            # ⑥ 尖刺加权: 95+分位(score>=9.5)指标权重×1.5, 避免极端信号被加权平均稀释
            if score >= 9.5:
                weight *= 1.5
                spike_indicators.append({"name": config.get("name", name), "score": score})
            weighted_sum += score * weight
            total_weight += weight

        total_score = round((weighted_sum / total_weight) * 10, 1) if total_weight > 0 else 50.0
        total_score = max(0.0, min(100.0, total_score))

        # 背离共振加权: macd顶背离 + 广度收缩 同时恶化 -> 风险分放大15%(经典见顶前兆)
        divergence = self._detect_divergence(all_results, market, date)
        if divergence["resonance"]:
            total_score = min(100.0, round(total_score * 1.15, 1))
        if divergence.get("price_fund_divergence"):
            total_score = min(100.0, round(total_score * 1.10, 1))

        # Map to market state
        state_info = self._map_state(total_score)

        # Aggregate five dimensions
        dimensions = self._aggregate_dimensions(market, all_results)

        return {
            "total_score": total_score,
            "state": state_info["state"],
            "crash_prob": state_info["crash_prob"],
            "expected_return": state_info["expected_return"],
            "action": state_info["action"],
            "dimensions": dimensions,
            "indicators": all_results,
            "missing_indicators": missing_indicators,
            "spike_indicators": spike_indicators,
            "divergence_warning": divergence,
            "date": date or datetime.now().strftime("%Y-%m-%d"),
            "market": market,
        }

    def calculate_history(self, market: str, start_date: str, end_date: str) -> pd.DataFrame:
        """Calculate risk scores for every trading day in a date range.

        Returns DataFrame with columns: date, total_score, state
        """
        from investbrief.data import market_index_spec
        sql, kind = self._primary_series_sql(market)
        if kind == "macro":
            trading_days = self.data.query(sql, (start_date, end_date))
        else:
            code = market_index_spec(market)["code"]
            trading_days = self.data.query(sql, (code, start_date, end_date))

        if trading_days.empty:
            return pd.DataFrame(columns=["date", "total_score", "state"])

        results = []
        for _, row in trading_days.iterrows():
            day = row["date"]
            try:
                score_data = self.calculate_score(market, day)
                count_high = sum(1 for v in score_data["indicators"].values()
                                 if v.get("value") is not None and (v.get("score") or 0) >= 8)
                results.append({
                    "date": day,
                    "total_score": score_data["total_score"],
                    "state": score_data["state"],
                    "count_high": count_high,
                })
            except Exception as e:
                logger.warning(f"Failed to calculate score for {day}: {e}")

        return pd.DataFrame(results)

    def historical_percentile(self, market: str, current_score: float, history_df: pd.DataFrame = None) -> float:
        """Calculate percentile of current score within 10-year history."""
        try:
            if history_df is None:
                ten_years_ago = (datetime.now() - timedelta(days=3650)).strftime("%Y-%m-%d")
                today = datetime.now().strftime("%Y-%m-%d")
                history = self.calculate_history(market, ten_years_ago, today)
            else:
                history = history_df
            if history.empty:
                return 50.0

            return percentile_rank(current_score, history["total_score"])
        except Exception as e:
            logger.error(f"Failed to calculate historical percentile: {e}")
            return 50.0

    def find_similar_periods(self, market: str, current_score: float, top_n: int = 5, history_df: pd.DataFrame = None) -> list[dict]:
        """Find historical periods with closest risk scores."""
        try:
            if history_df is None:
                ten_years_ago = (datetime.now() - timedelta(days=3650)).strftime("%Y-%m-%d")
                today = datetime.now().strftime("%Y-%m-%d")
                history = self.calculate_history(market, ten_years_ago, today)
            else:
                history = history_df
            if history.empty:
                return []

            history = history.assign(score_diff=abs(history["total_score"] - current_score))
            closest = history.nsmallest(top_n, "score_diff")

            results = []
            from investbrief.data import market_index_spec
            spec = market_index_spec(market)
            if spec["kind"] == "macro":
                sql_future = (f"SELECT value AS close FROM macro_data WHERE indicator='{spec['indicator']}' "
                              f"AND country='{spec['country']}' AND date > ? ORDER BY date LIMIT 63")
                sql_now = (f"SELECT value AS close FROM macro_data WHERE indicator='{spec['indicator']}' "
                           f"AND country='{spec['country']}' AND date >= ? ORDER BY date LIMIT 1")
                p_future = lambda d: (d,)
                p_now = lambda d: (d,)
            else:
                table, code = spec["table"], spec["code"]
                sql_future = f"SELECT close FROM {table} WHERE code = ? AND date > ? ORDER BY date LIMIT 63"
                sql_now = f"SELECT close FROM {table} WHERE code = ? AND date >= ? ORDER BY date LIMIT 1"
                p_future = lambda d: (code, d)
                p_now = lambda d: (code, d)

            for _, row in closest.iterrows():
                date = row["date"]
                # Get subsequent 3-month return
                future = self.data.query(sql_future, p_future(date))
                current_price = self.data.query(sql_now, p_now(date))

                subsequent_return = None
                if len(future) >= 63 and not current_price.empty:
                    p0 = float(current_price.iloc[0]["close"])
                    p1 = float(future.iloc[62]["close"])
                    subsequent_return = round((p1 - p0) / p0 * 100, 2)

                results.append({
                    "date": date,
                    "total_score": row["total_score"],
                    "state": row["state"],
                    "subsequent_3m_return": subsequent_return,
                })

            return results
        except Exception as e:
            logger.error(f"Failed to find similar periods: {e}")
            return []

    def _map_state(self, score: float) -> dict:
        """Map total score to market state."""
        for i, (score_min, score_max, state, crash_prob, expected_return, action) in enumerate(MARKET_STATE_MAP):
            is_last = i == len(MARKET_STATE_MAP) - 1
            if is_last:
                matched = score >= score_min
            else:
                matched = score_min <= score < score_max
            if matched:
                return {
                    "state": state,
                    "crash_prob": crash_prob,
                    "expected_return": expected_return,
                    "action": action,
                    "risk_level": score_to_risk_level(score),
                }
        # Unreachable: the last range in MARKET_STATE_MAP always matches
        return None

    def _aggregate_dimensions(self, market: str, all_results: dict) -> dict:
        """Aggregate indicator scores into five dimensions for radar chart."""
        dimensions = {}
        for dim_name, dim_indicators in FIVE_DIMENSIONS.items():
            if isinstance(dim_indicators, dict):
                indicator_list = dim_indicators.get(market, [])
            else:
                indicator_list = dim_indicators

            scores = []
            for ind_name in indicator_list:
                if ind_name in all_results:
                    score = all_results[ind_name].get("score", 5.0)
                    scores.append(score)

            if not scores:
                logger.warning(f"No indicator data for dimension '{dim_name}' in market '{market}'")

            avg_score = round(sum(scores) / len(scores), 2) if scores else 5.0
            dimensions[dim_name] = avg_score

        return dimensions

    def _detect_divergence(self, results: dict, market: str = None, date: str = None) -> dict:
        """检测两类见顶背离, 任一触发都对风险分加权放大。

        1. 量价背离共振: 价格超买(ma50偏离大) + 量能萎缩 = 上涨乏力(经典见顶前兆)
           ma50_deviation score高=偏离大=超买; volume_shrinkage score高=缩量; 两者同时>=7 => 共振。
        2. 价格-资金背离 ⑤(跨维度: 指数处近60日高位 + 融资余额近20日下降 = 上涨缺资金支撑)
        """
        THRESH = 7.0
        ma50 = float(results.get("ma50_deviation", {}).get("score", 0.0) or 0.0)
        volume = float(results.get("volume_shrinkage", {}).get("score", 0.0) or 0.0)
        resonance = ma50 >= THRESH and volume >= THRESH
        price_fund = self._detect_price_fund_divergence(market, date)

        if resonance and price_fund:
            level = "red"
        elif resonance or price_fund:
            level = "yellow"
        else:
            level = "green"
        return {
            "resonance": resonance,
            "price_fund_divergence": price_fund,
            "level": level,
            "ma50_score": round(ma50, 1),
            "volume_score": round(volume, 1),
        }

    def _detect_price_fund_divergence(self, market: str, date: str | None) -> bool:
        """⑤ 价格-资金背离: 指数处近60日高位 + 融资余额近20日下降。

        仅 cn(融资余额口径)。
        backtest 注: 结构市(21顶)两融不高, 此信号主要捕捉全面顶, 结构市可能失效。
        """
        if market != "cn":
            return False
        try:
            # RiskModel 无 _get_index_data, 直接query近60日上证close
            isql = ("SELECT date, close FROM cn_index_daily WHERE code='sh000001' "
                    "AND close IS NOT NULL")
            if date:
                idf = self.data.query(isql + " AND date <= ? ORDER BY date DESC LIMIT 60", (date,))
            else:
                idf = self.data.query(isql + " ORDER BY date DESC LIMIT 60")
            if idf.empty or len(idf) < 20:
                return False
            close = idf["close"].astype(float).iloc[::-1]  # 升序(旧->新)
            price_near_high = float(close.iloc[-1]) >= float(close.quantile(0.95))

            sql = ("SELECT margin_balance FROM sentiment_data WHERE market='cn' "
                   "AND margin_balance IS NOT NULL")
            if date:
                mdf = self.data.query(sql + " AND date <= ? ORDER BY date DESC LIMIT 30", (date,))
            else:
                mdf = self.data.query(sql + " ORDER BY date DESC LIMIT 30")
            if mdf.empty or len(mdf) < 20:
                return False
            margin = mdf["margin_balance"].astype(float).iloc[::-1]  # 升序(旧->新)
            margin_declining = float(margin.iloc[-1]) < float(margin.iloc[-20])
            return bool(price_near_high and margin_declining)
        except Exception as e:
            logger.warning(f"price-fund divergence detection failed: {e}")
            return False
