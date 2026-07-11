from investbrief.market.macro_brief import serialize_macro_context


def test_risk_scores_in_claude_context():
    ctx = serialize_macro_context(
        {"美联储利率": 5.25}, {"monetary_policy": {}}, [],
        risk_scores={
            "cn": {"total_score": 44.4, "state": "乐观扩张", "action": "逐步减仓"},
            "gold": {"total_score": 69.1, "state": "狂热泡沫", "action": "大幅减仓"},
        },
    )
    assert "市场周期风险分" in ctx
    assert "跟踪≠预测" in ctx
    assert "A股" in ctx and "44.4" in ctx and "乐观扩张" in ctx
    assert "黄金" in ctx


def test_no_risk_scores_omits_section():
    ctx = serialize_macro_context({"monetary_policy": {}}, {"monetary_policy": {}}, [])
    assert "市场周期风险分" not in ctx


def test_risk_hotspots_and_regime_indicators_feed_claude():
    """B2-2 回归：serialize 把 regime indicators(GDP_YOY/CPI_LATEST) + risk 高分 indicator(score>=8)
    喂给 Claude，让 Claude 写宏观/风险时看到具体数值而非靠新闻拼凑。"""
    ctx = serialize_macro_context(
        {"美联储利率": 5.25}, {"monetary_policy": {}}, [],
        risk_scores={
            "cn": {
                "total_score": 62.4, "state": "狂热泡沫", "risk_level": "high",
                "action": "大幅减仓",
                "indicators": {
                    "market_breadth": {"score": 5.0, "name": "市场宽度低分"},
                    "margin_growth": {"score": 9.5, "name": "两融增速"},
                    "valuation": {"score": 7.0, "name": "估值"},
                },
            },
        },
        regime_data={
            "cn": {
                "quadrant": "通胀", "confidence": 90,
                "growth_axis": "扩张", "inflation_axis": "上行",
                "indicators": {"GDP_YOY": 2.5, "CPI_LATEST": 3.1},
            },
        },
    )
    # regime 关键值
    assert "GDP_YOY=2.5" in ctx
    assert "CPI_LATEST=3.1" in ctx
    # risk 高分项（score>=8 才入选；market_breadth 5.0 / valuation 7.0 应被排除）
    assert "两融增速" in ctx and "9.5" in ctx
    assert "极端指标" in ctx
    # 低分项不出现在极端指标行
    hot_line = next((l for l in ctx.split("\n") if "极端指标" in l), "")
    assert "市场宽度低分" not in hot_line and "估值" not in hot_line
