"""Risk score regression — 固定 DB 输入应产出稳定分数。

重构前后跑此测试, 分数漂移即说明 indicator 改造引入了数值变化。
DB 无数据时 skip (CI 兼容)。
"""
import pytest

from investbrief.data.cn_data import CNData
from investbrief.data.us_data import USData
from investbrief.data.gold_data import GoldData
from investbrief.risk.models import RiskModel


def _db_has_data():
    try:
        cn = CNData()
        df = cn.query("SELECT COUNT(*) AS c FROM cn_index_daily")
        cn.close()
        return int(df.iloc[0]["c"]) > 100
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_has_data(), reason="needs P1-populated macro_data.db")


@pytest.mark.parametrize("market_code,data_cls,expected_min,expected_max", [
    ("us", USData, 0.0, 100.0),
    ("cn", CNData, 0.0, 100.0),
    ("gold", GoldData, 0.0, 100.0),
])
def test_calculate_score_stable_range(market_code, data_cls, expected_min, expected_max):
    """三个市场的总分都落在 0-100 合法区间, 且 dimensions 五维齐全(非空)。"""
    data = data_cls()
    try:
        model = RiskModel(data)
        score = model.calculate_score(market_code)
        assert expected_min <= score["total_score"] <= expected_max
        assert score["market"] == market_code
        assert set(["估值风险", "技术面风险", "流动性风险", "情绪面风险", "宏观基本面风险"]).issubset(
            score["dimensions"].keys()
        ) or market_code == "gold"  # gold 维度结构不同
    finally:
        data.close()


def test_us_cn_gold_scores_recorded():
    """记录当前分数到 stdout(人工核对, 非断言)。

    重构前跑一次记下数值, 重构后应一致。此测试只保证不报错。
    """
    results = {}
    for code, cls in [("us", USData), ("cn", CNData), ("gold", GoldData)]:
        data = cls()
        try:
            model = RiskModel(data)
            results[code] = model.calculate_score(code)["total_score"]
        finally:
            data.close()
    print(f"\n[REGRESSION BASELINE] scores: {results}")
    assert len(results) == 3
