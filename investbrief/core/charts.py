"""
Stock chart generation for email reports.

Generates PNG charts as base64 for embedding in HTML emails.
"""

import logging
from io import BytesIO
from typing import Optional

logger = logging.getLogger(__name__)

# Use non-interactive backend before importing pyplot
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import base64

# CJK font support
import platform
if platform.system() == 'Darwin':
    plt.rcParams['font.sans-serif'] = ['PingFang SC', 'Heiti SC', 'STHeiti', 'Arial Unicode MS']
elif platform.system() == 'Linux':
    plt.rcParams['font.sans-serif'] = ['Noto Sans CJK SC', 'WenQuanYi Micro Hei', 'Droid Sans Fallback']
plt.rcParams['axes.unicode_minus'] = False


def generate_stock_chart(symbol: str, history_df, period: str = "6mo") -> Optional[str]:
    """
    Generate a stock price chart as base64 PNG.

    Args:
        symbol: Stock symbol for title
        history_df: pandas DataFrame from yfinance history()
        period: Period string for label

    Returns:
        Base64 encoded PNG string, or None on failure
    """
    if history_df is None or history_df.empty:
        return None

    try:
        fig, ax = plt.subplots(figsize=(7.6, 3.0), dpi=100)
        fig.patch.set_facecolor('#ffffff')
        ax.set_facecolor('#fafafa')

        dates = history_df.index
        closes = history_df['Close']

        # Price line
        ax.plot(dates, closes, color='#2980b9', linewidth=1.5, label='Price')

        # Moving average (20-day)
        if len(closes) >= 20:
            ma20 = closes.rolling(window=20).mean()
            ax.plot(dates, ma20, color='#e74c3c', linewidth=1.0, linestyle='--', alpha=0.7, label='MA20')

        # Moving average (50-day)
        if len(closes) >= 50:
            ma50 = closes.rolling(window=50).mean()
            ax.plot(dates, ma50, color='#27ae60', linewidth=1.0, linestyle='--', alpha=0.7, label='MA50')

        # Fill area under price
        ax.fill_between(dates, closes, alpha=0.08, color='#2980b9')

        # Y-axis: start from near the min price to show fluctuations clearly
        price_min, price_max = closes.min(), closes.max()
        padding = (price_max - price_min) * 0.1 or price_min * 0.02
        ax.set_ylim(bottom=price_min - padding)

        # Formatting
        ax.set_title(f'{symbol} - {period}', fontsize=12, fontweight='bold', color='#2c3e50', pad=8)
        ax.legend(loc='upper left', fontsize=8, framealpha=0.8)
        ax.grid(True, alpha=0.2)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)

        # Date formatting
        if len(dates) > 90:
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
            ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
        elif len(dates) > 30:
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
            ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=2))
        else:
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))

        fig.autofmt_xdate(rotation=0, ha='center')
        plt.tight_layout(pad=0.5)

        # Save to base64
        buf = BytesIO()
        fig.savefig(buf, format='png', facecolor='#ffffff', edgecolor='none')
        plt.close(fig)
        buf.seek(0)
        b64 = base64.b64encode(buf.read()).decode('utf-8')
        return b64

    except Exception as e:
        logger.warning(f"Chart generation error ({symbol}): {e}")
        return None
