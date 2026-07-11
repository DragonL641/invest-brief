"""find_similar_periods 契约测试：不原地修改入参 history_df。"""
from unittest.mock import MagicMock

import pandas as pd

from investbrief.risk.models import RiskModel


def test_find_similar_periods_does_not_mutate_input():
    """find_similar_periods 必须对入参 history_df 做 copy,不能原地加 score_diff 列。

    回归:旧实现 `history["score_diff"] = ...` 直接在入参上原地加列,调用方继续用该
    DataFrame 会发现被改。改为 .assign() 返回新 df,消除副作用。
    """
    history_df = pd.DataFrame({
        "date": ["2024-01-01", "2024-02-01", "2024-03-01"],
        "total_score": [45.0, 50.0, 55.0],
        "state": ["中性", "谨慎", "谨慎"],
    })
    original_cols = list(history_df.columns)

    # data source mock: query 返回空 DataFrame,避免依赖真实 DB(后续收益计算会得到 None)
    ds = MagicMock()
    ds.query.return_value = pd.DataFrame()
    model = RiskModel(ds, indicators=[])

    result = model.find_similar_periods("cn", 50.0, history_df=history_df)

    # 核心断言:入参未被加 score_diff 列
    assert "score_diff" not in history_df.columns
    assert list(history_df.columns) == original_cols
    # 返回值仍是 list[dict](DB mock 为空 → subsequent_return=None,结构仍在)
    assert isinstance(result, list)
    if result:
        assert "total_score" in result[0]
