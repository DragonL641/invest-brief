"""外围环境卡:数据组装 + 渲染。渲染是纯函数,不触网。"""
from investbrief.market.overseas import fetch_overseas_data, render_overseas_card


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
    """标普涨为红(A股配色:红涨),跌为绿。涨跌色由 .pos/.neg class 控制(styles.css)。"""
    up = render_overseas_card({"fed_rate": 5.0, "us_10y": 4.0, "sp500": {"point": 100, "change": 1.5}, "usdcny": 7.0})
    down = render_overseas_card({"fed_rate": 5.0, "us_10y": 4.0, "sp500": {"point": 100, "change": -1.5}, "usdcny": 7.0})
    assert '"stat-value pos"' in up      # 涨 → 红
    assert '"stat-value neg"' in down    # 跌 → 绿


class _StubAKClient:
    """最小 akshare client stub — 各方法返回固定值,不触网。"""
    def get_us_treasury_10y(self):
        return 4.50

    def get_sp500_quote(self):
        return {"point": 7500.0, "change": 0.3}

    def get_fx_usdcny_realtime(self):
        return 7.20


def test_fetch_overseas_data_default_fed_rate():
    """不传 fed_rate 时回退到 FED_FUNDS_RATE 常量(默认 5.25)。"""
    data = fetch_overseas_data(_StubAKClient())
    assert data["fed_rate"] == 5.25
    assert data["us_10y"] == 4.50
    assert data["sp500"]["point"] == 7500.0
    assert data["usdcny"] == 7.20


def test_fetch_overseas_uses_config_fed_rate():
    """fed_rate 参数透传到 data(可由 config.json 的 fed_funds_rate 覆盖默认)。"""
    data = fetch_overseas_data(_StubAKClient(), fed_rate=4.75)
    assert data["fed_rate"] == 4.75
