"""USData 指数 history 必须经 YFinanceClient（共享 _throttle），不直接用 yf.Ticker。"""


def test_us_data_uses_yfinance_client():
    import investbrief.data.us_data as us_mod
    import inspect

    src = inspect.getsource(us_mod.USData)
    assert "yf.Ticker" not in src, "USData 仍直接用 yf.Ticker（绕过节流），需收口到 YFinanceClient"
