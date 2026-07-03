"""
Email report template-rendering library.

Loads the base HTML template and renders it with macro report data, with
optional translation to the recipient's language via the Claude API.

Public API: load_template(), render_template(), translate_html().
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

logger = logging.getLogger(__name__)


def md_inline(text: str) -> str:
    """Convert common Markdown patterns to inline HTML for email rendering.

    Handles: **bold**, *italic*, ## headings (→ styled bold), - list items (→ bullets).
    Does NOT produce block elements (no <h2>, <ul>) to avoid CSS font-size inheritance issues.
    """
    if not text:
        return ""
    # Bold: **text**
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    # Italic: *text* (avoid matching inside <strong> tags)
    text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<em>\1</em>', text)
    # Headings: ## text → styled bold span
    text = re.sub(r'^#{1,3}\s+(.+)$', r'<strong style="display:inline-block;margin:4px 0;">\1</strong>', text, flags=re.MULTILINE)
    # Unordered list: - text or * text → indented bullet
    text = re.sub(r'^[\-\*]\s+(.+)$', r'<span style="display:block;padding-left:12px;">• \1</span>', text, flags=re.MULTILINE)
    # Ordered list: 1. text
    text = re.sub(r'^(\d+)\.\s+(.+)$', r'<span style="display:block;padding-left:12px;">\1. \2</span>', text, flags=re.MULTILINE)
    # Line breaks (after all other conversions)
    text = text.replace('\n', '<br>')
    return text


# ============================================================================
# Language Configuration (minimal - only styling)
# ============================================================================

LANGUAGE_CONFIG = {
    'zh-CN': {
        'font_family': "'Microsoft YaHei', 'PingFang SC', sans-serif",
        'color_up': '#e74c3c',      # Red for up (中国惯例：红涨)
        'color_down': '#27ae60',    # Green for down (中国惯例：绿跌)
    },
    'ko-KR': {
        'font_family': "'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif",
        'color_up': '#e74c3c',      # Red for up
        'color_down': '#2980b9',    # Blue for down
    }
}


# ============================================================================
# Configuration Loading
# ============================================================================

def load_template(name: str = "email_base.html") -> str:
    """Load HTML template by name from templates/ (default: macro email base)."""
    skill_dir = Path(__file__).parent.parent
    template_path = skill_dir / 'templates' / name
    with open(template_path, 'r', encoding='utf-8') as f:
        return f.read()


def get_config(language):
    """Get language configuration (colors, fonts)"""
    return LANGUAGE_CONFIG.get(language, LANGUAGE_CONFIG['zh-CN'])


# ============================================================================
# HTML Translation
# ============================================================================

def translate_html(html_content, target_language, max_retries=2):
    """
    Translate HTML content to target language using Claude API.

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

    # Strip base64 images to reduce payload (save ~40K per chart)
    import re
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
            # Use streaming to avoid timeout on large HTML
            with client.messages.stream(
                model=model,
                max_tokens=32000,
                messages=[{"role": "user", "content": prompt}]
            ) as stream:
                translated = ""
                for text in stream.text_stream:
                    translated += text
            # Remove markdown code block wrapper (Claude sometimes returns ```html ... ```)
            translated = re.sub(r'^\s*```(?:html)?\s*\n?', '', translated)
            translated = re.sub(r'\n?\s*```\s*$', '', translated)
            translated = translated.strip()

            # Restore base64 chart images
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
        # Clickable title
        title = item.get('title', '')
        url = item.get('url', '')
        if url:
            title_html = f'<a href="{url}" target="_blank" style="color:#2980b9; text-decoration:underline; font-weight:600;">{title}</a>'
        else:
            title_html = f'<span style="font-weight:600; color:#2c3e50;">{title}</span>'

        # Summary: truncate + convert Markdown to inline HTML
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

def render_template(template, data, language):
    """Render template with data.

    All content in Chinese - translated later via translate_html().
    """
    html = template
    config = get_config(language)

    # Apply font and color configuration
    html = html.replace('{{font_family}}', config['font_family'])
    html = html.replace('{{color_up}}', config['color_up'])
    html = html.replace('{{color_down}}', config['color_down'])

    # Basic info
    html = html.replace('{{title}}', '🗓️ 宏观经济日报')
    html = html.replace('{{date}}', datetime.now().strftime('%Y年%m月%d日'))
    html = html.replace('{{data_time_label}}', '数据截止')
    html = html.replace('{{data_time}}', data.get('data_time', datetime.now().strftime('%H:%M:%S')))

    # Global section labels
    html = html.replace('{{global_news_title}}', '📰 重要新闻')

    # Macro summary (① 核心观点) and risk outlook (⑥ 风险提示)
    html = html.replace('{{macro_summary}}', data.get('macro_summary') or '<p>暂无研判。</p>')
    html = html.replace('{{risk_outlook}}', data.get('risk_outlook') or '<p>—</p>')

    # Market sections - pre-rendered HTML passed in by the caller
    market_html = data.get('market_section_html', '')
    html = html.replace('{{market_sections}}', market_html)

    # Research views (sell-side) - pre-rendered section HTML, or empty
    html = html.replace('{{research_views}}', data.get('research_views') or '')

    # News - hard cap at 5 items
    news = data.get('news', data.get('global_news', []))
    news_count = 5
    html = html.replace('{{global_news}}', build_news_html(news[:news_count]))

    # Footer
    html = html.replace('{{disclaimer}}', '⚠️ 免责声明：本报告仅供参考，不构成投资建议。投资有风险，入市需谨慎。')
    html = html.replace('{{generated_by}}', '由 Claude Code 自动生成')
    html = html.replace('{{generated_at}}', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

    return html


def render_holdings_template(template: str, data: dict, language: str) -> str:
    """Render the per-recipient holdings-analysis email template.

    Mirrors render_template but for the holdings email: replaces
    {{title}}/{{date}}/{{holdings_summary}}/{{holdings_sections}} etc.
    Pre-rendered HTML (summary + section cards) is supplied by the caller.
    """
    html = template
    config = get_config(language)
    html = html.replace('{{font_family}}', config['font_family'])
    html = html.replace('{{color_up}}', config['color_up'])
    html = html.replace('{{color_down}}', config['color_down'])

    html = html.replace('{{title}}', '📊 持仓分析')
    html = html.replace('{{date}}', datetime.now().strftime('%Y年%m月%d日'))
    html = html.replace('{{data_time_label}}', '数据截止')
    html = html.replace('{{data_time}}', data.get('data_time', datetime.now().strftime('%H:%M:%S')))

    html = html.replace('{{holdings_summary}}', data.get('holdings_summary') or '<p>暂无组合研判。</p>')
    html = html.replace('{{holdings_sections}}', data.get('holdings_sections') or '')

    html = html.replace('{{disclaimer}}', '⚠️ 免责声明：本报告仅供参考，不构成投资建议。数据来自公开渠道，可能存在延迟或误差。')
    html = html.replace('{{generated_by}}', '由 Claude Code 自动生成')
    html = html.replace('{{generated_at}}', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    return html
