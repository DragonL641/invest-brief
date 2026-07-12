"""
Email report template-rendering library.

Renders Jinja2 templates (macro / holdings / picks) into Chinese-only email HTML.

Outlook 桌面兼容：渲染后经 ``css_inline.inline`` 把 ``COMPONENT_CSS`` 的 class 规则
**inline 到每个元素**（Outlook 桌面用 Word 引擎，只可靠读取 inline style），并保留
``<style>`` 里的 ``@media``（移动端 WebKit 响应式；Outlook 桌面忽略 @media 不受影响）。

Public API: load_template(), render_template(), render_holdings_template(),
render_picks_template().
"""

from investbrief.core.timeutil import now_cn
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from css_inline import inline as _inline_html

from investbrief.core.textfmt import md_inline
from investbrief.mail.styles import COMPONENT_CSS, MEDIA_CSS, COLOR_UP, COLOR_DOWN, FONT_FAMILY

TEMPLATES_DIR = Path(__file__).parent / "templates"

# autoescape=False: template variables are pre-rendered HTML fragments
# (macro_summary, market_sections, etc.). Escaping would mangle <p> → &lt;p&gt;.
_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=False,
    keep_trailing_newline=True,
)


# ============================================================================
# Language Configuration (single source of truth: investbrief/mail/styles.py)
# ============================================================================

LANGUAGE_CONFIG = {
    'font_family': FONT_FAMILY,
    'color_up': COLOR_UP,
    'color_down': COLOR_DOWN,
}


def get_config(language=None):
    """Chinese-only config (colors, fonts). Language arg ignored (kept for call-site compat)."""
    return LANGUAGE_CONFIG


def load_template(name: str = "email_base.j2") -> str:
    """Load raw template string by name. Kept for existence checks (test_mail_api)."""
    with open(TEMPLATES_DIR / name, encoding='utf-8') as f:
        return f.read()


# ============================================================================
# HTML Building Functions
# ============================================================================

def build_news_html(news_items):
    """Build news items HTML - content from JSON. Class 化（inliner 会 inline）。"""
    html = ''
    for i, item in enumerate(news_items, 1):
        title = item.get('title', '')
        url = item.get('url', '')
        if url:
            title_html = f'<a href="{url}" target="_blank">{title}</a>'
        else:
            title_html = title

        summary = item.get('summary', '')
        if len(summary) > 200:
            summary = summary[:200] + '...'
        summary = md_inline(summary)

        tag_html = ''
        if item.get('tag'):
            tag_html = f'<span class="news-tag">{item["tag"]}</span>'

        html += (
            f'<div class="news-item">'
            f'<div class="news-title">{i}. {title_html}{tag_html}</div>'
            f'<div class="news-summary">{summary}</div>'
            f'<div class="news-meta">{item.get("source", "")} · {item.get("time", "")}</div>'
            f'</div>'
        )
    return html


# ============================================================================
# Template Rendering
# ============================================================================

def _render(template_name: str, ctx: dict) -> str:
    """Jinja2 渲染 + css_inline inline 化（Outlook 桌面兼容）。

    - ``extra_css=COMPONENT_CSS``：class 规则 inline 到每个元素（Outlook 读 inline style）。
    - ``keep_style_tags=True``：保留 ``<style>``（含 @media，移动端响应式）。
    """
    html = _env.get_template(template_name).render(**ctx)
    return _inline_html(html, extra_css=COMPONENT_CSS, keep_style_tags=True)


def _base_context(language: str, data: dict, title: str, disclaimer: str) -> dict:
    """Shared context for macro / holdings / picks templates."""
    cfg = get_config(language)
    return {
        'media_css': MEDIA_CSS,
        'font_family': cfg['font_family'],
        'color_up': cfg['color_up'],
        'color_down': cfg['color_down'],
        'title': title,
        'date': now_cn().strftime('%Y年%m月%d日'),
        'data_time_label': '数据截止',
        'data_time': data.get('data_time', now_cn().strftime('%H:%M:%S')),
        'disclaimer': disclaimer,
        'generated_by': '由 Claude Code 自动生成',
        'generated_at': now_cn().strftime('%Y-%m-%d %H:%M:%S'),
    }


def render_template(template_name: str, data: dict, language: str) -> str:
    """Render the macro email template. First arg is the template NAME (not loaded string)."""
    ctx = _base_context(
        language, data, '宏观经济日报',
        '免责声明：本报告仅供参考，不构成投资建议。投资有风险，入市需谨慎。',
    )
    news = data.get('news') or data.get('global_news') or []
    ctx.update({
        'macro_summary': data.get('macro_summary') or '<p>暂无研判。</p>',
        'risk_outlook': data.get('risk_outlook') or '<p>—</p>',
        'market_sections': data.get('market_section_html', ''),
        'research_views': data.get('research_views') or '',
        'global_news_title': '重要新闻',
        'global_news': build_news_html(news[:5]),
    })
    return _render(template_name, ctx)


def render_holdings_template(template_name: str, data: dict, language: str) -> str:
    """Render the per-recipient holdings email template. First arg is the template NAME."""
    ctx = _base_context(
        language, data, '持仓分析',
        '免责声明：本报告仅供参考，不构成投资建议。数据来自公开渠道，可能存在延迟或误差。',
    )
    ctx.update({
        'holdings_summary': data.get('holdings_summary') or '<p>暂无组合研判。</p>',
        'holdings_sections': data.get('holdings_sections') or '',
    })
    return _render(template_name, ctx)


def render_picks_template(template_name: str, data: dict, language: str) -> str:
    """Render the stock-picks recommendation email template. First arg is the template NAME."""
    ctx = _base_context(
        language, data, '股票推荐',
        '免责声明：本邮件为量化跟踪信号，非投资建议。模型基于历史规律，不预测未来。',
    )
    ctx.update({
        'picks_brief': data.get('picks_brief') or '<p>本期暂无综合研判。</p>',
        'picks_sections': data.get('picks_sections') or '',
    })
    return _render(template_name, ctx)
