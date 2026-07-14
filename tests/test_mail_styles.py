"""邮件样式回归:防止 .stat 瘦身参数被回退。"""
from investbrief.mail.styles import COMPONENT_CSS


def _block(css: str, selector: str) -> str:
    """取 `selector { ... }` 块内文本(到第一个 })。selector 需含尾空格以精确匹配。"""
    i = css.index(selector)
    return css[i:css.index("}", i)]


def test_stat_value_slimmed_to_16px_sans():
    blk = _block(COMPONENT_CSS, ".stat-value ")
    assert "font-size: 16px" in blk
    assert "PingFang SC" in blk        # SANS 栈
    assert "Georgia" not in blk         # 不再用衬线
    assert "font-weight: 600" in blk


def test_stat_value_not_21px():
    blk = _block(COMPONENT_CSS, ".stat-value ")
    assert "font-size: 21px" not in blk


def test_stat_no_tint_background():
    blk = _block(COMPONENT_CSS, ".stat ")
    assert "#faf9f6" not in blk         # 去米底
    assert "transparent" in blk


def test_summary_box_left_accent_bar():
    blk = _block(COMPONENT_CSS, ".summary-box ")
    assert "border-left: 3px solid" in blk and "#b8232e" in blk   # ACCENT 红左条
    assert "#fcfbf9" in blk                                        # 极淡底
    assert "border-top: 2px" not in blk                            # 去黑顶线


def test_brief_box_left_accent_bar():
    blk = _block(COMPONENT_CSS, ".brief-box ")
    assert "border-left: 3px solid" in blk and "#b8232e" in blk
    assert "#fcfbf9" in blk
    assert "border-top: 2px" not in blk


def test_secondary_boxes_no_tint():
    for sel in (".ai-box ", ".logic-box ", ".risk-wrap ", ".regime-wrap "):
        blk = _block(COMPONENT_CSS, sel)
        assert "#faf9f6" not in blk                                 # 去米底


def test_footer_notice_transparent():
    for sel in (".footer ", ".notice "):
        blk = _block(COMPONENT_CSS, sel)
        assert "#faf9f6" not in blk
        assert "transparent" in blk


def test_signal_and_news_tag_no_tint():
    for sel in (".signal-tag-up ", ".signal-tag-down ", ".signal-tag-warn ",
                ".signal-tag-neutral ", ".news-tag "):
        blk = _block(COMPONENT_CSS, sel)
        assert "#faf9f6" not in blk


def test_font_sizes_slimmed():
    assert "font-size: 25px" in _block(COMPONENT_CSS, ".masthead-title ")
    assert "font-size: 29px" not in _block(COMPONENT_CSS, ".masthead-title ")
    assert "font-size: 20px" in _block(COMPONENT_CSS, ".section-title ")
    assert "font-size: 24px" in _block(COMPONENT_CSS, ".risk-score ")


def test_masthead_border_thinned():
    blk = _block(COMPONENT_CSS, ".masthead ")
    assert "border-bottom: 2px solid" in blk
    assert "border-bottom: 3px solid" not in blk
