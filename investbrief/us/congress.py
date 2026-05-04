"""
Congressional Trading Tracker

Fetches recent stock trades by US Congress members from public data sources:
- house-stock-watcher (House representatives)
- senate-stock-watcher (Senators)

Both are public S3-hosted JSON files, no API key needed.
"""

import logging
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

HOUSE_URL = "https://house-stock-watcher.s3-us-west-2.amazonaws.com/data/all_transactions.json"
SENATE_URL = "https://senate-stock-watcher.s3-us-west-2.amazonaws.com/data/data_report/all_transactions.json"

_TIMEOUT = 15
_MAX_PROCESS = 500


def get_recent_congressional_trades(
    days: int = 30,
    tickers: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Fetch recent congressional trades, optionally filtered by tickers.

    Args:
        days: How many days back to look
        tickers: Optional list of tickers to filter by

    Returns:
        List of trade dicts sorted by date descending
    """
    cutoff = datetime.now() - timedelta(days=days)
    ticker_set = set(tickers) if tickers else None
    trades = []

    for source, url in [("House", HOUSE_URL), ("Senate", SENATE_URL)]:
        try:
            resp = requests.get(url, timeout=_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()

            for item in data[:_MAX_PROCESS]:
                tx_date_str = item.get("transaction_date", "")
                if not tx_date_str:
                    continue
                for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
                    try:
                        tx_date = datetime.strptime(tx_date_str, fmt)
                        break
                    except ValueError:
                        continue
                else:
                    continue

                if tx_date < cutoff:
                    continue

                ticker = item.get("ticker", "")
                if not ticker or ticker == "--":
                    continue
                if ticker_set and ticker not in ticker_set:
                    continue

                trades.append({
                    "representative": item.get("representative", item.get("senator", "")),
                    "ticker": ticker,
                    "asset_name": item.get("asset_description", ""),
                    "transaction_type": item.get("type", item.get("transaction_type", "")),
                    "amount": item.get("amount", ""),
                    "transaction_date": tx_date.strftime("%Y-%m-%d"),
                    "source": source,
                })

        except Exception as e:
            logger.warning(f"Congressional trades fetch error ({source}): {e}")

    trades.sort(key=lambda x: x["transaction_date"], reverse=True)
    return trades[:20]
