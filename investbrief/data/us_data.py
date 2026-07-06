"""US stock data acquisition using yfinance and akshare."""

from datetime import datetime, timedelta

import akshare as ak
import pandas as pd
import urllib.request
import yfinance as yf

from investbrief.data.base import BaseData
from investbrief.core.config import US_GDP_BASE_YEAR, US_GDP_BASE_VALUE
import logging

logger = logging.getLogger(__name__)


def _parse_shiller_date(value) -> str | None:
    """Shiller 日期 YYYY.MM(float) -> 'YYYY-MM'. round 修复 10/11/12 月 float 去零."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    year = int(v)
    month = int(round((v - year) * 100))
    if not (1 <= month <= 12):
        return None
    return f"{year}-{month:02d}"


class USData(BaseData):
    """US stock market data acquisition and storage."""

    market_code = "us"
    primary_index = "^GSPC"
    primary_table = "us_index_daily"

    INDEX_SYMBOLS = [
        "^GSPC", "^IXIC", "^DJI", "^VIX", "^TNX", "^FVX", "^IRX",
        "HYG", "CL=F", "DX-Y.NYB", "GC=F",
    ]

    def update_all(self):
        """Full download of all US data."""
        logger.info("Starting US full data download")
        self.update_index_daily()
        self.update_macro()
        self.update_sentiment()
        logger.info("US full data download complete")

    def update_incremental(self):
        """Incremental update since last recorded date."""
        logger.info("Starting US incremental update")
        self.update_index_daily()
        self.update_macro()
        self.update_sentiment()
        logger.info("US incremental update complete")

    def is_fresh(self) -> bool:
        """True if us_index_daily already has today's data (avoid same-day re-fetch)."""
        from datetime import datetime
        latest = self._latest_data_date("us_index_daily")
        return latest == datetime.now().strftime("%Y-%m-%d")

    def update_index_daily(self):
        """Fetch daily OHLCV for all US symbols invest-brief + risk model need."""
        for ticker_symbol in self.INDEX_SYMBOLS:
            try:
                last_date = self.get_update_date(f"us_index_daily_{ticker_symbol}")
                if last_date:
                    # Incremental: fetch from ~1 week before last_date (TZ-safe), dedup by PK on upsert.
                    start = (datetime.strptime(last_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
                    hist = self._retry_api(lambda ts=ticker_symbol, s=start: yf.Ticker(ts).history(start=s))
                else:
                    hist = self._retry_api(lambda ts=ticker_symbol: yf.Ticker(ts).history(period="max"))
                if hist is None or hist.empty:
                    continue
                hist = hist.reset_index()
                hist["code"] = ticker_symbol
                hist["date"] = pd.to_datetime(hist["Date"]).dt.strftime("%Y-%m-%d")
                df = hist[["code", "date", "Open", "High", "Low", "Close", "Volume"]].copy()
                df.columns = ["code", "date", "open", "high", "low", "close", "volume"]
                if last_date:
                    df = df[df["date"] > last_date]
                if not df.empty:
                    self.upsert_df("us_index_daily", df)
                    self.set_update_date(f"us_index_daily_{ticker_symbol}", df["date"].max())
            except Exception as e:
                logger.error(f"Failed to update {ticker_symbol}: {e}")

    def update_macro(self):
        """Fetch CPI and GDP data."""
        self._update_cpi()
        self._update_gdp()

    def _update_cpi(self):
        try:
            df = self._retry_api(lambda: ak.macro_usa_cpi_yoy())
            rows = []
            for _, row in df.iterrows():
                value = row.get("现值") or row.get("今值")
                date_col = row.get("时间") or row.get("日期")
                if pd.notna(value):
                    rows.append({
                        "indicator": "CPI",
                        "country": "us",
                        "date": str(date_col),
                        "value": float(value),
                    })
            if rows:
                cpi_df = pd.DataFrame(rows)
                self.upsert_df("macro_data", cpi_df)
                self.set_update_date("macro_data_cpi_us", cpi_df["date"].max())
        except Exception as e:
            logger.error(f"Failed to update US CPI: {e}")

    def _update_gdp(self):
        try:
            df = self._retry_api(lambda: ak.macro_usa_gdp_monthly())
            rows = []
            base_value = US_GDP_BASE_VALUE
            for _, row in df.iterrows():
                if pd.notna(row.get("今值")):
                    date_str = str(row["日期"])
                    growth_rate = float(row["今值"]) / 100.0
                    # Estimate absolute GDP from base year
                    base_year = US_GDP_BASE_YEAR
                    try:
                        current_year = int(date_str[:4])
                    except (ValueError, IndexError):
                        continue
                    years_from_base = current_year - base_year
                    if years_from_base >= 0:
                        estimated_gdp = base_value * ((1 + growth_rate) ** years_from_base)
                    else:
                        estimated_gdp = base_value / ((1 + growth_rate) ** abs(years_from_base))
                    rows.append({
                        "indicator": "GDP",
                        "country": "us",
                        "date": date_str,
                        "value": estimated_gdp,  # in trillion USD
                    })
            if rows:
                gdp_df = pd.DataFrame(rows)
                self.upsert_df("macro_data", gdp_df)
                self.set_update_date("macro_data_gdp_us", gdp_df["date"].max())
        except Exception as e:
            logger.error(f"Failed to update US GDP: {e}")

    def update_sentiment(self):
        """Fetch SPY PE, Shiller PE history, credit spread proxy, VIX, market breadth."""
        self._update_spy_pe()
        self._update_shiller_pe()
        self._update_credit_spread()
        self._update_vix_sentiment()
        self._update_market_breadth()

    def _update_spy_pe(self):
        try:
            spy = yf.Ticker("SPY")
            info = spy.info
            pe = info.get("trailingPE")
            if pe is None:
                logger.warning("SPY trailing PE not available")
                return
            trading_date = self.query("SELECT MAX(date) as d FROM us_index_daily WHERE code = '^GSPC'")
            today = str(trading_date.iloc[0]["d"]) if not trading_date.empty else datetime.now().strftime("%Y-%m-%d")
            self.merge_sentiment_row("us", today, pe_ratio=float(pe))
            self.set_update_date("sentiment_pe_us", today)
        except Exception as e:
            logger.error(f"Failed to update SPY PE: {e}")

    def _update_shiller_pe(self):
        """回填S&P500历史PE(Shiller ie_data.xls, 月度1871至今).

        替代 _update_spy_pe 的"只给当天无历史"缺陷: Shiller P/E = S&P价格(col1)÷
        earnings(col3), 与SPY trailingPE同口径。回填后 _pe_us 样本量>100自动走
        历史分位。upsert+UPDATE_NULL 模式(参照 _update_credit_spread), 不覆盖
        vix/credit_spread 等已有列。
        """
        try:
            import io
            # Recency gate on FETCH time (not data date — Shiller series lags, so
            # get_update_date returns ~2023 forever; get_update_time returns when we
            # last ran this fetch). Monthly series → skip if fetched within 7 days.
            last = self.get_update_time("sentiment_pe_us_shiller")
            if last:
                try:
                    last_dt = datetime.strptime(str(last)[:10], "%Y-%m-%d")
                    if (datetime.now() - last_dt).days < 7:
                        logger.info("Shiller PE recent (within 7d), skip xls download")
                        return
                except ValueError:
                    pass  # malformed date → proceed to download
            url = "http://www.econ.yale.edu/~shiller/data/ie_data.xls"
            with urllib.request.urlopen(url, timeout=60) as resp:
                buf = io.BytesIO(resp.read())
            # Data sheet 表头在第7行(0-indexed); 前4列=Date,P,D,E
            df = pd.read_excel(buf, sheet_name="Data", header=7).iloc[:, :4]
            df.columns = ["date_raw", "price", "dividend", "earnings"]
            df = df[pd.to_numeric(df["date_raw"], errors="coerce").notna()].copy()
            for c in ("price", "earnings"):
                df[c] = pd.to_numeric(df[c], errors="coerce")
            df = df.dropna(subset=["price", "earnings"])
            df = df[df["earnings"] > 0]
            # 日期 YYYY.MM -> YYYY-MM (round 修复 10/11/12 月 float 去零)
            df["date"] = df["date_raw"].apply(_parse_shiller_date)
            df = df.dropna(subset=["date"]).copy()
            df["pe_ratio"] = (df["price"] / df["earnings"]).round(3)
            rows = pd.DataFrame({
                "market": "us",
                "date": df["date"].values,
                "pe_ratio": df["pe_ratio"].values,
            })
            self.upsert_df("sentiment_data", rows)
            # 补已存在行的 NULL pe_ratio (不覆盖其他源已写的值)
            upd = [(float(r["pe_ratio"]), str(r["date"])) for _, r in rows.iterrows()]
            self.conn.executemany(
                "UPDATE sentiment_data SET pe_ratio=? WHERE market='us' AND date=? AND pe_ratio IS NULL",
                upd,
            )
            self.conn.commit()
            self.set_update_date("sentiment_pe_us_shiller", str(df["date"].iloc[-1]))
            logger.info(f"Shiller S&P500 PE 回填 {len(rows)} 月度点, 至 {df['date'].iloc[-1]}")
        except Exception as e:
            logger.error(f"Failed to update Shiller PE: {e}")

    def _update_credit_spread(self):
        """回算HYG/TNX 30d信用利差全历史, 回填sentiment(修复只存当天的3点问题)."""
        try:
            hyg = self.query("SELECT date, close AS h FROM us_index_daily WHERE code = 'HYG' ORDER BY date")
            tnx = self.query("SELECT date, close AS t FROM us_index_daily WHERE code = '^TNX' ORDER BY date")
            if hyg.empty or tnx.empty:
                return
            m = hyg.merge(tnx, on="date")
            m["credit_spread"] = m["h"].pct_change(30) - (m["t"] - m["t"].shift(30)) / 100.0
            cs = m[["date", "credit_spread"]].dropna()
            cs["market"] = "us"
            self.upsert_df("sentiment_data", cs[["market", "date", "credit_spread"]])
            # INSERT OR IGNORE跳过已有行, 用UPDATE补NULL列
            rows = [(float(r["credit_spread"]), str(r["date"])) for _, r in cs.iterrows()]
            self.conn.executemany(
                "UPDATE sentiment_data SET credit_spread=? WHERE market='us' AND date=? AND credit_spread IS NULL",
                rows,
            )
            self.conn.commit()
            self.set_update_date("sentiment_credit_us", str(cs.iloc[-1]["date"]))
        except Exception as e:
            logger.error(f"Failed to update credit spread: {e}")

    def _update_vix_sentiment(self):
        """从us_index_daily ^VIX全历史回填sentiment.vix(修复只存当天的3点问题)."""
        try:
            vix = self.query("SELECT date, close AS vix FROM us_index_daily WHERE code = '^VIX'")
            if vix.empty:
                return
            vix["market"] = "us"
            self.upsert_df("sentiment_data", vix[["market", "date", "vix"]])
            self.set_update_date("sentiment_vix_us", str(vix.iloc[-1]["date"]))
        except Exception as e:
            logger.error(f"Failed to update VIX sentiment: {e}")

    def _update_market_breadth(self):
        """Calculate US market breadth from S&P 500 advance/decline or stock universe."""
        try:
            last_saved = self.get_update_date("sentiment_breadth_us")
            trading_df = self.query(
                "SELECT MAX(date) as d FROM us_index_daily WHERE code = '^GSPC'"
            )
            today = str(trading_df.iloc[0]["d"]) if not trading_df.empty else datetime.now().strftime("%Y-%m-%d")
            if last_saved and today <= last_saved:
                return

            # Use akshare to get US stock universe and count advancers/decliners
            try:
                df = self._retry_api(lambda: ak.stock_us_spot_em())
                if df is not None and not df.empty:
                    change_col = None
                    for col in ["涨跌幅", "changepercent", "涨跌额"]:
                        if col in df.columns:
                            change_col = col
                            break
                    if change_col is None:
                        logger.warning("Cannot find change column for US market breadth")
                        return
                    total = len(df)
                    up_count = (df[change_col] > 0).sum()
                    breadth = up_count / total if total > 0 else 0.5
                    self.merge_sentiment_row("us", today, market_breadth=breadth)
                    self.set_update_date("sentiment_breadth_us", today)
                    logger.info(f"US market breadth: {breadth:.3f} ({up_count}/{total})")
            except Exception as api_err:
                logger.warning(f"US market breadth from akshare failed: {api_err}")
                # Fallback: estimate from S&P 500 index daily change
                # If SPX is up, assume >50% breadth; if down, <50%
                spx = self.query(
                    "SELECT close FROM us_index_daily WHERE code = '^GSPC' ORDER BY date DESC LIMIT 2"
                )
                if len(spx) >= 2:
                    change = (float(spx.iloc[0]["close"]) - float(spx.iloc[1]["close"])) / float(spx.iloc[1]["close"])
                    # Rough estimate: breadth ≈ 0.5 + change * 10 (capped at 0.1-0.9)
                    breadth = max(0.1, min(0.9, 0.5 + change * 10))
                    self.merge_sentiment_row("us", today, market_breadth=breadth)
                    self.set_update_date("sentiment_breadth_us", today)
        except Exception as e:
            logger.error(f"Failed to update US market breadth: {e}")
