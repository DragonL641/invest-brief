"""A股数据客户端，基于 AKShare。"""

import logging
import os
from typing import Any
from datetime import datetime, timedelta

os.environ["TQDM_DISABLE"] = "1"

import akshare as ak
import pandas as pd

logger = logging.getLogger(__name__)


class AKShareClient:
    """封装 AKShare 接口，提供统一的 A 股数据获取方法。

    每个方法内部做异常处理和空值兜底，单个接口失败不影响整体。
    """

    # ---- 指数 ----

    def get_index_quote(self, symbol: str) -> dict[str, Any] | None:
        """获取指数实时行情。symbol: 如 "000001"（上证指数）。

        调用 stock_zh_index_spot_em() 拿到全部指数，按代码过滤。
        """
        try:
            df = ak.stock_zh_index_spot_em()
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
        """批量获取指数实时行情。一次 API 调用，过滤多个代码。"""
        try:
            df = ak.stock_zh_index_spot_em()
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

    def get_stock_quote(self, symbol: str) -> dict[str, Any] | None:
        """获取个股实时行情。symbol: 6位代码如 "600519"。

        注意：stock_zh_a_spot_em() 返回全量 A 股，调用较慢（约 1 分钟）。
        如需批量查询，优先使用 get_stock_quotes()。
        """
        try:
            df = ak.stock_zh_a_spot_em()
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
        """批量获取个股实时行情。一次 API 调用，过滤多个代码。

        推荐：需要查询多只股票时使用此方法，避免重复调用全量接口。
        """
        try:
            df = ak.stock_zh_a_spot_em()
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

    def get_analyst_rating_summary(self, symbol: str) -> dict[str, Any] | None:
        """汇总研报评级分布（取全量研报以反映真实分布）。"""
        try:
            reports = self.get_research_reports(symbol, limit=500)
            if not reports:
                return None
            counts: dict[str, int] = {
                "buy": 0, "outperform": 0, "neutral": 0,
                "underperform": 0, "sell": 0,
            }
            target_prices: list[float] = []
            for rpt in reports:
                en = self._RATING_MAP.get(rpt["rating"], "")
                if en:
                    counts[en] += 1
                tp = rpt.get("target_price")
                if tp is not None:
                    target_prices.append(tp)
            return {
                **counts,
                "avg_target_price": (
                    sum(target_prices) / len(target_prices)
                    if target_prices else None
                ),
                "total_reports": len(reports),
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

    def get_insider_trades(self, symbol: str, days: int = 30) -> list[dict[str, Any]]:
        """获取高管持股变动（东方财富）。

        调用 stock_ggcg_em() 拿全量数据，按代码和日期过滤。
        注意：该接口分页较多，耗时较长。
        """
        try:
            df = ak.stock_ggcg_em(symbol="全部")
            if df is None or df.empty:
                return []
            cutoff = (datetime.now() - timedelta(days=days)).date()
            df = df[df["代码"] == symbol]
            df = df[df["公告日"].apply(lambda x: x.date() if hasattr(x, "date") else x) >= cutoff]
            results = []
            for _, r in df.iterrows():
                results.append({
                    "name": str(r.get("名称", "")),
                    "position": str(r.get("股东名称", "")),
                    "action": str(r.get("持股变动信息-增减", "")),
                    "shares": self._safe_float(r.get("持股变动信息-变动数量")),
                    "amount": None,  # 该接口不直接提供变动金额
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

    def get_institutional_research(
        self, symbol: str, days: int = 30
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

    # ---- 工具方法 ----

    @staticmethod
    def _safe_float(val) -> float | None:
        """安全转换为 float。"""
        if val is None or val == "-" or val == "":
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None
