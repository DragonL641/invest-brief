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
