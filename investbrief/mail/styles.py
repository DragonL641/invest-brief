"""邮件编辑研报风设计系统（单一真相源）。

三套 .j2 模板经 ``{{base_css}}`` 注入 BASE_CSS；所有 Python renderer 生成的
内联 HTML 片段统一用此处定义的语义 class。改色/字号/间距 → 只改本文件常量。

邮件兼容性约束（与 Web 不同）：
- **不用 CSS 变量** ``var()`` —— Gmail/Outlook/Yahoo 均不支持，颜色由
  ``string.Template`` 在 Python 侧注入为字面量。
- **不依赖 box-shadow / 外部字体** —— Outlook 桌面(Word 引擎)会丢弃阴影，
  外部 web font 在多数客户端不加载；衬线靠系统栈 ``Georgia``(全平台兜底) +
  中文宋体回退。
- **不用 ``gap``** —— 部分客户端忽略，间距走 margin。
- **去 hover** —— 邮件无交互。
"""

from string import Template

# ── 配色 ────────────────────────────────────────────────────────────────────
INK = "#1a1f2e"        # 深墨：正文 / 标题主色
INK_2 = "#5a6573"      # 次级文字
INK_3 = "#8b95a3"      # 辅助 / 标签
ACCENT = "#b8232e"     # 编辑红：kicker / 报头底线 / 强调
UP = "#c0392b"         # 涨（红，中国惯例）
DOWN = "#2d8659"       # 跌（绿，降饱和）
PAPER = "#f4f3ef"      # 画布米白（纸感）
CARD = "#ffffff"       # 卡片白
TINT = "#faf9f6"       # 分组浅底
RULE = "#e6e3dc"       # 分隔细线（暖灰）
RULE_SOFT = "#efece5"  # 更柔的次级分隔
ON_DARK_FAINT = "rgba(255,255,255,0.62)"  # 深底次级文字

# ── 字体栈 ──────────────────────────────────────────────────────────────────
# 衬线：标题 / 大号数字。Georgia 全平台兜底，中文走宋体。
SERIF = "Georgia, 'Songti SC', 'STSong', 'SimSun', 'Noto Serif SC', serif"
# 无衬线：正文 / 标签。PingFang(Mac/iOS) 优先，YaHei(Win) 回退。
SANS = "'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Helvetica Neue', Arial, sans-serif"

# ── 对外常量（render.py LANGUAGE_CONFIG / render_config 引用） ───────────────
COLOR_UP = UP
COLOR_DOWN = DOWN
FONT_FAMILY = SANS

# ── BASE_CSS ────────────────────────────────────────────────────────────────
_CSS = """
* { box-sizing: border-box; }
body { background: ${PAPER}; font-family: ${SANS}; color: ${INK}; margin: 0; padding: 26px; -webkit-font-smoothing: antialiased; }
img { max-width: 100%; }
a { color: ${ACCENT}; }

/* ── 容器 ── */
.container { max-width: 680px; margin: 0 auto; background: ${CARD}; border: 1px solid ${RULE}; border-radius: 4px; overflow: hidden; }

/* ── 报头 masthead ── */
.masthead { background: ${INK}; color: #fff; padding: 30px 30px 24px; border-bottom: 3px solid ${ACCENT}; }
.masthead-brand { font-family: ${SANS}; font-size: 10px; letter-spacing: 3px; color: #fff; font-weight: 700; margin-bottom: 12px; opacity: 0.55; }
.masthead-title { font-family: ${SERIF}; font-size: 29px; font-weight: 700; margin: 0 0 7px; color: #fff; letter-spacing: -0.01em; line-height: 1.2; }
.masthead-date { font-family: ${SANS}; font-size: 12px; color: ${ON_DARK_FAINT}; letter-spacing: 0.3px; }

/* ── 段落 section ── */
.section { padding: 28px 30px; border-bottom: 1px solid ${RULE}; }
.section:last-child { border-bottom: none; }
.section-head { padding-bottom: 14px; margin-bottom: 18px; border-bottom: 1px solid ${RULE}; }
.kicker { display: block; font-family: ${SANS}; font-size: 10px; letter-spacing: 2.5px; color: ${ACCENT}; font-weight: 700; margin-bottom: 6px; }
.section-title { font-family: ${SERIF}; font-size: 22px; font-weight: 700; color: ${INK}; margin: 0; letter-spacing: -0.005em; line-height: 1.25; }

/* ── 卡片 card ── */
.card { background: ${CARD}; border: 1px solid ${RULE}; border-radius: 3px; margin: 14px 0; }
.card-head { padding: 11px 16px; border-bottom: 1px solid ${RULE}; font-family: ${SANS}; font-size: 11px; font-weight: 700; color: ${INK}; letter-spacing: 1px; text-transform: uppercase; }
.card-body { padding: 16px; }
.card-body p { margin: 0 0 8px; } .card-body p:last-child { margin: 0; }

/* ── 数据网格 stat-grid（大类资产 / 外围） ── */
.stat-grid { display: flex; flex-wrap: wrap; }
.stat { flex: 1 1 30%; min-width: 0; background: ${TINT}; border: 1px solid ${RULE_SOFT}; border-radius: 3px; padding: 14px 10px; text-align: center; margin: 4px; }
.stat-label { font-family: ${SANS}; font-size: 11px; color: ${INK_3}; letter-spacing: 0.3px; margin-bottom: 7px; }
.stat-value { font-family: ${SERIF}; font-size: 21px; font-weight: 700; color: ${INK}; line-height: 1; font-variant-numeric: tabular-nums; }
.stat-delta { font-family: ${SANS}; font-size: 12px; font-weight: 700; margin-top: 6px; font-variant-numeric: tabular-nums; }
.stat-sub { font-family: ${SANS}; font-size: 10px; color: ${INK_3}; margin-top: 6px; }

/* ── 涨跌色 ── */
.pos, .stock-up { color: ${UP}; font-weight: 700; }
.neg, .stock-down { color: ${DOWN}; font-weight: 700; }
.neutral, .stock-neutral { color: ${INK_3}; }

/* ── 指标行 metrics-row（货币政策等） ── */
.metrics-row { display: flex; flex-wrap: wrap; font-family: ${SANS}; font-size: 13px; color: ${INK_2}; }
.metric { background: ${CARD}; border: 1px solid ${RULE_SOFT}; padding: 5px 10px; border-radius: 3px; margin: 0 6px 6px 0; }
.metric .label { color: ${INK_3}; font-size: 11px; margin-right: 4px; }

/* ── 摘要框 summary-box（核心观点 / 风险 / 卖方） ── */
.summary-box { background: ${TINT}; border-top: 2px solid ${INK}; padding: 18px 20px; font-family: ${SANS}; font-size: 14.5px; line-height: 1.8; color: ${INK}; }
.summary-box p { margin: 0 0 10px; } .summary-box p:last-child { margin: 0; }
.summary-box strong { color: ${INK}; font-weight: 700; }
.summary-box ul, .summary-box ol { margin: 8px 0; padding-left: 20px; } .summary-box li { margin-bottom: 5px; }

/* ── 表格 table（经济日历 / 评级） ── */
table { width: 100%; border-collapse: collapse; font-family: ${SANS}; font-size: 13px; }
th { text-align: left; font-size: 10px; letter-spacing: 1px; text-transform: uppercase; color: ${INK_3}; font-weight: 700; padding: 8px 10px; border-bottom: 1px solid ${RULE}; }
td { padding: 10px; border-bottom: 1px solid ${RULE_SOFT}; color: ${INK}; vertical-align: middle; }
tr:last-child td { border-bottom: none; }

/* ── 徽标 badge（经济日历倒计时） ── */
.badge { display: inline-block; font-family: ${SANS}; font-size: 10px; font-weight: 700; color: #fff; padding: 2px 8px; border-radius: 2px; letter-spacing: 0.3px; }
.badge-high { background: ${ACCENT}; }
.badge-med { background: ${INK_3}; }

/* ── 信号 tag（holdings / picks 共用，前缀统一 signal-tag-） ── */
.signal-tag { display: inline-block; font-family: ${SANS}; padding: 2px 9px; border-radius: 2px; font-size: 11px; font-weight: 700; margin: 0 5px 4px 0; letter-spacing: 0.2px; }
.signal-tag-up { background: ${TINT}; color: ${UP}; border: 1px solid #f0d6d2; }
.signal-tag-down { background: ${TINT}; color: ${DOWN}; border: 1px solid #cce4d8; }
.signal-tag-warn { background: ${TINT}; color: #b07a14; border: 1px solid #ecdfc0; }
.signal-tag-neutral { background: ${TINT}; color: ${INK_3}; border: 1px solid ${RULE}; }

/* ── 维度行 dim-row（holdings / picks 共用，结构对齐） ── */
.dim-row { display: table; width: 100%; padding: 6px 0; border-bottom: 1px solid ${RULE_SOFT}; font-family: ${SANS}; font-size: 13px; }
.dim-row:last-child { border-bottom: none; }
.dim-name { display: table-cell; width: 84px; color: ${INK_3}; font-size: 11px; font-weight: 600; vertical-align: top; letter-spacing: 0.2px; }
.dim-cells { display: table-cell; vertical-align: top; color: ${INK_2}; }
.cell { display: inline-block; margin: 0 14px 4px 0; }
.cell .cl { color: ${INK_3}; font-size: 10px; margin-right: 3px; }

/* ── CSS bar（评级分布） ── */
.bar-track { display: inline-block; height: 5px; width: 56px; background: ${RULE}; border-radius: 3px; vertical-align: middle; margin-left: 4px; overflow: hidden; }
.bar-fill { display: block; height: 5px; border-radius: 3px; background: ${INK_3}; }

/* ── AI 研判框 ── */
.ai-box { margin-top: 12px; padding: 13px 15px; background: ${TINT}; border-top: 2px solid ${INK}; border-radius: 2px; font-family: ${SANS}; font-size: 13px; line-height: 1.65; color: ${INK}; }
.ai-box .ai-label { font-size: 10px; letter-spacing: 2px; color: ${ACCENT}; font-weight: 700; display: block; margin-bottom: 6px; }

/* ── 买入逻辑框（picks） ── */
.logic-box { margin-top: 10px; padding: 11px 13px; background: ${TINT}; border: 1px solid ${RULE}; border-radius: 2px; font-family: ${SANS}; font-size: 12.5px; line-height: 1.6; color: ${INK_2}; }
.logic-box b, .logic-box strong { color: ${INK}; }
.logic-box ul { margin: 5px 0 0; padding-left: 16px; } .logic-box li { margin-bottom: 3px; }

/* ── 新闻 news ── */
.news-item { padding: 13px 0; border-bottom: 1px solid ${RULE_SOFT}; }
.news-item:last-child { border-bottom: none; }
.news-title { font-family: ${SANS}; font-size: 14px; font-weight: 700; color: ${INK}; margin-bottom: 5px; line-height: 1.45; }
.news-title a { color: ${INK}; text-decoration: none; border-bottom: 1px solid ${RULE}; }
.news-summary { font-family: ${SANS}; font-size: 13px; color: ${INK_2}; line-height: 1.65; }
.news-meta { font-family: ${SANS}; font-size: 11px; color: ${INK_3}; margin-top: 5px; letter-spacing: 0.2px; }
.news-tag { display: inline-block; font-family: ${SANS}; font-size: 10px; color: ${INK_3}; background: ${TINT}; border: 1px solid ${RULE}; padding: 1px 7px; border-radius: 2px; margin-left: 8px; letter-spacing: 0.3px; }

/* ── 无数据 ── */
.no-data { text-align: center; color: ${INK_3}; padding: 24px; font-family: ${SANS}; font-size: 13px; }

/* ── 页脚 footer ── */
.footer { padding: 20px 30px; text-align: center; color: ${INK_3}; font-family: ${SANS}; font-size: 11px; line-height: 1.8; background: ${TINT}; border-top: 1px solid ${RULE}; }

/* ── 周期风险卡 risk（嵌入各 section 底部） ── */
.risk-wrap { margin-top: 14px; padding: 16px 18px; background: ${TINT}; border: 1px solid ${RULE}; border-radius: 3px; }
.risk-label { font-family: ${SANS}; font-size: 10px; letter-spacing: 2px; color: ${INK_3}; font-weight: 700; margin-bottom: 10px; }
.risk-score-row { margin-bottom: 10px; }
.risk-score { font-family: ${SERIF}; font-size: 30px; font-weight: 700; line-height: 1; vertical-align: middle; font-variant-numeric: tabular-nums; }
.risk-score-out { font-family: ${SANS}; font-size: 12px; color: ${INK_3}; margin-left: 2px; vertical-align: middle; }
.risk-state { font-family: ${SANS}; font-size: 12.5px; color: ${INK_2}; margin-bottom: 12px; }
.risk-state b { font-weight: 700; }
.ind { margin-bottom: 10px; }
.ind-line { font-family: ${SANS}; font-size: 12px; color: ${INK_2}; line-height: 1.5; }
.ind-name { display: inline-block; width: 92px; vertical-align: top; color: ${INK}; font-weight: 600; }
.ind-val { display: inline-block; width: 78px; vertical-align: top; color: ${INK_2}; }
.ind-explain { font-family: ${SANS}; font-size: 11px; color: ${INK_3}; padding-left: 4px; margin-top: 2px; line-height: 1.5; }

/* ── 宏观四象限 regime ── */
.regime-wrap { margin-top: 14px; padding: 16px 18px; background: ${TINT}; border: 1px solid ${RULE}; border-radius: 3px; }
.regime-label { font-family: ${SANS}; font-size: 10px; letter-spacing: 2px; color: ${INK_3}; font-weight: 700; margin-bottom: 10px; }
.regime-table { width: 100%; border-collapse: separate; border-spacing: 6px; }
.regime-axis { font-family: ${SANS}; font-size: 10px; color: ${INK_3}; letter-spacing: 0.5px; vertical-align: middle; }
.regime-col-head { font-family: ${SANS}; font-size: 10px; color: ${INK_3}; text-align: center; letter-spacing: 0.5px; }
.regime-cell { background: ${CARD}; border: 1px solid ${RULE}; padding: 11px 8px; text-align: center; border-radius: 2px; vertical-align: middle; }
.regime-cell-current { background: ${CARD}; border: 1.5px solid ${ACCENT}; }
.regime-name { font-family: ${SERIF}; font-size: 15px; font-weight: 700; color: ${INK}; }
.regime-star { color: ${ACCENT}; font-size: 11px; margin-left: 2px; }
.regime-favors { font-family: ${SANS}; font-size: 10px; color: ${INK_3}; margin-top: 3px; }
.regime-basis { font-family: ${SANS}; font-size: 12px; color: ${INK_2}; line-height: 1.6; margin-top: 10px; }
.regime-basis b { color: ${INK}; }

/* ── holdings 专用 ── */
.group-title { font-family: ${SANS}; font-size: 11px; color: ${INK_3}; font-weight: 700; letter-spacing: 1.5px; text-transform: uppercase; margin: 18px 0 10px; padding-bottom: 6px; border-bottom: 1px solid ${RULE}; }
.group-title:first-child { margin-top: 0; }
.card-name { font-size: 15px; font-weight: 700; color: ${INK}; }
.card-meta { float: right; font-size: 12px; color: ${INK_3}; font-weight: 400; }
.card-meta strong { color: ${INK}; font-weight: 700; }
.card-sym { color: ${INK_3}; font-size: 12px; margin-left: 5px; font-weight: 400; }
.signal-row { margin-bottom: 10px; overflow: hidden; }
.dims { font-family: ${SANS}; font-size: 13px; }
.news-date { color: ${INK_3}; font-size: 11px; margin-left: 4px; }

/* ── picks 专用 ── */
.brief-box { background: ${TINT}; border-top: 2px solid ${INK}; border-radius: 2px; padding: 15px 17px; font-family: ${SANS}; font-size: 13.5px; line-height: 1.75; color: ${INK}; }
.brief-box p { margin: 0 0 8px; } .brief-box p:last-child { margin: 0; }
.brief-box strong { color: ${INK}; }
.mkt-badge { display: inline-block; font-family: ${SANS}; font-size: 9px; font-weight: 700; color: ${ACCENT}; border: 1px solid ${ACCENT}; padding: 1px 6px; border-radius: 2px; margin-left: 6px; vertical-align: middle; letter-spacing: 0.5px; }
.profile-title { font-family: ${SERIF}; font-size: 16px; font-weight: 700; color: ${INK}; margin: 24px 0 10px; padding-bottom: 8px; border-bottom: 1px solid ${RULE}; }
.profile-title:first-child { margin-top: 0; }
.profile-kicker { display: block; font-family: ${SANS}; font-size: 10px; letter-spacing: 2px; color: ${ACCENT}; font-weight: 700; margin-bottom: 4px; }
.notice { padding: 12px 20px; background: ${TINT}; border-bottom: 1px solid ${RULE}; font-family: ${SANS}; font-size: 11.5px; line-height: 1.65; color: ${INK_2}; }
.notice b { color: ${INK}; font-weight: 700; }
.price-row { display: flex; flex-wrap: wrap; padding: 10px 16px; background: ${TINT}; border-top: 1px solid ${RULE_SOFT}; border-bottom: 1px solid ${RULE_SOFT}; }
.price-row .pl { font-family: ${SANS}; font-size: 13px; margin-right: 18px; }
.price-row .pl-l { font-size: 10px; color: ${INK_3}; margin-right: 4px; letter-spacing: 0.2px; }
.factor-list { padding: 4px 0; margin: 2px 0; }
.factor-row { display: flex; gap: 8px; padding: 4px 0; align-items: baseline; border-bottom: 1px solid ${RULE_SOFT}; }
.factor-row:last-child { border-bottom: none; }
.fl-name { color: ${INK_3}; font-size: 12px; min-width: 76px; flex-shrink: 0; font-weight: 600; }
.fl-explain { font-size: 12px; color: ${INK_2}; line-height: 1.5; }
.card.empty { text-align: center; color: ${INK_3}; padding: 22px; font-size: 13px; background: ${TINT}; border: 1px dashed ${RULE}; }
.card-score { float: right; color: ${INK_3}; font-size: 11px; font-family: ${SANS}; letter-spacing: 0.3px; }
.card-score b { color: ${INK}; font-weight: 700; }

/* ── 响应式 ── */
@media (max-width: 600px) {
  body { padding: 12px; }
  .section { padding: 22px 18px; }
  .masthead { padding: 26px 20px 22px; }
  .masthead-title { font-size: 24px; }
  .section-title { font-size: 19px; }
  .stat { flex: 1 1 100%; }
  .dim-row { display: block; }
  .dim-name { display: block; width: auto; margin-bottom: 3px; }
  .dim-cells { display: block; }
  th, td { padding: 7px 8px; font-size: 12px; }
}
"""

# 自动收集本模块所有大写字符串常量作为 Template token
_TOKENS = {
    name: val for name, val in dict(globals()).items()
    if name.isupper() and isinstance(val, str)
}

BASE_CSS = Template(_CSS).substitute(_TOKENS)
