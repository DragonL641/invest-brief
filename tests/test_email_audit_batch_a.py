"""邮件体检批次 A 回归测试(spec: 2026-07-11-email-audit-fixes-design)。"""
from unittest.mock import MagicMock


# ---- #1 宏观新闻接 Tavily 源 ----

def test_cn_macro_news_maps_tavily_results(monkeypatch):
    from investbrief.market.cn import news as cn_news

    fake = [{
        "title": "央行宣布降准",
        "url": "https://www.reuters.com/article/cn-rate",
        "content": "降准细节 " * 60,
        "score": 0.9,
        "published_date": "2026-07-11T08:00:00Z",
    }]
    client = MagicMock()
    client.enabled = True
    client.search_news.return_value = fake
    monkeypatch.setattr(cn_news, "TavilyClient", lambda: client)

    items = cn_news.fetch_cn_macro_news(limit=5)
    assert len(items) == 1
    assert items[0]["title"] == "央行宣布降准"
    assert items[0]["url"] == "https://www.reuters.com/article/cn-rate"
    assert items[0]["time"] == "2026-07-11"
    assert items[0]["source"] == "reuters.com"
    assert items[0]["summary"]  # content 截断后非空


def test_cn_macro_news_disabled_returns_empty(monkeypatch):
    from investbrief.market.cn import news as cn_news

    client = MagicMock()
    client.enabled = False
    monkeypatch.setattr(cn_news, "TavilyClient", lambda: client)
    assert cn_news.fetch_cn_macro_news(limit=5) == []
