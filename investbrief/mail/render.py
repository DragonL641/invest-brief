"""
Email report template-rendering library.

Renders Jinja2 templates (macro / holdings) into email HTML, with optional
translation to the recipient's language via the Claude API.

Public API: load_template(), render_template(), render_holdings_template(),
translate_html().
"""
import re
import logging
from datetime import datetime
from pathlib import Path

# Try to import anthropic for translation
try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

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

LANGUAGE_CONFIG = {
    'zh-CN': {
        'font_family': "'Microsoft YaHei', 'PingFang SC', sans-serif",
        'color_up': '#e74c3c',
        'color_down': '#27ae60',
    },
    'ko-KR': {
        'font_family': "'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif",
        'color_up': '#e74c3c',
        'color_down': '#2980b9',
    }
}


def get_config(language):
    """Get language configuration (colors, fonts)"""
    return LANGUAGE_CONFIG.get(language, LANGUAGE_CONFIG['zh-CN'])


def load_template(name: str = "email_base.j2") -> str:
    """Load raw template string by name. Kept for existence checks (test_mail_api).
    Uses direct file read rather than Jinja2 internals. For rendering, call
    render_template / render_holdings_template directly with a template name."""
    with open(TEMPLATES_DIR / name, 'r', encoding='utf-8') as f:
        return f.read()


# ============================================================================
# HTML Translation
# ============================================================================

def translate_html(html_content, target_language, max_retries=2):
    """Translate HTML content to target language using Claude API.

    Strips base64 chart images before translation to reduce payload size,
    then restores them after translation.

    Args:
        html_content: The HTML string to translate
        target_language: 'ko-KR' for Korean, 'zh-CN' returns unchanged
        max_retries: Number of retries on API failure

    Returns:
        Translated HTML string
    """
    if not HAS_ANTHROPIC:
        logger.warning('anthropic package not installed, skipping translation')
        return html_content

    from investbrief.core.llm import get_client, default_model
    client = get_client()
    model = default_model()

    language_names = {
        'zh-CN': 'Simplified Chinese (简体中文)',
        'ko-KR': 'Korean (한국어)',
    }

    target_lang_name = language_names.get(target_language, target_language)

    chart_placeholders = {}
    counter = [0]
    def replace_b64(match):
        key = f"__CHART_PLACEHOLDER_{counter[0]}__"
        chart_placeholders[key] = match.group(0)
        counter[0] += 1
        return key
    html_stripped = re.sub(r'data:image/png;base64,[A-Za-z0-9+/=]+', replace_b64, html_content)

    prompt = f"""Translate the following HTML email content to {target_lang_name}.

Important rules:
1. Only translate the visible text content, preserve ALL HTML tags and attributes exactly as they are
2. Keep numbers, currency symbols, and percentages unchanged (e.g., "$205.27", "+1.71%", "¥68.50", "₩943,000")
3. Keep company names and stock symbols unchanged (e.g., AMD, NVIDIA, Samsung, SK하이닉스, 三星电子)
4. Keep URLs and email addresses unchanged
5. Translate naturally and professionally for a financial/investment context
6. Preserve the HTML structure and formatting completely
7. Keep __CHART_PLACEHOLDER_X__ strings exactly as they are (they are chart image placeholders)

HTML content to translate:
{html_stripped}

Return only the translated HTML, no explanations or markdown code blocks."""

    last_error = None
    for attempt in range(max_retries + 1):
        try:
            with client.messages.stream(
                model=model,
                max_tokens=32000,
                messages=[{"role": "user", "content": prompt}]
            ) as stream:
                translated = ""
                for text in stream.text_stream:
                    translated += text
            translated = re.sub(r'^\s*```(?:html)?\s*\n?', '', translated)
            translated = re.sub(r'\n?\s*```\s*$', '', translated)
            translated = translated.strip()

            for key, b64_data in chart_placeholders.items():
                translated = translated.replace(key, b64_data)

            return translated
        except Exception as e:
            last_error = e
            logger.warning(f'Translation attempt {attempt + 1} failed: {e}')

    logger.warning('All translation attempts failed, sending original HTML')
    return html_content


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
