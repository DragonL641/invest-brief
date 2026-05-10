"""
Industry watchlists for stock recommendations.

Each industry has a curated list of representative stocks used to
find high-conviction analyst picks for the "推荐关注" section.

Keys use GICS sector codes to match the preferences system.
"""

from investbrief.us.industries import US_GICS_SECTORS

INDUSTRY_WATCHLISTS = {
    "information_technology": [
        {"symbol": "AVGO", "name": "Broadcom"},
        {"symbol": "QCOM", "name": "Qualcomm"},
        {"symbol": "TXN", "name": "Texas Instruments"},
        {"symbol": "ARM", "name": "ARM Holdings"},
        {"symbol": "AMAT", "name": "Applied Materials"},
        {"symbol": "KLAC", "name": "KLA Corp"},
        {"symbol": "LRCX", "name": "Lam Research"},
        {"symbol": "MRVL", "name": "Marvell Technology"},
        {"symbol": "NXPI", "name": "NXP Semiconductors"},
        {"symbol": "INTC", "name": "Intel"},
        {"symbol": "TSM", "name": "TSMC"},
        {"symbol": "ASML", "name": "ASML"},
    ],
    "industrials": [
        {"symbol": "LMT", "name": "Lockheed Martin"},
        {"symbol": "RTX", "name": "RTX Corp"},
        {"symbol": "NOC", "name": "Northrop Grumman"},
        {"symbol": "BA", "name": "Boeing"},
        {"symbol": "GD", "name": "General Dynamics"},
        {"symbol": "LHX", "name": "L3Harris"},
        {"symbol": "TDG", "name": "TransDigm"},
        {"symbol": "HEI", "name": "HEICO"},
        {"symbol": "AXON", "name": "Axon Enterprise"},
        {"symbol": "CAT", "name": "Caterpillar"},
        {"symbol": "DE", "name": "John Deere"},
        {"symbol": "MMM", "name": "3M"},
        {"symbol": "ETN", "name": "Eaton"},
        {"symbol": "PH", "name": "Parker-Hannifin"},
        {"symbol": "IR", "name": "Ingersoll Rand"},
        {"symbol": "CMI", "name": "Cummins"},
        {"symbol": "PCAR", "name": "PACCAR"},
    ],
    "consumer_discretionary": [
        {"symbol": "DUOL", "name": "Duolingo"},
        {"symbol": "LRN", "name": "Stride"},
        {"symbol": "STRA", "name": "Strategic Education"},
        {"symbol": "LOPE", "name": "Grand Canyon Education"},
        {"symbol": "COUR", "name": "Coursera"},
    ],
}

INDUSTRY_LABELS = {s["key"]: s["label"] for s in US_GICS_SECTORS}


def get_watchlist_stocks(industries: list) -> list:
    """
    Get all watchlist stocks for given industries.

    Returns list of dicts with symbol, name, industry keys.
    """
    stocks = []
    for industry in industries:
        watchlist = INDUSTRY_WATCHLISTS.get(industry, [])
        for s in watchlist:
            stocks.append({**s, "industry": industry})
    return stocks
