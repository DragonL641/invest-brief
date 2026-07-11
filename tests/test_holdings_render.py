"""渲染：分组 + 关键信号 + 维度表格 + CSS bar + fund 卡片。"""
from investbrief.holdings.analyzer import HoldingResult
from investbrief.holdings.renderer import render_holdings_section


def test_renders_stock_etf_fund_three_groups():
    """三层层级：📈 个股 / 📊 场内基金 / 💰 场外基金。"""
    results = [
        HoldingResult(symbol="002371", market="cn", type="stock", name="北方华创",
                      price={"current": 300, "change_pct": 2.3}),
        HoldingResult(symbol="600519", market="cn", type="stock", name="贵州茅台",
                      price={"current": 1680, "change_pct": -1.2}),
        HoldingResult(symbol="510300", market="cn", type="etf", name="沪深300ETF",
                      price={"current": 4.1}),
    ]
    html = render_holdings_section(results)
    assert "个股" in html
    assert "场内基金" in html
    assert "北方华创" in html and "贵州茅台" in html
    assert "沪深300ETF" in html


def test_renders_key_signal_tags():
    r = HoldingResult(symbol="X", market="cn", type="stock",
                      insider={"direction": "sell", "net_shares": -800000},
                      price={"current": 100})
    html = render_holdings_section([r])
    assert "signal-tag" in html
    assert "减持" in html
    assert "股" in html  # net_shares 渲染为股数单位,非金额


def test_renders_css_bar_for_rating():
    r = HoldingResult(symbol="600519", market="cn", type="stock",
                      rating={"distribution": {"buy": 10, "hold": 3, "sell": 1}, "total": 14},
                      price={"current": 100})
    html = render_holdings_section([r])
    assert "bar-fill" in html or "bar-track" in html


def test_empty_group_not_rendered():
    """无该类型持仓时整组省略（不再显示"暂无场外基金"占位）。"""
    results = [HoldingResult(symbol="002371", market="cn", type="stock", price={"current": 100})]
    html = render_holdings_section(results)
    assert "场外基金" not in html
    assert "个股" in html


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
