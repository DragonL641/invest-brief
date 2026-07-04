"""渲染：分组 + 关键信号 + 维度表格 + CSS bar + fund 卡片。"""
from investbrief.holdings.analyzer import HoldingResult
from investbrief.holdings.renderer import render_holdings_section


def test_renders_on_off_market_groups():
    results = [
        HoldingResult(symbol="002371", market="cn", type="stock", name="北方华创",
                      price={"current": 300, "change_pct": 2.3}),
        HoldingResult(symbol="AAPL", market="us", type="stock", name="Apple",
                      price={"current": 150, "change_pct": -1.2}),
    ]
    html = render_holdings_section(results)
    assert "场内持仓" in html
    assert "北方华创" in html and "Apple" in html


def test_renders_key_signal_tags():
    r = HoldingResult(symbol="X", market="cn", type="stock",
                      insider={"direction": "sell", "net_amount": -800000},
                      price={"current": 100})
    html = render_holdings_section([r])
    assert "signal-tag" in html
    assert "减持" in html


def test_renders_css_bar_for_rating():
    r = HoldingResult(symbol="X", market="us", type="stock",
                      rating={"distribution": {"buy": 10, "hold": 3, "sell": 1}, "total": 14},
                      price={"current": 100})
    html = render_holdings_section([r])
    assert "bar-fill" in html or "bar-track" in html


def test_off_market_group_empty_state():
    results = [HoldingResult(symbol="002371", market="cn", type="stock", price={"current": 100})]
    html = render_holdings_section(results)
    assert "场外基金" in html
    assert "暂无" in html


def test_fund_routed_to_off_market():
    results = [HoldingResult(symbol="000001", market="cn", type="fund", name="测试基金",
                             price={"current": 1.5})]
    html = render_holdings_section([r for r in results])
    assert "场外基金" in html
    assert "测试基金" in html


def test_fund_card_shows_nav_and_meta():
    r = HoldingResult(symbol="000001", market="cn", type="fund", name="测试基金",
                      price={"current": 1.5, "change_pct": 0.3, "acc_nav": 2.0},
                      fundamentals={"return_1m": 2.1},
                      fund_meta={"scale": 12.3, "manager": "张三", "rating": "★★★"})
    html = render_holdings_section([r])
    assert "测试基金" in html
    assert "张三" in html
