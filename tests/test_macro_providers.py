"""宏观 provider 单测：CN monetary_policy & asset_performance。

US provider 的契约测试见 tests/test_provider_contract.py（P1 起 US provider
改为读 SQLite 数据层，不再 mock yfinance client；旧的 yfinance-mock 用例已废弃）。

CN provider 仍使用 AKShareClient（P1 Task 6 将同样改为数据层）；此处用
MagicMock 替换底层 client，保证无网络、确定性。
"""

from unittest.mock import MagicMock

from investbrief.cn.provider import CNMarketProvider


# ---------------------------------------------------------------------------
# CN provider — self.client
# ---------------------------------------------------------------------------

def test_cn_monetary_policy_delegates():
    p = CNMarketProvider()
    p.client = MagicMock()
    p.client.get_cn_monetary_policy.return_value = {"lpr_1y": 3.0, "m2_yoy": 8.6}
    assert p.get_monetary_policy() == {"lpr_1y": 3.0, "m2_yoy": 8.6}


def test_cn_monetary_policy_resilient():
    p = CNMarketProvider()
    p.client = MagicMock()
    p.client.get_cn_monetary_policy.side_effect = RuntimeError("boom")
    assert p.get_monetary_policy() == {}


def test_cn_asset_performance_has_fx():
    p = CNMarketProvider()
    p.client = MagicMock()
    p.client.get_index_quotes.return_value = []
    p.client.get_fx_rate_usdcny.return_value = {
        "pair": "USDCNY",
        "price": 6.78,
        "change_pct": 0.2,
    }
    assets = p.get_asset_performance()
    fx = [a for a in assets if a["name"] == "人民币汇率(USDCNY)"]
    assert fx and fx[0]["point"] == 6.78
