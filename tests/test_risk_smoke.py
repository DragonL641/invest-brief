"""P2 冒烟测试：RiskModel 针对 P1 填充的真实 SQLite 计算 cn/us 风险分。

依赖 data/macro_data.db 已被 P1 的 --update/backfill 填充；否则 skip。
目的：验证移植后的指标链端到端跑通、且确实在算（非全回退 5.0 → 总分 50）。
"""
import os
from pathlib import Path

import pytest

from investbrief.config import DB_PATH
from investbrief.data.cn_data import CNData
from investbrief.data.gold_data import GoldData
from investbrief.data.us_data import USData
from investbrief.risk.models import RiskModel


def _db_has_data() -> bool:
    if not os.path.exists(DB_PATH):
        return False
    try:
        ds = USData()
        n = ds.query("SELECT COUNT(*) AS n FROM us_index_daily").iloc[0]["n"]
        ds.close()
        return n > 100
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_has_data(), reason="needs P1-populated data/macro_data.db")


@pytest.mark.parametrize("market, cls", [("cn", CNData), ("us", USData), ("gold", GoldData)])
def test_calculate_score_real_db(market, cls):
    """calculate_score 端到端：结构正确 + 分数在 0-100 + 维度非全 5.0（确实在算）。"""
    ds = cls()
    try:
        result = RiskModel(ds).calculate_score(market)
    finally:
        ds.close()

    # 结构契约
    assert isinstance(result, dict)
    for key in ("total_score", "state", "crash_prob", "expected_return",
                "action", "dimensions", "indicators", "date", "market"):
        assert key in result, f"缺 key: {key}"

    # 分数范围
    score = result["total_score"]
    assert isinstance(score, float)
    assert 0.0 <= score <= 100.0

    # 维度是 dict，且至少有一个维度分 ≠ 5.0（证明指标真的算出非中性值，而非全回退）
    dims = result["dimensions"]
    assert isinstance(dims, dict) and len(dims) > 0
    non_neutral = [v for v in dims.values() if abs(v - 5.0) > 0.01]
    assert non_neutral, f"{market} 所有维度都是 5.0，指标可能未读到数据: {dims}"

    # 指标层有实际结果（至少一个 indicator 有 value 非 None）
    inds = result["indicators"]
    has_value = any(isinstance(v, dict) and v.get("value") is not None for v in inds.values())
    assert has_value, f"{market} 所有指标 value 都是 None，数据层可能没喂到"

    # 打印供人工研判（-s 时可见）
    print(f"\n[{market}] total_score={score} state={result['state']} "
          f"crash_prob={result['crash_prob']} action={result['action']}")
    print(f"[{market}] dimensions={dims}")
    scored = {k: v for k, v in inds.items() if isinstance(v, dict) and v.get("value") is not None}
    print(f"[{market}] indicators with value ({len(scored)}/{len(inds)}): "
          + ", ".join(f"{k}={v.get('score')}" for k, v in list(scored.items())[:8]))

