# tests/test_picks_us_symbol.py
"""picks pipeline: US symbol cleaning (strip akshare 市场码 prefix)."""
from investbrief.pipelines.picks import _clean_us_symbol


def test_strips_numeric_market_prefix():
    assert _clean_us_symbol("105.AMZN") == "AMZN"   # NASDAQ
    assert _clean_us_symbol("106.BABA") == "BABA"   # NYSE
    assert _clean_us_symbol("107.TSM") == "TSM"


def test_no_numeric_prefix_unchanged():
    """Tickers without a numeric market-code prefix pass through unchanged."""
    assert _clean_us_symbol("BRK.B") == "BRK.B"     # dot but non-numeric prefix
    assert _clean_us_symbol("AAPL") == "AAPL"
    assert _clean_us_symbol("") == ""
