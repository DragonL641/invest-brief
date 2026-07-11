"""A-share data acquisition using akshare."""

from datetime import datetime, timedelta
import re
import akshare as ak
import pandas as pd
from investbrief.data.base import BaseData
import logging
logger = logging.getLogger(__name__)


class CNData(BaseData):
    """A-share market data acquisition and storage."""

    market_code = "cn"
    primary_index = "sh000001"
    primary_table = "cn_index_daily"

    # invest-brief 需要的 5 个 A 股指数（覆盖原 sh000001 单一来源）
    INDEX_CODES = ["sh000001", "sz399001", "sz399006", "sh000300", "sh000688"]

    def update_all(self):
        """Full download of all A-share data."""
        logger.info("Starting A-share full data download")
        self.update_index_daily()
        self.update_macro()
        self.update_sentiment()
        logger.info("A-share full data download complete")

    def update_incremental(self):
        """Incremental update since last recorded date."""
        logger.info("Starting A-share incremental update")
        self.update_index_daily()
        self.update_macro()
        self.update_sentiment()
        logger.info("A-share incremental update complete")

    def is_fresh(self) -> bool:
        """True if cn_index_daily already has today's data (avoid same-day re-fetch)."""
        from datetime import datetime
        latest = self._latest_data_date("cn_index_daily")
        return latest == datetime.now().strftime("%Y-%m-%d")

    def update_index_daily(self):
        """Fetch daily OHLCV for the 5 A-share indices invest-brief renders."""
        for code in self.INDEX_CODES:
            try:
                df = self._retry_api(lambda c=code: ak.stock_zh_index_daily(symbol=c))
                if df is None or df.empty:
                    continue
                df = df.copy()
                df["code"] = code
                df["amount"] = None  # stock_zh_index_daily 不返回成交额列
                df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
                last_date = self.get_update_date(f"cn_index_daily_{code}")
                if last_date:
                    df = df[df["date"] > last_date]
                if not df.empty:
                    self.upsert_df("cn_index_daily", df)
                    self.set_update_date(f"cn_index_daily_{code}", df["date"].max())
            except Exception as e:
                logger.error(f"Failed to update CN index {code}: {e}")

    def update_macro(self):
        """Fetch GDP, CPI, treasury yield, LPR, M2/M1, 社融, USDCNY."""
        self._update_gdp()
        self._update_cpi()
        self._update_treasury_yield()
        self._update_lpr()
        self._update_money_supply()
        self._update_social_financing()
        self._update_usdcny()

    def _update_gdp(self):
        try:
            df = self._retry_api(lambda: ak.macro_china_gdp())
            rows = []
            for _, row in df.iterrows():
                quarter = str(row["季度"])
                date_str = self._quarter_to_date(quarter)
                if date_str:
                    rows.append({
                        "indicator": "GDP",
                        "country": "cn",
                        "date": date_str,
                        "value": float(row["国内生产总值-绝对值"]),
                    })
            if rows:
                gdp_df = pd.DataFrame(rows)
                self.upsert_df("macro_data", gdp_df)
                self.set_update_date("macro_data_gdp_cn", gdp_df["date"].max())
        except Exception as e:
            logger.error(f"Failed to update CN GDP: {e}")

    def _update_cpi(self):
        try:
            # 国家统计局月度 CPI(同比),数据更新到上个月;比 macro_china_cpi_yearly
            # (英为财情源,滞后到 2025-08)更及时。
            df = self._retry_api(lambda: ak.macro_china_cpi())
            rows = []
            for _, row in df.iterrows():
                month = str(row.get("月份", ""))  # "2026年06月份"
                yoy = row.get("全国-同比增长")
                if yoy is None or pd.isna(yoy):
                    continue
                m = re.match(r"(\d{4})年(\d{1,2})月份", month)
                if not m:
                    continue
                date = f"{m.group(1)}-{int(m.group(2)):02d}"
                rows.append({
                    "indicator": "CPI",
                    "country": "cn",
                    "date": date,
                    "value": float(yoy),
                })
            if rows:
                cpi_df = pd.DataFrame(rows)
                self.upsert_df("macro_data", cpi_df)
                self.set_update_date("macro_data_cpi_cn", cpi_df["date"].max())
        except Exception as e:
            logger.error(f"Failed to update CN CPI: {e}")

    def _update_treasury_yield(self):
        try:
            today = datetime.now()
            last_date = self.get_update_date("macro_data_treasury_cn")
            if last_date:
                try:
                    # Incremental: fetch from ~10 days before last_date (overlap safe; PK dedup).
                    chunk_start = datetime.strptime(str(last_date)[:10], "%Y-%m-%d") - timedelta(days=10)
                except ValueError:
                    chunk_start = datetime(2005, 1, 1)
            else:
                chunk_start = datetime(2005, 1, 1)

            all_rows = []
            start = chunk_start
            while start < today:
                end = min(start + timedelta(days=360), today)
                s = start.strftime("%Y%m%d")
                e = end.strftime("%Y%m%d")
                try:
                    df = self._retry_api(lambda s=s, e=e: ak.bond_china_yield(start_date=s, end_date=e))
                    if df is not None and not df.empty:
                        treasury_df = df[df["曲线名称"] == "中债国债收益率曲线"]
                        for _, row in treasury_df.iterrows():
                            if pd.notna(row.get("10年")):
                                all_rows.append({
                                    "indicator": "10Y_TREASURY",
                                    "country": "cn",
                                    "date": str(row["日期"]),
                                    "value": float(row["10年"]),
                                })
                except Exception as chunk_err:
                    logger.warning(f"Treasury yield chunk {s}-{e} failed: {chunk_err}")
                start = end + timedelta(days=1)

            if all_rows:
                yield_df = pd.DataFrame(all_rows)
                self.upsert_df("macro_data", yield_df)
                self.set_update_date("macro_data_treasury_cn", yield_df["date"].max())
                logger.info(f"Updated {len(all_rows)} treasury yield rows")
        except Exception as e:
            logger.error(f"Failed to update CN treasury yield: {e}")

    def _update_lpr(self):
        try:
            df = self._retry_api(lambda: ak.macro_china_lpr())
            if df is None or df.empty:
                return
            df = df.copy()
            df["date"] = df["TRADE_DATE"].astype(str).str[:10]
            rows = []
            for _, row in df.iterrows():
                d = row["date"]
                for ind, col in (("LPR1Y", "LPR1Y"), ("LPR5Y", "LPR5Y")):
                    v = row.get(col)
                    if pd.notna(v):
                        rows.append({"indicator": ind, "country": "cn", "date": d, "value": float(v)})
            if rows:
                self.upsert_df("macro_data", pd.DataFrame(rows))
                self.set_update_date("macro_data_lpr_cn", df["date"].max())
        except Exception as e:
            logger.error(f"Failed to update CN LPR: {e}")

    def _update_money_supply(self):
        try:
            df = self._retry_api(lambda: ak.macro_china_money_supply())
            if df is None or df.empty:
                return
            df = df.copy()
            df["_m"] = (df["月份"].astype(str).str.replace("年", "-", regex=False)
                        .str.replace("月份", "", regex=False))
            rows = []
            for _, row in df.iterrows():
                d = f"{row['_m']}-01"
                for ind, col in (("M2_YOY", "货币和准货币(M2)-同比增长"),
                                 ("M1_YOY", "货币(M1)-同比增长")):
                    v = row.get(col)
                    if pd.notna(v):
                        rows.append({"indicator": ind, "country": "cn", "date": d, "value": float(v)})
            if rows:
                self.upsert_df("macro_data", pd.DataFrame(rows))
                self.set_update_date("macro_data_money_cn", df["_m"].max())
        except Exception as e:
            logger.error(f"Failed to update CN money supply: {e}")

    def _update_social_financing(self):
        try:
            df = self._retry_api(lambda: ak.macro_china_shrzgm())
            if df is None or df.empty:
                return
            df = df.copy()
            # shrzgm 月份 = "YYYYMM"（如 "201501"，实测 akshare 无年/月份后缀）；归一为 "YYYY-MM"
            df["_m"] = pd.to_datetime(df["月份"].astype(str), format="%Y%m", errors="coerce").dt.strftime("%Y-%m")
            df = df.dropna(subset=["_m"])
            rows = []
            for _, row in df.iterrows():
                v = row.get("社会融资规模增量")
                if pd.notna(v):
                    rows.append({"indicator": "SOCIAL_FIN", "country": "cn",
                                 "date": f"{row['_m']}-01", "value": float(v)})
            if rows:
                self.upsert_df("macro_data", pd.DataFrame(rows))
                self.set_update_date("macro_data_social_cn", df["_m"].max())
        except Exception as e:
            logger.error(f"Failed to update CN 社融: {e}")

    def _update_usdcny(self):
        """USDCNY 即期汇率(akshare forex_spot_em) → macro_data，供 CN 资产表现板块计算 change。

        gold_data 已通过 FRED DEXCHUS 入库 USDCNY 历史序列; 此处只刷新当日实时值。
        """
        try:
            from investbrief.datasources.akshare import AKShareClient
            price = AKShareClient().get_fx_usdcny_realtime()
            if price is None:
                return
            today = datetime.now().strftime("%Y-%m-%d")
            rows = pd.DataFrame([{
                "indicator": "USDCNY", "country": "global",
                "date": today, "value": float(price),
            }])
            self.upsert_df("macro_data", rows)
            self.set_update_date("macro_data_usdcny_global", today)
        except Exception as e:
            logger.error(f"Failed to update USDCNY: {e}")

    def update_sentiment(self):
        """Fetch margin balance, accounts, market cap, PE."""
        self._update_margin()
        self._update_market_cap_pe()
        self._update_index_pes()
        self._update_market_breadth()

    def _update_margin(self):
        try:
            # Fetch in 1-year chunks to avoid API date range limits
            today = datetime.now()
            last_date = self.get_update_date("sentiment_margin_cn")
            if last_date:
                # Incremental: only fetch the chunk from ~10 days before last_date onward.
                # (merge_sentiment_row preserves existing non-NULL values, so overlap is safe.)
                chunk_start = datetime.strptime(last_date, "%Y-%m-%d") - timedelta(days=10)
            else:
                chunk_start = datetime(2010, 1, 1)
            chunks = []
            start = chunk_start
            while start < today:
                end = min(start + timedelta(days=360), today)
                s = start.strftime("%Y%m%d")
                e = end.strftime("%Y%m%d")
                chunks.append((s, e))
                start = end + timedelta(days=1)

            last_merged_date = None
            for s, e in chunks:
                try:
                    sse_df = self._retry_api(
                        lambda s=s, e=e: ak.stock_margin_sse(start_date=s, end_date=e)
                    )
                except Exception:
                    continue
                if sse_df.empty:
                    continue
                for _, row in sse_df.iterrows():
                    date_str = str(row["信用交易日期"])
                    if len(date_str) == 8:
                        date_str = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
                    if last_date and date_str <= last_date:
                        continue
                    total = row["融资融券余额"]
                    if pd.notna(total):
                        # Convert from 元 to 亿 for unit consistency with market cap
                        self.merge_sentiment_row("cn", date_str, margin_balance=float(total) / 1e8)
                        last_merged_date = date_str
            if last_merged_date:
                self.set_update_date("sentiment_margin_cn", last_merged_date)
        except Exception as e:
            logger.error(f"Failed to update CN margin: {e}")

    def _update_market_cap_pe(self):
        try:
            df = self._retry_api(lambda: ak.stock_market_pe_lg(symbol="上证"))
            if df.empty:
                return

            # Get current total A-share market cap for scaling (in 亿)
            total_mcap = self._get_current_total_market_cap()
            current_index = float(df.iloc[-1]["指数"])
            scaling_factor = total_mcap / current_index if total_mcap and current_index > 0 else 0

            if scaling_factor <= 0:
                logger.warning("Cannot calibrate market cap scaling factor, storing PE only")

            last_saved = self.get_update_date("sentiment_mktcap_pe_cn")
            last_date = None
            for _, row in df.iterrows():
                date_str = str(row["日期"])
                if last_saved and date_str <= last_saved:
                    continue

                pe = row.get("平均市盈率")
                idx = row.get("指数")
                est_mcap = float(idx) * scaling_factor if pd.notna(idx) and scaling_factor > 0 else None

                self.merge_sentiment_row(
                    "cn", date_str,
                    total_market_cap=est_mcap,
                    pe_ratio=float(pe) if pd.notna(pe) else None,
                )
                last_date = date_str
            if last_date:
                self.set_update_date("sentiment_mktcap_pe_cn", last_date)
        except Exception as e:
            logger.error(f"Failed to update market cap/PE: {e}")

    def _update_index_pes(self):
        """采集沪深300/中证500 PE → macro_data(零改表结构), 用于双ERP。"""
        specs = [('沪深300', 'HSH300'), ('中证500', 'ZZ500')]
        for symbol, prefix in specs:
            try:
                df = self._retry_api(lambda s=symbol: ak.stock_index_pe_lg(symbol=s))
                if df is None or df.empty:
                    continue
                date_col = df.columns[0]
                # 存等权PE(_PE, 用于ERP) + 加权PE(_PE_W, 用于结构分化比值)
                for col, suffix in [('等权滚动市盈率', '_PE'), ('滚动市盈率', '_PE_W')]:
                    if col not in df.columns:
                        continue
                    indicator = prefix + suffix
                    rows = []
                    for _, r in df.iterrows():
                        d = str(r[date_col])[:10]
                        pe = r[col]
                        if pd.notna(pe):
                            rows.append({"indicator": indicator, "country": "cn",
                                         "date": d, "value": float(pe)})
                    if rows:
                        self.upsert_df("macro_data", pd.DataFrame(rows))
                        self.set_update_date(f"macro_data_{indicator.lower()}_cn", str(rows[-1]["date"]))
            except Exception as e:
                logger.error(f"Failed {symbol} PE: {e}")

    def _get_current_total_market_cap(self) -> float | None:
        """Get total A-share market cap (SSE + SZSE) in 亿."""
        try:
            sse = self._retry_api(lambda: ak.stock_sse_summary())
            sse_mcap_row = sse[sse["项目"] == "总市值"]
            if sse_mcap_row.empty:
                return None
            sse_mcap = float(sse_mcap_row.iloc[0]["股票"])

            try:
                szse = self._retry_api(lambda: ak.stock_szse_summary())
                szse_stock = szse[szse["证券类别"] == "股票"]
                if not szse_stock.empty:
                    szse_mcap = float(szse_stock.iloc[0]["总市值"]) / 1e8
                    return sse_mcap + szse_mcap
            except Exception:
                pass
            return sse_mcap * 1.4
        except Exception as e:
            logger.warning(f"Failed to get current market cap: {e}")
            return None

    def _update_market_breadth(self):
        """Calculate market breadth (up/total ratio) from all A-share stocks."""
        try:
            last_saved = self.get_update_date("sentiment_breadth_cn")
            today = datetime.now().strftime("%Y-%m-%d")
            if last_saved and today <= last_saved:
                return

            df = self._retry_api(lambda: ak.stock_zh_a_spot_em())
            if df.empty:
                return
            total = len(df)
            change_col = None
            for col in ["涨跌幅", "changepercent", "涨跌"]:
                if col in df.columns:
                    change_col = col
                    break
            if change_col is None:
                logger.warning("Cannot find change column for market breadth")
                return

            up_count = (df[change_col] > 0).sum()
            breadth = up_count / total if total > 0 else 0.5

            self.merge_sentiment_row("cn", today, market_breadth=breadth)
            self.set_update_date("sentiment_breadth_cn", today)
        except Exception as e:
            logger.error(f"Failed to update market breadth: {e}")

    @staticmethod
    def _quarter_to_date(quarter_str: str) -> str | None:
        """Convert '2026年第1季度' -> '2026-03-31' etc."""
        try:
            if "第1-4季度" in quarter_str or "全年" in quarter_str:
                year = quarter_str[:4]
                return f"{year}-12-31"
            elif "第1-3季度" in quarter_str:
                year = quarter_str[:4]
                return f"{year}-09-30"
            elif "第1-2季度" in quarter_str:
                year = quarter_str[:4]
                return f"{year}-06-30"
            elif "第1季度" in quarter_str:
                year = quarter_str[:4]
                return f"{year}-03-31"
            elif "第2季度" in quarter_str:
                year = quarter_str[:4]
                return f"{year}-06-30"
            elif "第3季度" in quarter_str:
                year = quarter_str[:4]
                return f"{year}-09-30"
            elif "第4季度" in quarter_str:
                year = quarter_str[:4]
                return f"{year}-12-31"
        except (ValueError, IndexError):
            pass
        return None
