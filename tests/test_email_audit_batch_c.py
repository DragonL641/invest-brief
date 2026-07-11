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
