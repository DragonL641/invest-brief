"""yfinance API Client."""
import math
import threading
import time
from datetime import datetime, timedelta
from typing import Any

import logging

logger = logging.getLogger(__name__)

_HIGH_IMPORTANCE_PATTERNS = [
    "cpi", "consumer price", "non farm", "employment situation",
    "fomc", "federal funds", "interest rate", "gdp", "gross domestic",
    "pce", "personal consumption", "unemployment rate",
]


def _classify_economic_importance(event_name: str) -> str:
    lower = event_name.lower()
    for pattern in _HIGH_IMPORTANCE_PATTERNS:
        if pattern in lower:
            return "high"
    return "medium"


def _fmt_econ_value(val) -> str | None:
    if val is None:
        return None
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return None
    if isinstance(val, float):
        return f"{val:.1f}"
    return str(val) if val != "" else None


class YFinanceClient:
    """
    yfinance API Client

    No API key needed. Best for US stocks, partial support for KR (.KS/.KQ).
    Provides: prices, analyst targets, upgrades/downgrades, EPS, insider trades.
    """

    _MIN_INTERVAL = 0.4  # seconds between yfinance requests
    _lock = threading.Lock()
    _last_request = 0.0

    def __init__(self):
        try:
            import yfinance
            self._yf = yfinance
            self.enabled = True
        except ImportError:
            self._yf = None
            self.enabled = False
        self._ticker_cache: dict = {}
        self._history_cache: dict = {}
        self._max_cache = 50

    @classmethod
    def _throttle(cls):
        """Block until enough time has passed since the last yfinance request."""
        with cls._lock:
            now = time.monotonic()
            wait = cls._MIN_INTERVAL - (now - cls._last_request)
            if wait > 0:
                time.sleep(wait)
            cls._last_request = time.monotonic()

    def _ticker(self, symbol: str):
        if len(self._ticker_cache) > self._max_cache:
            oldest = next(iter(self._ticker_cache))
            del self._ticker_cache[oldest]
        if symbol not in self._ticker_cache:
            self._ticker_cache[symbol] = self._yf.Ticker(symbol)
        return self._ticker_cache[symbol]

    # ==================== Price ====================

    def get_quote(self, symbol: str) -> dict[str, Any] | None:
        """Get current price and basic info via fast_info + history."""
        if not self.enabled:
            return None
        try:
            self._throttle()
            t = self._ticker(symbol)
            fi = t.fast_info
            current = float(fi.last_price) if fi.last_price else None
            if not current:
                return None
            prev = float(fi.previous_close) if fi.previous_close else current
            change_pct = ((current - prev) / prev) * 100 if prev else 0
            return {
                "price": current,
                "previous_close": prev,
                "change": round(current - prev, 4),
                "change_percent": round(change_pct, 2),
                "day_high": float(fi.day_high) if fi.day_high else None,
                "day_low": float(fi.day_low) if fi.day_low else None,
                "volume": int(fi.last_volume) if fi.last_volume else None,
                "market_cap": float(fi.market_cap) if fi.market_cap else None,
                "source": "yfinance",
            }
        except Exception as e:
            logger.warning(f"yfinance quote error ({symbol}): {e}")
            return None

    def get_index_quote(self, symbol: str) -> dict[str, Any] | None:
        """Get index quote (e.g., ^GSPC, ^KS11)."""
        return self.get_quote(symbol)

    # ==================== Analyst ====================

    def get_price_targets(self, symbol: str) -> dict[str, Any] | None:
        """Get analyst price targets {current, low, high, mean, median}."""
        if not self.enabled:
            return None
        try:
            self._throttle()
            t = self._ticker(symbol)
            targets = t.analyst_price_targets
            if not targets or not targets.get("mean"):
                return None
            return {
                "current": targets.get("current"),
                "low": targets.get("low"),
                "high": targets.get("high"),
                "mean": targets.get("mean"),
                "median": targets.get("median"),
                "source": "yfinance",
            }
        except Exception as e:
            logger.warning(f"yfinance price_targets error ({symbol}): {e}")
            return None

    def get_upgrades_downgrades(self, symbol: str, limit: int = 10) -> list[dict[str, Any]] | None:
        """Get analyst upgrade/downgrade history (last 30 days)."""
        if not self.enabled:
            return None
        try:
            self._throttle()
            t = self._ticker(symbol)
            df = t.upgrades_downgrades
            if df is None or df.empty:
                return None
            # Filter to last 30 days
            cutoff = datetime.now() - timedelta(days=30)
            df = df[df.index >= cutoff]
            if df.empty:
                return None
            results = []
            for date, row in df.head(limit).iterrows():
                results.append({
                    "firm": row.get("Firm", ""),
                    "to_grade": row.get("ToGrade", ""),
                    "from_grade": row.get("FromGrade", ""),
                    "action": row.get("Action", ""),
                    "price_target": row.get("currentPriceTarget"),
                    "date": date.strftime("%Y-%m-%d"),
                })
            return results if results else None
        except Exception as e:
            logger.warning(f"yfinance upgrades_downgrades error ({symbol}): {e}")
            return None

    def get_recommendations(self, symbol: str) -> dict[str, Any] | None:
        """Get analyst recommendation distribution."""
        if not self.enabled:
            return None
        try:
            self._throttle()
            t = self._ticker(symbol)
            df = t.recommendations
            if df is None or df.empty:
                return None
            latest = df.iloc[0]
            return {
                "strong_buy": int(latest.get("strongBuy", 0)),
                "buy": int(latest.get("buy", 0)),
                "hold": int(latest.get("hold", 0)),
                "sell": int(latest.get("sell", 0)),
                "strong_sell": int(latest.get("strongSell", 0)),
                "source": "yfinance",
            }
        except Exception as e:
            logger.warning(f"yfinance recommendations error ({symbol}): {e}")
            return None

    # ==================== Fundamentals ====================

    def get_info(self, symbol: str) -> dict[str, Any] | None:
        """Get comprehensive stock info (PE, margins, growth, etc.)."""
        if not self.enabled:
            return None
        try:
            self._throttle()
            t = self._ticker(symbol)
            return t.info
        except Exception as e:
            logger.warning(f"yfinance info error ({symbol}): {e}")
            return None

    def get_earnings_estimate(self, symbol: str) -> dict[str, Any] | None:
        """Get EPS estimates for current/next quarter/year."""
        if not self.enabled:
            return None
        try:
            self._throttle()
            t = self._ticker(symbol)
            df = t.earnings_estimate
            if df is None or df.empty:
                return None
            result = {}
            for period, row in df.iterrows():
                result[period] = {
                    "avg": float(row.get("avg", 0)),
                    "low": float(row.get("low", 0)),
                    "high": float(row.get("high", 0)),
                    "growth": float(row.get("growth", 0)),
                    "num_analysts": int(row.get("numberOfAnalysts", 0)),
                }
            return result
        except Exception as e:
            logger.warning(f"yfinance earnings_estimate error ({symbol}): {e}")
            return None

    def get_earnings_history(self, symbol: str) -> list[dict[str, Any]] | None:
        """Get recent earnings history with actual vs estimate."""
        if not self.enabled:
            return None
        try:
            self._throttle()
            t = self._ticker(symbol)
            df = t.earnings_history
            if df is None or df.empty:
                return None
            results = []
            for date, row in df.iterrows():
                results.append({
                    "quarter": str(date.date()) if hasattr(date, "date") else str(date),
                    "eps_actual": float(row.get("epsActual", 0)),
                    "eps_estimate": float(row.get("epsEstimate", 0)),
                    "surprise_pct": float(row.get("surprisePercent", 0)),
                })
            return results
        except Exception as e:
            logger.warning(f"yfinance earnings_history error ({symbol}): {e}")
            return None

    def get_insider_transactions(self, symbol: str, limit: int = 10) -> list[dict[str, Any]] | None:
        """Get recent insider buy transactions (last 30 days)."""
        if not self.enabled:
            return None
        try:
            self._throttle()
            t = self._ticker(symbol)
            df = t.insider_transactions
            if df is None or df.empty:
                return None
            # Filter to last 30 days
            if 'Start Date' in df.columns:
                cutoff = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
                df['_date_str'] = df['Start Date'].astype(str).str[:10]
                df = df[df['_date_str'] >= cutoff]
                df = df.drop(columns=['_date_str'])
                if df.empty:
                    return None
            results = []
            for idx, row in df.head(limit * 3).iterrows():
                text = row.get("Text", "")
                # Only keep buy transactions
                if "Buy" not in str(text):
                    continue
                date_str = str(row.get("Start Date", ""))[:10]
                results.append({
                    "insider": row.get("Insider", ""),
                    "position": row.get("Position", ""),
                    "shares": int(row.get("Shares", 0)),
                    "value": float(row.get("Value", 0)) if row.get("Value") else None,
                    "transaction": "Buy",
                    "date": date_str,
                    "text": text,
                })
                if len(results) >= limit:
                    break
            return results if results else None
        except Exception as e:
            logger.warning(f"yfinance insider_transactions error ({symbol}): {e}")
            return None

    def get_history(self, symbol: str, period: str = "6mo") -> Any | None:
        """
        Get historical OHLCV data.

        Args:
            symbol: Stock symbol
            period: "1d", "1mo", "3mo", "6mo", "1y", "2y", "3y"

        Returns:
            pandas DataFrame with columns: Open, High, Low, Close, Volume
        """
        if not self.enabled:
            return None
        try:
            self._throttle()
            t = self._ticker(symbol)
            df = t.history(period=period)
            if df is None or df.empty:
                return None
            return df
        except Exception as e:
            logger.warning(f"yfinance history error ({symbol}): {e}")
            return None

    def get_premarket_data(self, symbol: str) -> dict[str, Any] | None:
        """Get pre-market price data."""
        if not self.enabled:
            return None
        try:
            self._throttle()
            t = self._ticker(symbol)
            info = t.info
            pre_price = info.get("preMarketPrice")
            pre_change_pct = info.get("preMarketChangePercent")
            if pre_price is None or pre_change_pct is None:
                return None
            return {
                "symbol": symbol,
                "preMarketPrice": float(pre_price),
                "preMarketChangePercent": float(pre_change_pct),
                "preMarketChange": float(info.get("preMarketChange", 0)),
                "source": "yfinance",
            }
        except Exception as e:
            logger.warning(f"yfinance premarket error ({symbol}): {e}")
            return None

    def get_earnings_dates(self, symbol: str) -> list[dict[str, Any]] | None:
        """Get upcoming earnings dates from yfinance calendar."""
        if not self.enabled:
            return None
        try:
            self._throttle()
            t = self._ticker(symbol)
            cal = t.calendar
            if cal is None:
                return None
            # calendar can be a dict or DataFrame depending on yfinance version
            if isinstance(cal, dict):
                earnings_dates = cal.get("Earnings Date")
                if earnings_dates is None:
                    return None
                dates = earnings_dates if isinstance(earnings_dates, list) else [earnings_dates]
            elif hasattr(cal, 'empty'):
                # DataFrame
                if cal.empty:
                    return None
                earnings_dates = cal.get("Earnings Date")
                if earnings_dates is None:
                    return None
                dates = earnings_dates.tolist() if hasattr(earnings_dates, 'tolist') else [earnings_dates]
            else:
                return None
            results = []
            for d in dates[:4]:
                if hasattr(d, 'strftime'):
                    results.append({"date": d.strftime("%Y-%m-%d")})
                else:
                    results.append({"date": str(d)[:10]})
            return results if results else None
        except Exception as e:
            logger.warning(f"yfinance earnings_dates error ({symbol}): {e}")
            return None

    def get_economic_calendar(
        self, start: str = None, end: str = None, limit: int = 30
    ) -> list[dict[str, Any]] | None:
        """Fetch US economic events calendar via yfinance Calendars API."""
        if not self.enabled:
            return None
        try:
            self._throttle()
            cal = self._yf.Calendars(start=start, end=end)
            df = cal.get_economic_events_calendar(limit=limit)
            if df is None or df.empty:
                return None

            now = datetime.now()
            results = []
            for event_name, row in df.iterrows():
                region = str(row.get("Region", ""))
                if region and region != "US":
                    continue

                event_time = row.get("Event Time")
                if event_time is None or not hasattr(event_time, "strftime"):
                    continue

                date_str = event_time.strftime("%Y-%m-%d")
                days_away = (event_time.replace(tzinfo=None) - now).days
                if days_away < -1:
                    continue

                results.append({
                    "name": str(event_name),
                    "date": date_str,
                    "importance": _classify_economic_importance(str(event_name)),
                    "days_away": days_away,
                    "actual": _fmt_econ_value(row.get("Actual")),
                    "forecast": _fmt_econ_value(row.get("Expected")),
                    "previous": _fmt_econ_value(row.get("Last")),
                })

            results.sort(key=lambda x: x["days_away"])
            return results if results else None
        except Exception as e:
            logger.warning(f"yfinance economic calendar error: {e}")
            return None

    def get_technical_indicators(self, symbol: str, period: str = "1y", history_df=None) -> dict[str, Any] | None:
        """Calculate RSI(14), SMA(50/200), MACD from yfinance history."""
        if not self.enabled:
            return None
        try:
            df = history_df if history_df is not None else self.get_history(symbol, period=period)
            if df is None or len(df) < 50:
                return None

            import numpy as np
            close = df['Close']

            result = {}

            # SMA
            if len(df) >= 50:
                result["sma_50"] = round(float(close.rolling(window=50).mean().iloc[-1]), 2)
            if len(df) >= 200:
                result["sma_200"] = round(float(close.rolling(window=200).mean().iloc[-1]), 2)

            # RSI(14)
            delta = close.diff()
            gain = delta.where(delta > 0, 0.0)
            loss = -delta.where(delta < 0, 0.0)
            avg_gain = gain.rolling(window=14).mean()
            avg_loss = loss.rolling(window=14).mean()
            rs = avg_gain / avg_loss.replace(0, float('inf'))
            rsi = 100 - (100 / (1 + rs))
            rsi_val = rsi.iloc[-1]
            if not (np.isnan(rsi_val) if isinstance(rsi_val, float) else False):
                result["rsi_14"] = round(float(rsi_val), 1)

            # MACD (12, 26, 9)
            ema12 = close.ewm(span=12, adjust=False).mean()
            ema26 = close.ewm(span=26, adjust=False).mean()
            macd_line = ema12 - ema26
            signal_line = macd_line.ewm(span=9, adjust=False).mean()
            macd_hist = macd_line - signal_line
            result["macd_line"] = round(float(macd_line.iloc[-1]), 4)
            result["macd_signal"] = round(float(signal_line.iloc[-1]), 4)
            result["macd_hist"] = round(float(macd_hist.iloc[-1]), 4)

            return result if len(result) > 1 else None
        except Exception as e:
            logger.warning(f"Technical indicators error ({symbol}): {e}")
            return None
