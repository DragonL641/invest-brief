"""邮件体检批次 B 回归测试(spec: 2026-07-11-email-audit-fixes-design, 批次 B)。"""
from datetime import datetime, timedelta


# ---- #7 持仓新闻三重过滤 ----

def test_news_filter_dedup_relevance():
    """去重(归一化标题前15字)+ 相关性(标题需含 symbol/name)。"""
    from investbrief.holdings.analyzer import _extract_news
    today = datetime.now().date()
    recent = (today - timedelta(days=2)).strftime("%Y-%m-%d")
    older = (today - timedelta(days=6)).strftime("%Y-%m-%d")
    items = [
        {"title": "科大讯飞在安徽成立爻方智能科技公司 注册资本3亿", "date": older},
        {"title": "科大讯飞在安徽成立爻方智能科技公司", "date": older},  # 去重(前15字同)
        {"title": "解密主力资金出逃股 连续5日净流出443股", "date": recent},  # 榜单,不含个股
        {"title": "科大讯飞发布星火大模型新品", "date": recent},  # 相关
    ]
    out = _extract_news(items, symbol="002230", name="科大讯飞", limit=5, max_days=7)
    titles = [x["title"] for x in out]
    assert len(titles) == 2  # 成立公司 + 新品
    assert "科大讯飞发布星火大模型新品" in titles
    assert all("主力资金出逃" not in t for t in titles)  # 榜单被相关性过滤


def test_news_filter_relaxes_when_all_stale():
    """全部超过 max_days 则放宽 window,避免空(韧性)。"""
    from investbrief.holdings.analyzer import _extract_news
    items = [
        {"title": "科大讯飞旧闻甲", "date": "2025-01-01"},
        {"title": "科大讯飞旧闻乙", "date": "2025-01-02"},
    ]
    out = _extract_news(items, symbol="002230", name="科大讯飞", max_days=7)
    assert len(out) == 2  # 全过期 → 放宽,仍返回


# ---- #6 极端指标标注风险子分单位 ----

def test_macro_context_marks_risk_subscore():
    """极端指标标注「风险子分 X/10」,不被 Claude 当成指标原值。"""
    from investbrief.market.macro_brief import serialize_macro_context, MACRO_BRIEF_PROMPT
    risk = {"gold": {"total_score": 62, "state": "狂热泡沫", "risk_level": "high",
                     "action": "大幅减仓",
                     "indicators": {"gold_to_gdp": {"name": "黄金GDP占比", "score": 9.8,
                                                    "value": 18.5, "percentile": 98}}}}
    ctx = serialize_macro_context({}, {}, [], risk_scores=risk)
    assert "风险子分9.8/10" in ctx        # 标注了子分单位
    assert "黄金GDP占比" in ctx
    assert "子分" in MACRO_BRIEF_PROMPT    # prompt 也说明口径


# ---- #12 风险卡精简技术注释 ----

def test_risk_card_drops_algo_description():
    """副行不再拼「算法 + description」,explain 人读提示保留。"""
    from investbrief.risk.render import render_risk_card
    score = {"total_score": 50, "state": "乐观扩张", "action": "逐步减仓", "market": "cn",
             "indicators": {"margin_level": {"name": "融资余额水平", "value": 14856.0,
                                              "score": 9.9, "percentile": 99}}}
    html = render_risk_card(score)
    assert "算法 " not in html  # description 不再进 HTML
    assert "融资余额水平" in html  # 指标名仍在
