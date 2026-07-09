"""picks/data.py 的 US financials/industry 必须经 YFinanceClient，不直接用 yf.Ticker。"""
import inspect


def test_picks_data_no_raw_yf_ticker():
    import investbrief.picks.data as d
    for fn_name in ("_us_net_income_by_year", "fetch_earliest_report_period", "fetch_industry"):
        fn = getattr(d, fn_name)
        fsrc = inspect.getsource(fn)
        assert "yf.Ticker" not in fsrc, f"{fn_name} 仍直接用 yf.Ticker（绕节流）"


def test_yfinance_client_has_get_financials():
    from investbrief.datasources.yfinance import YFinanceClient
    assert hasattr(YFinanceClient, "get_financials")
    assert hasattr(YFinanceClient, "get_sector")
