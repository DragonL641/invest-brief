"""邮件体检批次 C 回归测试(spec: 批次 C, #8 补卡片)。"""
from investbrief.holdings.analyzer import HoldingResult
from investbrief.holdings.renderer import _render_dimensions


def test_stock_card_shows_volume_ratio_and_boll():
    """#8a 个股卡技术面补渲染量比 + 布林位置(AI 高频引用)。"""
    r = HoldingResult(
        symbol="002230", market="cn", type="stock", name="科大讯飞",
        technicals={"rsi": 47.2, "ma_alignment": "mixed", "macd_cross": "none",
                    "volume_ratio": 1.46, "boll_position": 87.3},
    )
    html = _render_dimensions(r)
    assert "量比" in html and "1.46" in html
    assert "布林" in html and "87.3" in html


def test_etf_card_shows_premium_and_signals():
    """#8a ETF 卡补溢价率 + 命中规则信号(AI 高频引用折价率)。"""
    from investbrief.holdings.etf.engine import RuleResult
    r = HoldingResult(
        symbol="588200", market="cn", type="etf", name="科创芯片ETF",
        price={"current": 4.57, "premium_rate": -1.27},
        signals=[RuleResult(rule_id="x", dimension="趋势", name="均线多头",
                            description="", signal="bullish", matched=True, weight=1.0)],
    )
    html = _render_dimensions(r)
    assert "溢价率" in html and "-1.27" in html
    assert "均线多头" in html and "多" in html  # signal bullish→多
