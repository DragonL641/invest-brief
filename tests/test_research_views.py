"""investbrief/research/views 单测：标题归因、市场标签、去重、韧性。

mock _default_search（底层 Tavily 调用），保证无网络、确定性。
"""
from investbrief.research import views


# ---------------------------------------------------------------------------
# 纯函数
# ---------------------------------------------------------------------------

def test_tag_market_us_cn_kr():
    assert "us" in views._tag_market("s&p 500 target hiked".lower())
    assert "cn" in views._tag_market("A股 后市 看多".lower())
    assert "kr" in views._tag_market("kospi drops on chip worry".lower())
    assert views._tag_market("european stocks rally".lower()) == []  # 全球其他


def test_firms_in_title_single_and_multi():
    assert views._firms_in_title("goldman sachs cuts s&p 500 target".lower()) == ["Goldman Sachs"]
    assert set(views._firms_in_title("jpmorgan and morgan stanley on tech".lower())) == {"JPMorgan", "Morgan Stanley"}
    assert views._firms_in_title("markets wrap".lower()) == []


# ---------------------------------------------------------------------------
# fetch_research_views（mock _default_search）
# ---------------------------------------------------------------------------

def test_fetch_no_key_returns_empty(monkeypatch):
    monkeypatch.delenv("TAVILY_KEY", raising=False)
    assert views.fetch_research_views() == []


def test_fetch_drops_non_title_mentions(monkeypatch):
    # firm 只出现在正文、不在标题 -> 丢弃（标题归因）
    def fake_search(subject, *, api_key, session, **kw):
        return [
            {"title": "Goldman Sachs cuts S&P 500 target", "url": "u1",
             "content": "rally", "published_date": "Wed, 25 Jun 2026"},
            {"title": "Markets wrap", "url": "u2",
             "content": "Goldman Sachs noted the selloff", "published_date": "Thu, 26 Jun 2026"},
        ]
    monkeypatch.setattr(views, "_default_search", fake_search)
    monkeypatch.setenv("TAVILY_KEY", "k")
    items = views.fetch_research_views()
    assert len(items) == 1
    assert items[0]["firms"] == ["Goldman Sachs"]
    assert "us" in items[0]["markets"]
    assert items[0]["url"] == "u1"


def test_fetch_dedups_by_url(monkeypatch):
    # 13 家查询返回同一条 URL -> 只保留一条
    def fake_search(subject, *, api_key, session, **kw):
        return [{"title": "JPMorgan view on stocks", "url": "same-url",
                 "content": "s&p 500", "published_date": "Wed, 25 Jun 2026"}]
    monkeypatch.setattr(views, "_default_search", fake_search)
    monkeypatch.setenv("TAVILY_KEY", "k")
    items = views.fetch_research_views()
    assert len(items) == 1
    assert items[0]["firms"] == ["JPMorgan"]


def test_fetch_multi_firm_tagging(monkeypatch):
    def fake_search(subject, *, api_key, session, **kw):
        return [{"title": "JPMorgan and Morgan Stanley see tech upside",
                 "url": "u1", "content": "nasdaq", "published_date": "..."}]
    monkeypatch.setattr(views, "_default_search", fake_search)
    monkeypatch.setenv("TAVILY_KEY", "k")
    items = views.fetch_research_views()
    assert set(items[0]["firms"]) == {"JPMorgan", "Morgan Stanley"}


def test_fetch_one_firm_failure_is_resilient(monkeypatch):
    def fake_search(subject, *, api_key, session, **kw):
        if "Jefferies" in subject:
            raise RuntimeError("network down")
        return [{"title": "Morgan Stanley on tech", "url": "u1",
                 "content": "s&p 500", "published_date": "..."}]
    monkeypatch.setattr(views, "_default_search", fake_search)
    monkeypatch.setenv("TAVILY_KEY", "k")
    items = views.fetch_research_views()
    assert any(i["firms"] == ["Morgan Stanley"] for i in items)  # 其他机构仍可用
