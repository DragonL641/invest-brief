"""外围环境卡:数据组装 + 渲染。渲染是纯函数,不触网。"""
from investbrief.market.overseas import fetch_overseas_data, render_overseas_card


def _full_data():
    """6 项齐全的样例 data(quote schema: us_10y/usdcny 为 dict)。"""
    return {
        "fed_rate": 5.25,
        "us_10y": {"value": 4.56, "change": 0.02},
        "sp500": {"point": 7575.39, "change": 0.42},
        "nasdaq": {"point": 18342.5, "change": 0.31},
        "usdcny": {"value": 7.18, "change": None},
        "wti": {"point": 79.34, "change": 1.73},
    }


def test_render_overseas_card_contains_all_6_metrics():
    html = render_overseas_card(_full_data())
    assert "外围环境" in html
    for needle in ("5.25", "4.56", "7575", "18342", "7.18", "79.34"):
        assert needle in html
    assert "美联储利率" in html and "美债10Y" in html and "标普500" in html
    assert "纳斯达克" in html and "美元/人民币" in html and "WTI原油" in html


def test_render_overseas_card_has_6_stat_cells_in_3x2():
    """6 张卡 = 2 行 × 3 列(per_row=3), 无残缺行。"""
    html = render_overseas_card(_full_data())
    assert html.count('<td class="stat"') == 6
    assert html.count("<tr>") == 2          # 2 行


def test_render_overseas_card_missing_metric_degrades():
    """某指标缺失(为 None)时卡片仍渲染,不崩。"""
    data = {"fed_rate": 5.25, "us_10y": None, "sp500": None,
            "nasdaq": None, "usdcny": None, "wti": None}
    html = render_overseas_card(data)
    assert "外围环境" in html
    assert "5.25" in html


def test_render_overseas_card_sp500_change_color_on_delta():
    """标普涨跌色挂在 delta 行(.stat-delta pos/neg), 与 A 股大类资产一致。"""
    base = {"fed_rate": 5.0, "us_10y": {"value": 4.0, "change": 0.01},
            "nasdaq": {"point": 100, "change": 0.1},
            "usdcny": {"value": 7.0, "change": None},
            "wti": {"point": 70, "change": 0.1}}
    up = render_overseas_card({**base, "sp500": {"point": 100, "change": 1.5}})
    down = render_overseas_card({**base, "sp500": {"point": 100, "change": -1.5}})
    assert '"stat-delta pos"' in up
    assert '"stat-delta neg"' in down


def test_render_overseas_card_us_10y_shown_as_bp():
    """美债10Y 变动显示为 bp(收益率惯例), 不是百分比。"""
    html = render_overseas_card(_full_data())     # change=0.02 百分点 → +2bp
    assert "+2bp" in html


def test_render_overseas_card_static_metrics_have_sub_label():
    """美联储利率(静态)/USDCNY(无前值) 用 stat-sub 副标签占位, 保证 6 卡高度统一。"""
    html = render_overseas_card(_full_data())
    assert "目标区间上限" in html
    assert "在岸即期" in html


class _StubAKClient:
    """最小 akshare client stub — 各方法返回固定值,不触网。"""
    def get_us_10y_quote(self):
        return {"value": 4.50, "change": 0.01}

    def get_sp500_quote(self):
        return {"point": 7500.0, "change": 0.3}

    def get_nasdaq_quote(self):
        return {"point": 15000.0, "change": 0.2}

    def get_usdcny_quote(self):
        return {"value": 7.20, "change": None}

    def get_wti_quote(self):
        return {"point": 75.0, "change": 0.5}


def test_fetch_overseas_data_assembles_6_keys():
    data = fetch_overseas_data(_StubAKClient())
    assert data["fed_rate"] == 5.25
    assert data["us_10y"]["value"] == 4.50
    assert data["sp500"]["point"] == 7500.0
    assert data["nasdaq"]["point"] == 15000.0
    assert data["usdcny"]["value"] == 7.20
    assert data["wti"]["point"] == 75.0


def test_fetch_overseas_uses_config_fed_rate():
    data = fetch_overseas_data(_StubAKClient(), fed_rate=4.75)
    assert data["fed_rate"] == 4.75
