"""邮件体检批次 D 回归测试(spec: #10 regime 措辞)。"""


def test_regime_unknown_axis_shows_signal_insufficient():
    """#10 方向投票 unknown 时 axis 显示「信号不足」而非「未知」(避免观感像坏掉)。"""
    from investbrief.regime.engine import _judge_from_series
    r = _judge_from_series(
        [100, 105, 108, 112, 116],   # GDP 绝对值(季频,5 期)→ YoY 仅 1 期(<window+1)→ growth unknown
        [0.5, 0.5, 0.6, 0.5],         # CPI 同比,diffs: 0, +0.1, -0.1 → up1/down1 → inflation unknown
        "cn",
    )
    assert r["growth_axis"] == "信号不足"
    assert r["inflation_axis"] == "信号不足"
