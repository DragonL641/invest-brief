"""
AI Output Guards

EarningsGuard: Suppresses strong buy recommendations near earnings dates.
PostAIGuard: Verifies AI output prices match actual market data.
"""

import logging
import re
from typing import Dict, List

logger = logging.getLogger(__name__)


class EarningsGuard:
    """Downgrade buy recommendations near earnings dates."""

    def __init__(self, earnings_calendar: List[Dict]):
        self.calendar = earnings_calendar

    def check(self, summary: str) -> str:
        """Scan summary for near-earnings symbols and downgrade suggestions."""
        for event in self.calendar:
            symbol = event["symbol"]
            days = event["days_away"]
            if days <= 3:
                # Within 3 days: suppress all buy suggestions for this symbol
                summary = re.sub(
                    rf'({symbol}[^<]*(?:强烈买入|强烈推荐|建议买入|STOCK BUY|STRONG BUY))',
                    f'{symbol} — 财报临近，建议持有观望',
                    summary, flags=re.IGNORECASE
                )
            elif days <= 7:
                # Within 7 days: suppress strong buy only
                summary = re.sub(
                    rf'({symbol}[^<]*(?:强烈买入|STRONG BUY))',
                    f'{symbol} — 财报临近，谨慎持有',
                    summary, flags=re.IGNORECASE
                )
        return summary


class PostAIGuard:
    """Verify AI output prices match actual data."""

    def __init__(self, market_data: Dict):
        self.prices = {}
        self.changes = {}
        for h in market_data.get("holdings", []):
            symbol = h.get("symbol", "")
            price = h.get("price", 0)
            if symbol and price:
                self.prices[symbol] = price
                self.changes[symbol] = h.get("change", 0)

    def check(self, summary: str) -> str:
        """Find and verify prices in AI output. Fix mismatches >5%."""
        fixes = 0
        for symbol, actual_price in self.prices.items():
            # Match patterns like "$205.27" or "$1,205.27" within 80 chars of symbol
            pattern = rf'({symbol}[^$]{{0,80}})\$([0-9]{{1,3}}(?:,[0-9]{{3}})*\.\d{{2}})'
            for match in re.finditer(pattern, summary):
                cited_str = match.group(2).replace(',', '')
                try:
                    cited_price = float(cited_str)
                except ValueError:
                    continue
                if actual_price > 0 and abs(cited_price - actual_price) / actual_price > 0.05:
                    logger.warning(
                        f"AI price mismatch: {symbol} cited ${cited_price:.2f}, actual ${actual_price:.2f}"
                    )
                    old = match.group(0)
                    new_price_str = f"${actual_price:,.2f}"
                    new = old.replace(f"${match.group(2)}", new_price_str)
                    summary = summary.replace(old, new)
                    fixes += 1
        if fixes:
            logger.info(f"PostAIGuard fixed {fixes} price mismatches")
        return summary
