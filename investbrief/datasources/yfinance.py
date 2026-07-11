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

_RATE_LIMIT_MARKERS = ("too many requests", "429", "rate limit", "rate limited")


def _is_rate_limited(exc: Exception) -> bool:
    """识别 yfinance/curl_cffi 抛出的限流异常（按 message 文本，跨端点统一）。"""
    msg = str(exc).lower()
    return any(m in msg for m in _RATE_LIMIT_MARKERS)


def _to_float(val) -> float | None:
    """pandas cell → float；None / 非数 / NaN → None。get_quote 派生用。"""
    if val is None:
        return None
    try:
        v = float(val)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else v


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
    # Session timeout/retry: yfinance's default curl_cffi session hangs 30s per
    # endpoint with its own internal retry loop. We cap at 8s + 3 retries so a
    # dead network fails fast instead of blocking 150s (5 endpoints × 30s).
    _TIMEOUT = 8
    _RETRIES = 3

    def __init__(self):
        try:
            import yfinance
            self._yf = yfinance
            self.enabled = True
        except ImportError:
            self._yf = None
            self.enabled = False
        self._session = self._build_session()
        self._ticker_cache: dict = {}
        self._history_cache: dict = {}
        self._max_cache = 50

    @classmethod
    def _build_session(cls):
        """Build a session with short timeout + bounded retries.

        Preferred: curl_cffi.Session (yfinance 1.3.0 default transport) with
        ``timeout=8, retry=3``. curl_cffi uses ``retry`` (not ``retries``).
        Fallback: requests.Session + HTTPAdapter(Retry(total=3)) — loses curl
        impersonation but keeps timeout/retry controllable.
        """
        try:
            from curl_cffi.requests import Session as CurlSession
            return CurlSession(timeout=cls._TIMEOUT, retry=cls._RETRIES)
        except Exception as e:  # noqa: BLE001 — any import/construct failure → fallback
            logger.warning(f"curl_cffi Session unavailable ({e}); fallback to requests.Session")
            import requests
            from requests.adapters import HTTPAdapter
            try:
                from urllib3.util.retry import Retry
                adapter = HTTPAdapter(max_retries=Retry(total=cls._RETRIES, backoff_factor=0.3))
            except Exception:  # noqa: BLE001
                adapter = HTTPAdapter()
            s = requests.Session()
            s.mount("https://", adapter)
            s.mount("http://", adapter)
            return s

    @classmethod
    def _throttle(cls):
        """Block until enough time has passed since the last yfinance request."""
        with cls._lock:
            now = time.monotonic()
            wait = cls._MIN_INTERVAL - (now - cls._last_request)
            if wait > 0:
                time.sleep(wait)
            cls._last_request = time.monotonic()

    @classmethod
    def _call_with_retry(cls, op, *, label: str, max_retries: int = 3):
        """执行 op()。限流异常 → 指数退避(1/2s，末次直接放弃)重试；非限流异常或超上限 → 抛出。

        与 _throttle 配合：_throttle 控主动速率(2.5 QPS)，本方法控被动恢复(被 429 后退避)。
        """
        for attempt in range(max_retries):
            try:
                return op()
            except Exception as e:
                if not _is_rate_limited(e) or attempt == max_retries - 1:
                    raise
                delay = 2 ** attempt  # 1, 2
                logger.warning(f"yfinance {label} rate-limited, retry {attempt+1}/{max_retries} after {delay}s")
                time.sleep(delay)
        return None  # unreachable

    def _ticker(self, symbol: str):
        if len(self._ticker_cache) > self._max_cache:
            oldest = next(iter(self._ticker_cache))
            del self._ticker_cache[oldest]
        if symbol not in self._ticker_cache:
            self._ticker_cache[symbol] = self._yf.Ticker(symbol, session=self._session)
        return self._ticker_cache[symbol]

    # ==================== Price ====================

    def get_quote(self, symbol: str) -> dict[str, Any] | None:
        """Current price derived from a short history window (一次请求避开 429)。

        旧实现一次性读 fast_info 的 6 个属性(last_price/previous_close/day_high/
        day_low/last_volume/market_cap),触发 yahoo "Too Many Requests",重试耗尽
        后返回 None。改用一次 get_history(period="5d") 从 OHLCV 派生,请求次数从
        多次降到 1。market_cap 是死端字段(下游只读 price/change_percent)且
        analyzer.py 已有 info.get("market_cap") 兜底,故不再返回。

        返回 None 兼作 yfinance 可达性探针(analyzer.py:433 据此跳过其余 endpoint)。
        """
        if not self.enabled:
            return None
        try:
            df = self.get_history(symbol, period="5d")
            if df is None or df.empty:
                return None
            last = df.iloc[-1]
            close = _to_float(last.get("Close"))
            if close is None:
                return None
            prev = _to_float(df.iloc[-2].get("Close")) if len(df) >= 2 else None
            change = round(close - prev, 4) if prev is not None else 0.0
            change_pct = round((close - prev) / prev * 100, 2) if prev else 0.0
            vol = _to_float(last.get("Volume"))
            return {
                "price": close,
                "previous_close": prev,
                "change": change,
                "change_percent": change_pct,
                "day_high": _to_float(last.get("High")),
                "day_low": _to_float(last.get("Low")),
                "volume": int(vol) if vol is not None else None,
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

    def get_financials(self, symbol: str) -> Any | None:
        """yfinance Ticker.financials（年度，DataFrame）。经节流+退避。"""
        if not self.enabled:
            return None
        try:
            def _op():
                self._throttle()
                df = self._ticker(symbol).financials
                if df is None or df.empty:
                    return None
                return df
            return self._call_with_retry(_op, label=f"financials({symbol})")
        except Exception as e:
            logger.warning(f"yfinance financials error ({symbol}): {e}")
            return None

    def get_sector(self, symbol: str) -> str | None:
        """yfinance info['sector']。经节流（复用 get_info，无退避）。"""
        info = self.get_info(symbol) or {}
        s = info.get("sector")
        return str(s) if s else None

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
            def _op():
                self._throttle()
                t = self._ticker(symbol)
                df = t.history(period=period)
                if df is None or df.empty:
                    return None
                return df
            return self._call_with_retry(_op, label=f"history({symbol})")
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
