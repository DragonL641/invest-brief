"""A股数据客户端，基于 AKShare。"""

import logging
import os
import time
import threading
from typing import Any
from datetime import datetime, timedelta

os.environ["TQDM_DISABLE"] = "1"

import akshare as ak
import pandas as pd

logger = logging.getLogger(__name__)


class _DataFrameCache:
    """Thread-safe TTL cache for AKShare full-universe DataFrames."""

    def __init__(self):
        self._store: dict[str, tuple[float, pd.DataFrame]] = {}
        self._lock = threading.Lock()

    def get(self, key: str, ttl: int) -> pd.DataFrame | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            ts, df = entry
            if time.monotonic() - ts > ttl:
                del self._store[key]
                return None
            return df

    def set(self, key: str, df: pd.DataFrame):
        with self._lock:
            self._store[key] = (time.monotonic(), df)


_df_cache = _DataFrameCache()


def _safe_float(val) -> float | None:
    """安全转换为 float。"""
    if val is None or val == "-" or val == "":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


class AKShareClient:
    """封装 AKShare 接口，提供统一的 A 股数据获取方法。

    每个方法内部做异常处理和空值兜底，单个接口失败不影响整体。
    """

    # ---- 指数 ----

    def _get_all_indices_df(self) -> pd.DataFrame | None:
        """获取全量指数 DataFrame（带缓存，TTL 5 分钟）。"""
        df = _df_cache.get("zh_index_spot", 300)
        if df is not None:
            return df
        df = ak.stock_zh_index_spot_em()
        if df is not None and not df.empty:
            _df_cache.set("zh_index_spot", df)
        return df

    def get_index_quote(self, symbol: str) -> dict[str, Any] | None:
        """获取指数实时行情。symbol: 如 "000001"（上证指数）。"""
        try:
            df = self._get_all_indices_df()
            if df is None or df.empty:
                return None
            row = df[df["代码"] == symbol]
            if row.empty:
                return None
            r = row.iloc[0]
            return {
                "symbol": symbol,
                "name": str(r.get("名称", "")),
                "price": self._safe_float(r.get("最新价")),
                "change": self._safe_float(r.get("涨跌额")),
                "change_pct": self._safe_float(r.get("涨跌幅")),
                "volume": self._safe_float(r.get("成交量")),
                "amount": self._safe_float(r.get("成交额")),
            }
        except Exception as e:
            logger.warning(f"AKShare get_index_quote failed for {symbol}: {e}")
            return None

    def get_index_quotes(self, symbols: list[str]) -> list[dict[str, Any]]:
        """批量获取指数实时行情。"""
        try:
            df = self._get_all_indices_df()
            if df is None or df.empty:
                return []
            results = []
            for symbol in symbols:
                row = df[df["代码"] == symbol]
                if row.empty:
                    continue
                r = row.iloc[0]
                results.append({
                    "symbol": symbol,
                    "name": str(r.get("名称", "")),
                    "price": self._safe_float(r.get("最新价")),
                    "change": self._safe_float(r.get("涨跌额")),
                    "change_pct": self._safe_float(r.get("涨跌幅")),
                    "volume": self._safe_float(r.get("成交量")),
                    "amount": self._safe_float(r.get("成交额")),
                })
            return results
        except Exception as e:
            logger.warning(f"AKShare get_index_quotes failed: {e}")
            return []

    # ---- 个股行情 ----

    def _get_all_stocks_df(self) -> pd.DataFrame | None:
        """获取全量 A 股 DataFrame（带缓存，TTL 5 分钟）。"""
        df = _df_cache.get("zh_a_spot", 300)
        if df is not None:
            return df
        df = ak.stock_zh_a_spot_em()
        if df is not None and not df.empty:
            _df_cache.set("zh_a_spot", df)
        return df

    def get_stock_quote(self, symbol: str) -> dict[str, Any] | None:
        """获取个股实时行情。symbol: 6位代码如 "600519"。"""
        try:
            df = self._get_all_stocks_df()
            if df is None or df.empty:
                return None
            row = df[df["代码"] == symbol]
            if row.empty:
                return None
            r = row.iloc[0]
            return self._parse_stock_row(r)
        except Exception as e:
            logger.warning(f"AKShare get_stock_quote failed for {symbol}: {e}")
            return None

    def get_stock_quotes(self, symbols: list[str]) -> list[dict[str, Any]]:
        """批量获取个股实时行情。"""
        try:
            df = self._get_all_stocks_df()
            if df is None or df.empty:
                return []
            symbol_set = set(symbols)
            filtered = df[df["代码"].isin(symbol_set)]
            results = []
            for _, r in filtered.iterrows():
                results.append(self._parse_stock_row(r))
            return results
        except Exception as e:
            logger.warning(f"AKShare get_stock_quotes failed: {e}")
            return []

    def _parse_stock_row(self, r: "pd.Series") -> dict[str, Any]:
        """解析单行个股数据为标准 dict。"""
        return {
            "symbol": str(r.get("代码", "")),
            "name": str(r.get("名称", "")),
            "price": self._safe_float(r.get("最新价")),
            "change": self._safe_float(r.get("涨跌额")),
            "change_pct": self._safe_float(r.get("涨跌幅")),
            "open": self._safe_float(r.get("今开")),
            "high": self._safe_float(r.get("最高")),
            "low": self._safe_float(r.get("最低")),
            "volume": self._safe_float(r.get("成交量")),
            "amount": self._safe_float(r.get("成交额")),
            "market_cap": self._safe_float(r.get("总市值")),
            "pe": self._safe_float(r.get("市盈率-动态")),
            "turnover_rate": self._safe_float(r.get("换手率")),
        }

    # ---- 历史K线 ----

    def get_stock_history(self, symbol: str, days: int = 180) -> pd.DataFrame | None:
        """获取个股日K线（前复权）。"""
        try:
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
            df = ak.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust="qfq",
            )
            if df is None or df.empty:
                return None
            df = df.rename(columns={
                "日期": "date", "股票代码": "symbol",
                "开盘": "open", "收盘": "close",
                "最高": "high", "最低": "low",
                "成交量": "volume", "成交额": "amount",
                "振幅": "amplitude", "涨跌幅": "change_pct",
                "涨跌额": "change", "换手率": "turnover",
            })
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date")
            return df
        except Exception as e:
            logger.warning(f"AKShare get_stock_history failed for {symbol}: {e}")
            return None

    # ---- 研报与财务 ----

    def get_research_reports(self, symbol: str, limit: int = 10) -> list[dict[str, Any]]:
        """获取个股研报列表。"""
        try:
            df = ak.stock_research_report_em(symbol=symbol)
            if df is None or df.empty:
                return []
            df = df.head(limit)
            results = []
            for _, r in df.iterrows():
                results.append({
                    "title": str(r.get("报告名称", "")),
                    "rating": str(r.get("东财评级", "")),
                    "target_price": None,  # 东财研报接口无直接目标价字段
                    "institution": str(r.get("机构", "")),
                    "analyst": "",  # 接口不提供分析师姓名
                    "date": str(r.get("日期", "")),
                })
            return results
        except Exception as e:
            logger.warning(f"AKShare get_research_reports failed for {symbol}: {e}")
            return []

    _RATING_MAP: dict[str, str] = {
        "买入": "buy", "强烈推荐": "buy", "推荐": "buy",
        "增持": "outperform", "优于大市": "outperform",
        "中性": "neutral", "持有": "neutral", "观望": "neutral",
        "减持": "underperform", "落后大市": "underperform",
        "卖出": "sell",
    }

    def _count_rating_distribution(self, df: "pd.DataFrame") -> dict[str, int]:
        """统计给定 DataFrame 的研报评级分布（东财评级 → 标准桶）。"""
        counts = {"buy": 0, "outperform": 0, "neutral": 0, "underperform": 0, "sell": 0}
        for _, r in df.iterrows():
            en = self._RATING_MAP.get(str(r.get("东财评级", "")), "")
            if en:
                counts[en] += 1
        return counts

    def get_analyst_rating_summary(self, symbol: str, days: int = 90) -> dict[str, Any] | None:
        """汇总近 `days` 天研报评级分布 + 盈利预测一致预期 + 评级变化（vs 上一 `days` 周期）。

        akshare 帧顺序不稳定，先解析日期+排序。`change` 是各评级桶占比的 pct-point
        变化（正=近期更偏多）。盈利预测一致预期仍用全量数据。
        """
        try:
            df = ak.stock_research_report_em(symbol=symbol)
            if df is None or df.empty:
                return None

            df = df.copy()
            df["_dt"] = pd.to_datetime(df.get("日期"), errors="coerce")
            df = df.sort_values("_dt", ascending=False)

            now = pd.Timestamp.now()
            recent_cutoff = now - pd.Timedelta(days=days)
            prev_cutoff = recent_cutoff - pd.Timedelta(days=days)
            df_recent = df[df["_dt"] >= recent_cutoff]
            df_prev = df[(df["_dt"] >= prev_cutoff) & (df["_dt"] < recent_cutoff)]

            recent_counts = self._count_rating_distribution(df_recent)
            prev_counts = self._count_rating_distribution(df_prev)

            all_buckets = ("buy", "outperform", "neutral", "underperform", "sell")
            r_tot = sum(recent_counts.values()) or 1
            p_tot = sum(prev_counts.values()) or 1
            change = {k: round(recent_counts[k] / r_tot * 100 - prev_counts[k] / p_tot * 100, 1)
                      for k in all_buckets}

            # 盈利预测一致预期（用全量数据，按年份聚合 EPS 和 PE）
            eps_forecasts: dict[str, list[float]] = {}
            pe_forecasts: dict[str, list[float]] = {}
            institutions: set[str] = set()
            import re as _re
            for _, r in df.iterrows():
                inst = str(r.get("机构", ""))
                if inst:
                    institutions.add(inst)
                for col in df.columns:
                    val = pd.to_numeric(r.get(col), errors="coerce")
                    if pd.isna(val):
                        continue
                    if "盈利预测-收益" in col:
                        m = _re.match(r"(\d{4})", col)
                        year = m.group(1) if m else col.split("-")[0][:4]
                        eps_forecasts.setdefault(year, []).append(float(val))
                    elif "盈利预测-市盈率" in col:
                        m = _re.match(r"(\d{4})", col)
                        year = m.group(1) if m else col.split("-")[0][:4]
                        pe_forecasts.setdefault(year, []).append(float(val))

            consensus: list[dict] = []
            for year in sorted(set(eps_forecasts) | set(pe_forecasts)):
                eps_vals = eps_forecasts.get(year, [])
                pe_vals = pe_forecasts.get(year, [])
                entry: dict[str, Any] = {"year": year}
                if eps_vals:
                    entry["eps_avg"] = round(sum(eps_vals) / len(eps_vals), 2)
                if pe_vals:
                    entry["pe_avg"] = round(sum(pe_vals) / len(pe_vals), 1)
                if len(eps_vals) >= 2:
                    entry["eps_growth"] = round(
                        (max(eps_vals) - min(eps_vals)) / entry["eps_avg"] * 100, 1
                    )
                consensus.append(entry)

            growth_rates: list[float] = []
            for i in range(1, len(consensus)):
                prev = consensus[i - 1].get("eps_avg")
                curr = consensus[i].get("eps_avg")
                if prev and curr and prev > 0:
                    growth_rates.append(round((curr - prev) / prev * 100, 1))

            return {
                **recent_counts,
                "total_reports": len(df_recent),
                "total_reports_all": len(df),
                "institutions": len(institutions),
                "change": change,
                "consensus": consensus,
                "eps_growth_rates": growth_rates,
                "days": days,
            }
        except Exception as e:
            logger.warning(f"AKShare get_analyst_rating_summary failed for {symbol}: {e}")
            return None

    def get_financial_indicators(self, symbol: str) -> dict[str, Any] | None:
        """获取个股最新财务指标（来自同花顺）。"""
        try:
            df = ak.stock_financial_abstract_ths(symbol=symbol)
            if df is None or df.empty:
                return None
            # 取最近一期报告（DataFrame 按时间升序排列，最后一条最新）
            r = df.iloc[-1]
            return {
                "eps": self._safe_float(r.get("基本每股收益")),
                "roe": self._parse_pct(r.get("净资产收益率")),
                "revenue_growth": self._parse_pct(r.get("营业总收入同比增长率")),
                "profit_growth": self._parse_pct(r.get("净利润同比增长率")),
                "gross_margin": self._parse_pct(r.get("销售毛利率")),
                "net_margin": self._parse_pct(r.get("销售净利率")),
                "debt_ratio": self._parse_pct(r.get("资产负债率")),
                "report_date": str(r.get("报告期", "")),
            }
        except Exception as e:
            logger.warning(f"AKShare get_financial_indicators failed for {symbol}: {e}")
            return None

    @staticmethod
    def _parse_pct(val) -> float | None:
        """将 '23.38%' 或纯数字转为 float（去掉百分号）。"""
        if val is None or val == "-" or val == "" or val is False:
            return None
        try:
            s = str(val).replace("%", "").strip()
            return float(s)
        except (ValueError, TypeError):
            return None

    # ---- 高管与股东变动 ----

    def _get_all_insider_trades_df(self) -> pd.DataFrame | None:
        """获取全量高管持股变动 DataFrame（带缓存，TTL 30 分钟）。"""
        df = _df_cache.get("insider_trades", 1800)
        if df is not None:
            return df
        df = ak.stock_ggcg_em(symbol="全部")
        if df is not None and not df.empty:
            _df_cache.set("insider_trades", df)
        return df

    def get_insider_trades(self, symbol: str, days: int = 30) -> list[dict[str, Any]]:
        """获取高管持股变动（东方财富）。

        调用 stock_ggcg_em() 拿全量数据，按代码和日期过滤。
        """
        try:
            df = self._get_all_insider_trades_df()
            if df is None or df.empty:
                return []
            cutoff = (datetime.now() - timedelta(days=days)).date()
            df = df[df["代码"] == symbol]
            df = df[df["公告日"].apply(lambda x: x.date() if hasattr(x, "date") else x) >= cutoff]
            results = []
            for _, r in df.iterrows():
                action = str(r.get("持股变动信息-增减", ""))
                if "增" not in action:
                    continue
                results.append({
                    "name": str(r.get("名称", "")),
                    "position": str(r.get("股东名称", "")),
                    "action": action,
                    "shares": self._safe_float(r.get("持股变动信息-变动数量")),
                    "amount": None,
                    "date": str(r.get("公告日", "")),
                })
            return results
        except Exception as e:
            logger.warning(f"AKShare get_insider_trades failed for {symbol}: {e}")
            return []

    def get_major_shareholder_trades(self, symbol: str, days: int = 90) -> list[dict[str, Any]]:
        """获取大股东增减持变动（同花顺）。

        调用 stock_shareholder_change_ths()，返回历史全量数据，按日期过滤。
        """
        try:
            df = ak.stock_shareholder_change_ths(symbol=symbol)
            if df is None or df.empty:
                return []
            cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            df["公告日期"] = df["公告日期"].astype(str)
            df = df[df["公告日期"] >= cutoff]
            results = []
            for _, r in df.iterrows():
                results.append({
                    "shareholder": str(r.get("变动股东", "")),
                    "action": str(r.get("变动数量", "")),
                    "shares": None,  # 同花顺返回的是 "增持4.16万" 文本，不是数值
                    "amount": None,
                    "date": str(r.get("公告日期", "")),
                })
            return results
        except Exception as e:
            logger.warning(
                f"AKShare get_major_shareholder_trades failed for {symbol}: {e}"
            )
            return []

    # ---- 龙虎榜 ----

    def get_dragon_tiger_list(self, days: int = 5) -> list[dict[str, Any]]:
        """获取龙虎榜数据。

        遍历最近 days 个交易日，逐日调用 stock_lhb_detail_em()，汇总结果。
        """
        try:
            results = []
            end = datetime.now()
            for i in range(days):
                d = end - timedelta(days=i)
                date_str = d.strftime("%Y%m%d")
                try:
                    df = ak.stock_lhb_detail_em(
                        start_date=date_str, end_date=date_str
                    )
                    if df is None or df.empty:
                        continue
                except Exception:
                    # 非交易日或接口异常，跳过
                    continue
                for _, r in df.iterrows():
                    results.append({
                        "symbol": str(r.get("代码", "")),
                        "name": str(r.get("名称", "")),
                        "change_pct": self._safe_float(r.get("涨跌幅")),
                        "buy_amount": self._safe_float(r.get("龙虎榜买入额")),
                        "sell_amount": self._safe_float(r.get("龙虎榜卖出额")),
                        "net_buy": self._safe_float(r.get("龙虎榜净买额")),
                        "reason": str(r.get("上榜原因", "")),
                        "date": str(r.get("上榜日", "")),
                    })
            return results
        except Exception as e:
            logger.warning(f"AKShare get_dragon_tiger_list failed: {e}")
            return []

    # ---- 机构调研 ----

    def get_institutional_research_batch(
        self, symbols: list[str], days: int = 7
    ) -> dict[str, list[dict[str, Any]]]:
        """批量获取多只股票的机构调研统计，只遍历一次日期。"""
        symbol_set = set(symbols)
        all_results: dict[str, list[dict[str, Any]]] = {s: [] for s in symbols}
        seen: set[str] = set()
        end = datetime.now()
        for i in range(days):
            d = end - timedelta(days=i)
            date_str = d.strftime("%Y%m%d")
            try:
                df = ak.stock_jgdy_tj_em(date=date_str)
                if df is None or df.empty:
                    continue
                df = df[df["代码"].isin(symbol_set)]
                for _, r in df.iterrows():
                    sym = str(r.get("代码", ""))
                    date_val = str(r.get("接待日期", ""))
                    key = f"{sym}_{date_val}"
                    if key in seen:
                        continue
                    seen.add(key)
                    all_results.setdefault(sym, []).append({
                        "institution": str(r.get("接待机构数量", "")),
                        "date": date_val,
                        "type": str(r.get("接待方式", "")),
                        "researchers": str(r.get("接待人员", "")),
                    })
            except Exception:
                continue
        return all_results

    def get_institutional_research(
        self, symbol: str, days: int = 7
    ) -> list[dict[str, Any]]:
        """获取个股机构调研统计（东方财富）。

        调用 stock_jgdy_tj_em() 按日期拉取，过滤指定代码。
        注意：该接口按日期分页，需要遍历多个日期。
        """
        try:
            results = []
            seen_dates: set[str] = set()
            end = datetime.now()
            cutoff = (end - timedelta(days=days)).strftime("%Y%m%d")
            # 遍历最近 days 天，逐日查询
            for i in range(days):
                d = end - timedelta(days=i)
                date_str = d.strftime("%Y%m%d")
                try:
                    df = ak.stock_jgdy_tj_em(date=date_str)
                    if df is None or df.empty:
                        continue
                except Exception:
                    continue
                df = df[df["代码"] == symbol]
                for _, r in df.iterrows():
                    date_val = str(r.get("接待日期", ""))
                    key = f"{symbol}_{date_val}"
                    if key in seen_dates:
                        continue
                    seen_dates.add(key)
                    results.append({
                        "institution": str(r.get("接待机构数量", "")),
                        "date": date_val,
                        "type": str(r.get("接待方式", "")),
                        "researchers": str(r.get("接待人员", "")),
                    })
            return results
        except Exception as e:
            logger.warning(
                f"AKShare get_institutional_research failed for {symbol}: {e}"
            )
            return []

    # ---- 个股新闻 ----

    def get_stock_news(self, symbol: str, limit: int = 20) -> list[dict[str, Any]]:
        """获取个股新闻（东方财富）。"""
        try:
            df = ak.stock_news_em(symbol=symbol)
            if df is None or df.empty:
                return []
            df = df.head(limit)
            results = []
            for _, r in df.iterrows():
                results.append({
                    "title": str(r.get("新闻标题", "")),
                    "content": str(r.get("新闻内容", "")),
                    "url": str(r.get("新闻链接", "")),
                    "date": str(r.get("发布时间", "")),
                    "source": str(r.get("文章来源", "")),
                })
            return results
        except Exception as e:
            logger.warning(f"AKShare get_stock_news failed for {symbol}: {e}")
            return []

    # ---- 主力资金 ----

    def get_stock_fund_flow(self, symbol: str) -> dict[str, Any] | None:
        """获取个股最新主力资金流向。

        market 从代码推断: 6 开头=sh, 其他=sz。
        """
        try:
            market = "sh" if symbol.startswith("6") else "sz"
            df = ak.stock_individual_fund_flow(stock=symbol, market=market)
            if df is None or df.empty:
                return None
            r = df.iloc[-1]
            return {
                "date": str(r.get("日期", "")),
                "main_net": self._safe_float(r.get("主力净流入-净额")),
                "main_pct": self._safe_float(r.get("主力净流入-净占比")),
                "huge_net": self._safe_float(r.get("超大单净流入-净额")),
                "huge_pct": self._safe_float(r.get("超大单净流入-净占比")),
                "big_net": self._safe_float(r.get("大单净流入-净额")),
                "big_pct": self._safe_float(r.get("大单净流入-净占比")),
            }
        except Exception as e:
            logger.warning(f"AKShare get_stock_fund_flow failed for {symbol}: {e}")
            return None

    def get_sector_performance(self, sector_names: list[str]) -> list[dict[str, Any]]:
        """获取指定行业板块的涨跌幅表现。"""
        try:
            df = ak.stock_board_industry_name_em()
            if df is None or df.empty:
                return []
            results = []
            for name in sector_names:
                matched = df[df["板块名称"] == name]
                if matched.empty:
                    continue
                r = matched.iloc[0]
                results.append({
                    "name": name,
                    "change_pct": self._safe_float(r.get("涨跌幅")),
                    "up_count": self._safe_float(r.get("上涨家数")),
                    "down_count": self._safe_float(r.get("下跌家数")),
                    "leader": str(r.get("领涨股票", "")),
                    "leader_change": self._safe_float(r.get("领涨股票-涨跌幅")),
                })
            return results
        except Exception as e:
            logger.warning(f"AKShare get_sector_performance failed: {e}")
            return []

    def get_industry_stocks(self, board_name: str) -> list[dict[str, Any]]:
        """获取行业板块成分股列表。"""
        try:
            df = ak.stock_board_industry_cons_em(symbol=board_name)
            if df is None or df.empty:
                return []
            results = []
            for _, r in df.iterrows():
                results.append({
                    "symbol": str(r.get("代码", "")),
                    "name": str(r.get("名称", "")),
                    "price": self._safe_float(r.get("最新价")),
                    "change_pct": self._safe_float(r.get("涨跌幅")),
                    "change_amt": self._safe_float(r.get("涨跌额")),
                    "turnover_rate": self._safe_float(r.get("换手率")),
                    "pe": self._safe_float(r.get("市盈率-动态")),
                    "pb": self._safe_float(r.get("市净率")),
                    "volume": self._safe_float(r.get("成交量")),
                    "amount": self._safe_float(r.get("成交额")),
                })
            return results
        except Exception as e:
            logger.warning(f"AKShare get_industry_stocks failed for {board_name}: {e}")
            return []

    def get_all_fund_flow(self) -> dict[str, dict[str, Any]]:
        """获取全 A 股资金流向排名（今日）。"""
        try:
            df = ak.stock_individual_fund_flow_rank(indicator="今日")
            if df is None or df.empty:
                return {}
            results: dict[str, dict[str, Any]] = {}
            for _, r in df.iterrows():
                symbol = str(r.get("代码", ""))
                results[symbol] = {
                    "main_net": self._safe_float(r.get("今日主力净流入-净额")),
                    "main_pct": self._safe_float(r.get("今日主力净流入-净占比")),
                    "huge_net": self._safe_float(r.get("今日超大单净流入-净额")),
                    "huge_pct": self._safe_float(r.get("今日超大单净流入-净占比")),
                    "big_net": self._safe_float(r.get("今日大单净流入-净额")),
                    "big_pct": self._safe_float(r.get("今日大单净流入-净占比")),
                }
            return results
        except Exception as e:
            logger.warning(f"AKShare get_all_fund_flow failed: {e}")
            return {}

    # ---- ETF ----

    def _get_all_etf_df(self) -> pd.DataFrame | None:
        """获取全量 ETF DataFrame（带缓存，TTL 5 分钟）。"""
        df = _df_cache.get("etf_spot", 300)
        if df is not None:
            return df
        df = ak.fund_etf_spot_em()
        if df is not None and not df.empty:
            _df_cache.set("etf_spot", df)
        return df

    def get_etf_spot(self, symbol: str) -> dict[str, Any] | None:
        """获取单只 ETF 实时行情。symbol: 6位代码如 "510300"。"""
        try:
            df = self._get_all_etf_df()
            if df is None or df.empty:
                return None
            row = df[df["代码"] == symbol]
            if row.empty:
                return None
            r = row.iloc[0]
            return {
                "symbol": symbol,
                "name": str(r.get("名称", "")),
                "price": self._safe_float(r.get("最新价")),
                "change": self._safe_float(r.get("涨跌额")),
                "change_pct": self._safe_float(r.get("涨跌幅")),
                "open": self._safe_float(r.get("今开")),
                "high": self._safe_float(r.get("最高")),
                "low": self._safe_float(r.get("最低")),
                "volume": self._safe_float(r.get("成交量")),
                "amount": self._safe_float(r.get("成交额")),
                "turnover_rate": self._safe_float(r.get("换手率")),
                "pe": self._safe_float(r.get("市盈率-动态")),
                "iopv": self._safe_float(r.get("IOPV实时估值")),
                "premium_rate": self._safe_float(r.get("基金折价率")),
                "main_net_flow": self._safe_float(r.get("主力净流入-净额")),
                "main_net_pct": self._safe_float(r.get("主力净流入-净占比")),
                "huge_net_flow": self._safe_float(r.get("超大单净流入-净额")),
                "big_net_flow": self._safe_float(r.get("大单净流入-净额")),
                "medium_net_flow": self._safe_float(r.get("中单净流入-净额")),
                "small_net_flow": self._safe_float(r.get("小单净流入-净额")),
                "shares_outstanding": self._safe_float(r.get("流通市值")),
                "total_market_cap": self._safe_float(r.get("总市值")),
            }
        except Exception as e:
            logger.warning(f"AKShare get_etf_spot failed for {symbol}: {e}")
            return None

    def get_etf_spot_batch(self, symbols: list[str]) -> list[dict[str, Any]]:
        """批量获取 ETF 实时行情（一次调用，多次过滤）。"""
        try:
            df = self._get_all_etf_df()
            if df is None or df.empty:
                return []
            symbol_set = set(symbols)
            filtered = df[df["代码"].isin(symbol_set)]
            results = []
            for _, r in filtered.iterrows():
                sym = str(r.get("代码", ""))
                results.append({
                    "symbol": sym,
                    "name": str(r.get("名称", "")),
                    "price": self._safe_float(r.get("最新价")),
                    "change": self._safe_float(r.get("涨跌额")),
                    "change_pct": self._safe_float(r.get("涨跌幅")),
                    "turnover_rate": self._safe_float(r.get("换手率")),
                    "iopv": self._safe_float(r.get("IOPV实时估值")),
                    "premium_rate": self._safe_float(r.get("基金折价率")),
                    "main_net_flow": self._safe_float(r.get("主力净流入-净额")),
                    "main_net_pct": self._safe_float(r.get("主力净流入-净占比")),
                    "amount": self._safe_float(r.get("成交额")),
                    "total_market_cap": self._safe_float(r.get("总市值")),
                })
            return results
        except Exception as e:
            logger.warning(f"AKShare get_etf_spot_batch failed: {e}")
            return []

    def get_etf_hist(self, symbol: str, days: int = 120) -> pd.DataFrame | None:
        """获取 ETF 历史日K线（前复权）。

        优先用 fund_etf_hist_em 获取 OHLCV 数据。如失败，fallback 到
        fund_etf_fund_info_em 的 NAV 数据构造简化版（close=nav, 无 high/low/volume）。
        """
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
        try:
            df = ak.fund_etf_hist_em(
                symbol=symbol,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust="qfq",
            )
            if df is not None and not df.empty:
                df = df.rename(columns={
                    "日期": "date", "开盘": "open", "收盘": "close",
                    "最高": "high", "最低": "low",
                    "成交量": "volume", "成交额": "amount",
                    "振幅": "amplitude", "涨跌幅": "change_pct",
                    "涨跌额": "change", "换手率": "turnover",
                })
                df["date"] = pd.to_datetime(df["date"])
                df = df.set_index("date")
                return df
        except Exception as e:
            logger.warning(f"AKShare get_etf_hist failed for {symbol}: {e}, falling back to NAV")
        # Fallback: use NAV history
        nav_df = self.get_etf_nav_history(symbol, days=days)
        if nav_df is not None and not nav_df.empty:
            result = nav_df.rename(columns={"nav": "close"}).copy()
            result["open"] = result["close"]
            result["high"] = result["close"]
            result["low"] = result["close"]
            result["volume"] = 0
            result["amount"] = 0
            result["change_pct"] = result["close"].pct_change() * 100
            result["change"] = result["close"].diff()
            return result[["open", "close", "high", "low", "volume", "amount", "change_pct", "change"]]
        return None

    def get_etf_nav_history(self, fund: str, days: int = 60) -> pd.DataFrame | None:
        """获取 ETF 净值历史。fund: 基金代码如 "510300"。

        返回 DataFrame: date, nav, acc_nav。
        """
        try:
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
            df = ak.fund_etf_fund_info_em(
                fund=fund,
                start_date=start_date,
                end_date=end_date,
            )
            if df is None or df.empty:
                return None
            df = df.rename(columns={
                "净值日期": "date", "单位净值": "nav",
                "累计净值": "acc_nav",
            })
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date")
            return df[["nav", "acc_nav"]]
        except Exception as e:
            logger.warning(f"AKShare get_etf_nav_history failed for {fund}: {e}")
            return None

    def get_open_fund_nav(self, symbol: str) -> dict[str, Any] | None:
        """获取场外（开放式）基金最新净值 + 近期收益。

        场外基金按 T 日净值、T+1 公布，无实时价格/资金流/IOPV。
        返回近 1 周/1 月/3 月收益（基于单位净值序列计算）。
        """
        try:
            df = ak.fund_open_fund_info_em(symbol=symbol, indicator="单位净值走势")
            if df is None or df.empty:
                return None
            df = df.sort_values("净值日期", ascending=False)
            latest = df.iloc[0]
            nav = self._safe_float(latest.get("单位净值"))

            def _ret(n: int) -> float | None:
                if len(df) > n and nav:
                    old = self._safe_float(df.iloc[n].get("单位净值"))
                    if old:
                        return round((nav - old) / old * 100, 2)
                return None

            return {
                "symbol": symbol,
                "nav": nav,
                "acc_nav": self._safe_float(latest.get("累计净值")),
                "date": str(latest.get("净值日期", "")),
                "daily_change": self._safe_float(latest.get("日增长率")),
                "return_1w": _ret(7),
                "return_1m": _ret(30),
                "return_3m": _ret(90),
            }
        except Exception as e:
            logger.warning(f"AKShare get_open_fund_nav failed for {symbol}: {e}")
            return None

    # ETF 跟踪指数 → 乐咕乐股指数名称映射
    _ETF_INDEX_MAP: dict[str, str] = {
        "510050": "上证50", "510300": "沪深300", "510500": "中证500",
        "159915": "创业板50", "512100": "中证1000", "510880": "上证红利",
        "159901": "深证100", "510180": "上证180",
    }
    _LG_INDEX_NAMES: list[str] = [
        "上证50", "沪深300", "上证380", "创业板50", "中证500",
        "上证180", "深证红利", "深证100", "中证1000", "上证红利",
        "中证100", "中证800",
    ]

    def get_index_valuation(self, symbol: str, index_name: str | None = None) -> dict[str, Any] | None:
        """获取指数估值数据（PE/PB 及历史百分位）。

        symbol: ETF 代码或指数代码。index_name: 乐咕乐股指数名称（可选，不传则自动映射）。
        """
        if index_name is None:
            index_name = self._ETF_INDEX_MAP.get(symbol)
        if index_name is None or index_name not in self._LG_INDEX_NAMES:
            logger.warning(f"No index mapping for ETF {symbol}")
            return None
        try:
            df = ak.stock_index_pe_lg(symbol=index_name)
            if df is None or df.empty:
                return None
            r = df.iloc[-1]
            pe = self._safe_float(r.get("滚动市盈率"))
            pe_static = self._safe_float(r.get("静态市盈率"))
            # 计算历史百分位
            pe_col = pd.to_numeric(df["滚动市盈率"], errors="coerce")
            pe_pct = None
            if pe is not None and pe_col.notna().sum() > 0:
                pe_pct = round(float((pe_col.dropna() < pe).sum() / pe_col.dropna().shape[0] * 100), 1)
            return {
                "symbol": symbol,
                "index_name": index_name,
                "date": str(r.get("日期", "")),
                "index_value": self._safe_float(r.get("指数")),
                "pe_ttm": pe,
                "pe_static": pe_static,
                "pe_percentile": pe_pct,
                "pe_median": round(float(pe_col.median()), 2) if pe_col.notna().sum() > 0 else None,
            }
        except Exception as e:
            logger.warning(f"AKShare get_index_valuation failed for {symbol}: {e}")
            return None

    def search_etf(self, keyword: str) -> list[dict[str, Any]]:
        """搜索 ETF（按代码或名称模糊匹配）。"""
        try:
            df = self._get_all_etf_df()
            if df is None or df.empty:
                return []
            mask = df["代码"].str.contains(keyword, na=False) | df["名称"].str.contains(keyword, na=False)
            filtered = df[mask].head(20)
            results = []
            for _, r in filtered.iterrows():
                results.append({
                    "symbol": str(r.get("代码", "")),
                    "name": str(r.get("名称", "")),
                    "price": self._safe_float(r.get("最新价")),
                    "change_pct": self._safe_float(r.get("涨跌幅")),
                })
            return results
        except Exception as e:
            logger.warning(f"AKShare search_etf failed for {keyword}: {e}")
            return []

    # ---- 宏观货币与汇率 ----

    def get_cn_monetary_policy(self) -> dict[str, Any]:
        """最新一期宏观货币数据：LPR / M2 / M1 / 社融 / 中国10Y国债收益率。

        每个数据源独立 try/except，单点失败仅置 None，不影响其它字段。
        akshare 返回的 DataFrame 排序方向不一致，统一按日期/月份降序取首行。
        """
        result: dict[str, Any] = {
            "lpr_1y": None, "lpr_5y": None, "m2_yoy": None,
            "m1_yoy": None, "social_financing": None, "cn_10y_yield": None,
        }
        # LPR
        try:
            df = ak.macro_china_lpr()
            if df is not None and not df.empty:
                latest = df.sort_values("TRADE_DATE", ascending=False).iloc[0]
                result["lpr_1y"] = self._safe_float(latest.get("LPR1Y"))
                result["lpr_5y"] = self._safe_float(latest.get("LPR5Y"))
        except Exception as e:
            logger.warning(f"macro_china_lpr failed: {e}")
        # M2 / M1 同比
        try:
            df = ak.macro_china_money_supply()
            if df is not None and not df.empty:
                # "月份" 形如 "2008年01月份"，归一为 "2008-01" 以便排序
                df = df.copy()
                df["_m"] = (
                    df["月份"].astype(str)
                    .str.replace("年", "-", regex=False)
                    .str.replace("月份", "", regex=False)
                )
                latest = df.sort_values("_m", ascending=False).iloc[0]
                result["m2_yoy"] = self._safe_float(latest.get("货币和准货币(M2)-同比增长"))
                result["m1_yoy"] = self._safe_float(latest.get("货币(M1)-同比增长"))
        except Exception as e:
            logger.warning(f"macro_china_money_supply failed: {e}")
        # 社融增量
        try:
            df = ak.macro_china_shrzgm()
            if df is not None and not df.empty:
                latest = df.sort_values("月份", ascending=False).iloc[0]
                result["social_financing"] = self._safe_float(latest.get("社会融资规模增量"))
        except Exception as e:
            logger.warning(f"macro_china_shrzgm failed: {e}")
        # 中国 10Y 国债收益率
        try:
            end = datetime.now().strftime("%Y%m%d")
            start = (datetime.now() - timedelta(days=60)).strftime("%Y%m%d")
            df = ak.bond_china_yield(start_date=start, end_date=end)
            if df is not None and not df.empty:
                cn = df[df["曲线名称"] == "中债国债收益率曲线"]
                if not cn.empty:
                    latest = cn.sort_values("日期", ascending=False).iloc[0]
                    result["cn_10y_yield"] = self._safe_float(latest.get("10年"))
        except Exception as e:
            logger.warning(f"bond_china_yield failed: {e}")
        return result

    def get_fx_rate_usdcny(self) -> dict[str, Any] | None:
        """USDCNY 即期汇率（lazy import yfinance，避免 CN 客户端硬依赖 yfinance）。"""
        try:
            import yfinance as yf
            t = yf.Ticker("USDCNY=X")
            fi = t.fast_info
            price = float(fi.last_price) if fi.last_price else None
            prev = float(fi.previous_close) if fi.previous_close else price
            if not price:
                return None
            chg = ((price - prev) / prev * 100) if prev else 0
            return {
                "pair": "USDCNY",
                "price": round(price, 4),
                "change_pct": round(chg, 2),
            }
        except Exception as e:
            logger.warning(f"get_fx_rate_usdcny failed: {e}")
            return None

    # ---- 工具方法 ----

    _safe_float = staticmethod(_safe_float)
