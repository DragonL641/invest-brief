"""外围环境卡:数据组装 + 渲染。渲染是纯函数,不触网。"""
from investbrief.market.overseas import render_overseas_card


def test_render_overseas_card_contains_all_metrics():
    data = {
        "fed_rate": 5.25,
        "us_10y": 4.56,
        "sp500": {"point": 7575.39, "change": 0.42},
        "usdcny": 7.18,
    }
    html = render_overseas_card(data)
    assert "外围环境" in html
    assert "5.25" in html and "4.56" in html and "7575" in html and "7.18" in html


def test_render_overseas_card_missing_metric_degrades():
    """某指标缺失(为 None)时卡片仍渲染,不崩。"""
    data = {"fed_rate": 5.25, "us_10y": None, "sp500": None, "usdcny": None}
    html = render_overseas_card(data)
    assert "外围环境" in html          # 不抛异常,降级展示
    assert "5.25" in html


def test_render_overseas_card_sp500_change_color():
    """标普涨为红(A股配色:红涨),跌为绿。"""
    up = render_overseas_card({"fed_rate": 5.0, "us_10y": 4.0, "sp500": {"point": 100, "change": 1.5}, "usdcny": 7.0})
    down = render_overseas_card({"fed_rate": 5.0, "us_10y": 4.0, "sp500": {"point": 100, "change": -1.5}, "usdcny": 7.0})
    assert "#e74c3c" in up and "#27ae60" in down
