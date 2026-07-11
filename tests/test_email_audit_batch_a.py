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


# ---- #2 止损价恒低于现价 ----

def test_stop_level_below_price_in_downtrend():
    """下跌趋势(MA60>现价,云铝场景)止损仍低于现价。"""
    from investbrief.pipelines.picks import _compute_stop_level
    stop = _compute_stop_level(
        23.15, ma20=23.70, ma60=28.44,
        risk={"stop_break_ma60": True, "stop_max_dd": 0.07})
    assert stop < 23.15
    assert stop == round(min(28.44, 23.15 * 0.93), 2)  # 21.53


def test_stop_level_uses_ma_when_uptrend():
    """上涨趋势(MA<现价)用趋势线下拽两者较小者。"""
    from investbrief.pipelines.picks import _compute_stop_level
    stop = _compute_stop_level(
        7.59, ma20=7.42, ma60=5.63,
        risk={"stop_break_ma20": True, "stop_max_dd": 0.05})
    assert stop < 7.59
    assert stop == round(min(7.42, 7.59 * 0.95), 2)  # 7.21
