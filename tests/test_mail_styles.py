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
