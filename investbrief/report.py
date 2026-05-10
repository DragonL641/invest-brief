"""
Send daily investment report to multiple recipients with personalized content.

This script receives market data and news from Claude (via JSON input),
renders the unified template for each recipient based on their settings,
and sends via SMTP.

Features:
- Multi-language support (zh-CN, ko-KR)
- Per-recipient configuration (markets, holdings, news count)
- Dynamic country ordering
- Color-coded global metrics
- Technical analysis with support/resistance
- Personalized daily summary
- HTML translation via Claude API

Workflow:
    1. Generate JSON data in Chinese
    2. Render HTML template with Chinese content
    3. Translate entire HTML to target language (if not Chinese)
    4. Send via SMTP

Usage:
    python send_report.py --data-json '<json_string>'
    python send_report.py --data-file report_data.json
"""
import sys
import re
import json
import logging
import argparse
from datetime import datetime
from pathlib import Path

from investbrief.core.mailer import EmailSender

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
        'color_neutral': '#7f8c8d',
    },
    'ko-KR': {
        'font_family': "'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif",
        'color_up': '#e74c3c',      # Red for up
        'color_down': '#2980b9',    # Blue for down
        'color_neutral': '#7f8c8d',
    }
}


# ============================================================================
# Configuration Loading
# ============================================================================

def _resolve_config_path() -> Path:
    """Resolve config path from project root"""
    return Path(__file__).resolve().parent.parent / "config.json"


def load_config():
    """Load configuration from config.json"""
    config_path = _resolve_config_path()
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_template():
    """Load base HTML template"""
    skill_dir = Path(__file__).parent.parent
    template_path = skill_dir / 'templates' / 'email_base.html'
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

    import os
    client = anthropic.Anthropic(
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
        base_url=os.environ.get("ANTHROPIC_BASE_URL"),
    )

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
                model="claude-sonnet-4-6",
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

def build_metrics_html(metrics, config):
    """Build global metrics cards as table for Outlook compatibility"""
    cells = ''
    for m in metrics:
        change = m.get('change', 0)
        if change > 0:
            bg_color = config['color_up']
        elif change < 0:
            bg_color = config['color_down']
        else:
            bg_color = config['color_neutral']

        cells += f'''
        <td style="background-color:{bg_color}; color:#ffffff; padding:15px; text-align:center; width:25%; border-radius:8px;">
            <div style="font-size:22px; font-weight:bold;">{m['value']}</div>
            <div style="font-size:11px; margin-top:5px; opacity:0.9;">{m['label']}</div>
        </td>'''

    # Wrap in table with spacing between cells
    html = f'''
    <table width="100%" cellpadding="0" cellspacing="12" style="border-collapse:separate; border-spacing:12px;">
      <tr>{cells}
      </tr>
    </table>'''
    return html


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

def render_template(template, data, language, recipient_settings):
    """Render template with data and recipient-specific settings.

    All content in Chinese - translated later via translate_html().
    """
    html = template
    config = get_config(language)

    # Apply font and color configuration
    html = html.replace('{{font_family}}', config['font_family'])
    html = html.replace('{{color_up}}', config['color_up'])
    html = html.replace('{{color_down}}', config['color_down'])

    # Basic info
    market_titles = {"us": "美股日报", "cn": "A股日报"}
    market_label = market_titles.get(data.get("market", "us"), "投资日报")
    html = html.replace('{{title}}', f'\U0001F4C5 {market_label}')
    html = html.replace('{{date}}', datetime.now().strftime('%Y年%m月%d日'))
    html = html.replace('{{data_time_label}}', '数据截止')
    html = html.replace('{{data_time}}', data.get('data_time', datetime.now().strftime('%H:%M:%S')))

    # Global section labels
    html = html.replace('{{global_market_title}}', '🌍 全球市场概况')
    html = html.replace('{{global_news_title}}', '📰 重要新闻')

    # Global metrics
    html = html.replace('{{global_metrics}}', build_metrics_html(data.get('global_metrics', []), config))

    # Market sections - pre-rendered HTML passed in by the caller
    market_html = data.get('market_section_html', '')
    html = html.replace('{{market_sections}}', market_html)

    # News - limit by recipient's news_count
    news = data.get('news', data.get('global_news', []))
    news_count = 5  # Hard limit: always show 5 news items
    html = html.replace('{{global_news}}', build_news_html(news[:news_count]))

    # Footer
    html = html.replace('{{disclaimer}}', '⚠️ 免责声明：本报告仅供参考，不构成投资建议。投资有风险，入市需谨慎。')
    html = html.replace('{{generated_by}}', '由 Claude Code 自动生成')
    html = html.replace('{{generated_at}}', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

    return html


# ============================================================================
# Main Entry Point
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description='Send daily investment report')
    parser.add_argument('--data-json', type=str, help='Report data as JSON string')
    parser.add_argument('--data-file', type=str, help='Path to JSON file with report data')
    args = parser.parse_args()

    # Load data
    if args.data_file:
        with open(args.data_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    elif args.data_json:
        data = json.loads(args.data_json)
    else:
        print('ERROR: No data provided. Use --data-json or --data-file')
        sys.exit(1)

    # Load config
    config = load_config()
    skill_dir = Path(__file__).parent.parent

    # Get active recipients
    active_recipients = [r for r in config.get('recipients', []) if r.get('active', True)]

    if not active_recipients:
        print('ERROR: No active recipients found in config')
        sys.exit(1)

    # Load template once
    template = load_template()

    # Send to each recipient
    sender = EmailSender(str(_resolve_config_path()))

    for recipient in active_recipients:
        email = recipient['email']
        name = recipient.get('name', email)
        language = recipient.get('language', 'zh-CN')
        settings = recipient.get('settings', {})

        print(f'\n{"="*60}')
        print(f'Processing: {name} ({email}) - Language: {language}')
        holdings_count = len(settings.get('holdings', []))
        print(f'Holdings: {holdings_count} stocks')
        print(f'{"="*60}')

        # Render template with data and recipient settings (Chinese content)
        html = render_template(template, data, language, settings)

        # Translate HTML (news from API is English, need to translate to target language)
        print(f'Translating to {language}...')
        html = translate_html(html, language)

        # Generate subject from data (or use default Chinese subject)
        subject = data.get('subject', f'【美股日报】{datetime.now().strftime("%Y年%m月%d日")}')

        print(f'HTML size: {len(html)} characters')

        # Send email
        try:
            sender.send(email, subject, html)
            print(f'✅ Sent successfully to {email}')
        except Exception as e:
            print(f'❌ Failed to send to {email}: {e}')

    print(f'\n{"="*60}')
    print('Report sending complete!')
    print(f'{"="*60}')


if __name__ == '__main__':
    main()
