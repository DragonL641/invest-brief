"""
Email report template-rendering library.

Renders Jinja2 templates (macro / holdings) into Chinese-only email HTML.

Public API: load_template(), render_template(), render_holdings_template().
"""
import re
import logging
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"

# autoescape=False: template variables are pre-rendered HTML fragments
# (macro_summary, market_sections, etc.). Escaping would mangle <p> → &lt;p&gt;.
# Content comes from Claude + public data sources (not user input), and the
# report is an email (not a web page), so XSS risk is acceptable.
_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=False,
    keep_trailing_newline=True,
)


def md_inline(text: str) -> str:
    """Convert common Markdown patterns to inline HTML for email rendering.

    Handles: **bold**, *italic*, ## headings (→ styled bold), - list items (→ bullets).
    Does NOT produce block elements (no <h2>, <ul>) to avoid CSS font-size inheritance issues.
    """
    if not text:
        return ""
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<em>\1</em>', text)
    text = re.sub(r'^#{1,3}\s+(.+)$', r'<strong style="display:inline-block;margin:4px 0;">\1</strong>', text, flags=re.MULTILINE)
    text = re.sub(r'^[\-\*]\s+(.+)$', r'<span style="display:block;padding-left:12px;">• \1</span>', text, flags=re.MULTILINE)
    text = re.sub(r'^(\d+)\.\s+(.+)$', r'<span style="display:block;padding-left:12px;">\1. \2</span>', text, flags=re.MULTILINE)
    text = text.replace('\n', '<br>')
    return text


# ============================================================================
# Language Configuration (minimal - only styling)
# ============================================================================

# Chinese-only styling (red=up, green=down per 中国惯例)
LANGUAGE_CONFIG = {
    'font_family': "'Microsoft YaHei', 'PingFang SC', sans-serif",
    'color_up': '#e74c3c',
    'color_down': '#27ae60',
}


def get_config(language=None):
    """Chinese-only config (colors, fonts). Language arg ignored (kept for call-site compat)."""
    return LANGUAGE_CONFIG


def load_template(name: str = "email_base.j2") -> str:
    """Load raw template string by name. Kept for existence checks (test_mail_api).
    Uses direct file read rather than Jinja2 internals. For rendering, call
    render_template / render_holdings_template directly with a template name."""
    with open(TEMPLATES_DIR / name, 'r', encoding='utf-8') as f:
        return f.read()


# ============================================================================
# HTML Building Functions
# ============================================================================

def build_news_html(news_items):
    """Build news items HTML - content from JSON"""
    html = ''
    for i, item in enumerate(news_items, 1):
        title = item.get('title', '')
        url = item.get('url', '')
        if url:
            title_html = f'<a href="{url}" target="_blank" style="color:#2980b9; text-decoration:underline; font-weight:600;">{title}</a>'
        else:
            title_html = f'<span style="font-weight:600; color:#2c3e50;">{title}</span>'

        summary = item.get('summary', '')
        if len(summary) > 200:
            summary = summary[:200] + '...'
        summary = md_inline(summary)

        tag_html = ''
        if item.get('tag'):
            tag_html = f' <span style="background:#e8f4f8;padding:2px 6px;border-radius:3px;font-size:11px;margin-left:8px;">{item["tag"]}</span>'

        html += f'''
<div class="news-item" style="padding:12px 0; border-bottom:1px solid #f0f0f0;">
    <div style="font-size:14px; margin-bottom:5px;">{i}. {title_html}{tag_html}</div>
    <div style="font-size:13px; color:#6c757d; line-height:1.6;">{summary}</div>
    <div style="font-size:12px; color:#adb5bd; margin-top:5px;">{item.get('source', '')} · {item.get('time', '')}</div>
</div>'''
    return html


# ============================================================================
# Template Rendering
# ============================================================================

def _base_context(language: str, data: dict, title: str, disclaimer: str) -> dict:
    """Shared context for both macro and holdings templates."""
    cfg = get_config(language)
    return {
        'font_family': cfg['font_family'],
        'color_up': cfg['color_up'],
        'color_down': cfg['color_down'],
        'title': title,
        'date': datetime.now().strftime('%Y年%m月%d日'),
        'data_time_label': '数据截止',
        'data_time': data.get('data_time', datetime.now().strftime('%H:%M:%S')),
        'disclaimer': disclaimer,
        'generated_by': '由 Claude Code 自动生成',
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }


def render_template(template_name: str, data: dict, language: str) -> str:
    """Render the macro email template. First arg is the template NAME (not loaded string)."""
    ctx = _base_context(
        language, data, '🗓️ 宏观经济日报',
        '⚠️ 免责声明：本报告仅供参考，不构成投资建议。投资有风险，入市需谨慎。',
    )
    news = data.get('news') or data.get('global_news') or []
    ctx.update({
        'macro_summary': data.get('macro_summary') or '<p>暂无研判。</p>',
        'risk_outlook': data.get('risk_outlook') or '<p>—</p>',
        'market_sections': data.get('market_section_html', ''),
        'research_views': data.get('research_views') or '',
        'global_news_title': '📰 重要新闻',
        'global_news': build_news_html(news[:5]),
    })
    return _env.get_template(template_name).render(**ctx)


def render_holdings_template(template_name: str, data: dict, language: str) -> str:
    """Render the per-recipient holdings email template. First arg is the template NAME."""
    ctx = _base_context(
        language, data, '📊 持仓分析',
        '⚠️ 免责声明：本报告仅供参考，不构成投资建议。数据来自公开渠道，可能存在延迟或误差。',
    )
    ctx.update({
        'holdings_summary': data.get('holdings_summary') or '<p>暂无组合研判。</p>',
        'holdings_sections': data.get('holdings_sections') or '',
    })
    return _env.get_template(template_name).render(**ctx)
