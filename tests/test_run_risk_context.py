from run import _serialize_macro_context


def test_risk_scores_in_claude_context():
    ctx = _serialize_macro_context(
        {"monetary_policy": {}}, {"monetary_policy": {}}, [],
        risk_scores={
            "us": {"total_score": 62.4, "state": "狂热泡沫", "action": "大幅减仓"},
            "cn": {"total_score": 44.4, "state": "乐观扩张", "action": "逐步减仓"},
            "gold": {"total_score": 69.1, "state": "狂热泡沫", "action": "大幅减仓"},
        },
    )
    assert "市场周期风险分" in ctx
    assert "跟踪≠预测" in ctx
    assert "美股" in ctx and "62.4" in ctx and "狂热泡沫" in ctx
    assert "A股" in ctx and "黄金" in ctx


def test_no_risk_scores_omits_section():
    ctx = _serialize_macro_context({"monetary_policy": {}}, {"monetary_policy": {}}, [])
    assert "市场周期风险分" not in ctx
