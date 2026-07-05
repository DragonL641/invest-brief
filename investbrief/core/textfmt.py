"""通用文本格式化工具（跨域共享，避免 holdings/mail 互相 import）。

md_inline 把常见 Markdown 模式转成内联 HTML，供邮件渲染复用。
不产生块级元素（无 <h2>/<ul>），避免 CSS 字体继承问题。
"""
import re


def md_inline(text: str) -> str:
    """Convert common Markdown patterns to inline HTML for email rendering.

    Handles: **bold**, *italic*, ## headings (→ styled bold), - list items (→ bullets),
    1. ordered items. Does NOT produce block elements (no <h2>, <ul>) to avoid CSS
    font-size inheritance issues. Newlines become <br>.
    """
    if not text:
        return ""
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<em>\1</em>', text)
    text = re.sub(r'^#{1,3}\s+(.+)$', r'<strong style="display:inline-block;margin:4px 0;">\1</strong>',
                  text, flags=re.MULTILINE)
    text = re.sub(r'^[\-\*]\s+(.+)$', r'<span style="display:block;padding-left:12px;">• \1</span>',
                  text, flags=re.MULTILINE)
    text = re.sub(r'^(\d+)\.\s+(.+)$', r'<span style="display:block;padding-left:12px;">\1. \2</span>',
                  text, flags=re.MULTILINE)
    text = text.replace('\n', '<br>')
    return text
