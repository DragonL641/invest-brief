"""akshare 外围数据接口契约:美债10Y / 标普500 / USDCNY实时 / QVIX。network 测试,标记跳过 CI。"""
import pytest
from investbrief.datasources.akshare import AKShareClient

pytestmark = pytest.mark.network


def test_us_treasury_10y_returns_float():
    v = AKShareClient().get_us_treasury_10y()
    assert isinstance(v, float) and 0 < v < 20   # 美债10Y 合理区间


def test_sp500_quote_returns_point_and_change():
    q = AKShareClient().get_sp500_quote()
    assert isinstance(q, dict)
    assert isinstance(q["point"], (int, float)) and q["point"] > 0
    assert "change" in q                          # 涨跌幅 %


def test_fx_usdcny_realtime_returns_float():
    v = AKShareClient().get_fx_usdcny_realtime()
    assert isinstance(v, float) and 6 < v < 8     # USDCNY 合理区间
