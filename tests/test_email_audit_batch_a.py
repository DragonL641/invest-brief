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


# ---- #3 USDCNY 大类资产卡与外围卡统一实时口径 ----

def test_usdcny_point_uses_realtime(monkeypatch):
    """大类资产卡 USDCNY 用实时值(与外围卡一致),非 DB 落库快照。"""
    import pandas as pd
    from investbrief.market.cn import provider as prov

    fake_ak = MagicMock()
    fake_ak.get_fx_usdcny_realtime.return_value = 6.7989
    monkeypatch.setattr(prov, "AKShareClient", lambda: fake_ak)
    monkeypatch.setattr(prov.CNMarketProvider, "get_indices", lambda self: [])

    class FakeData:
        def query(self, *a, **k):
            return pd.DataFrame([
                {"date": "2026-07-10", "value": 6.77},
                {"date": "2026-07-09", "value": 6.78},
            ])

    p = prov.CNMarketProvider(data=FakeData())
    assets = p.get_asset_performance()
    fx = [a for a in assets if "USDCNY" in a["name"]][0]
    assert fx["point"] == 6.7989  # 实时,非 DB 的 6.77


# ---- #4 ROE 低百分数值不再被放大 ----

def test_roe_low_pct_not_amplified():
    """ROE 原值 1.26(=1.26%)归一为 0.0126,_pct 渲染为 +1.3% 而非 +126.0%。"""
    from investbrief.picks.data import _normalize_cn_fund
    from investbrief.picks.renderer import _pct

    out = _normalize_cn_fund({"roe": 1.26})
    assert out["roe"] == 0.0126
    assert _pct(out["roe"]) == "+1.3%"
    # 正常值(>1.5)行为不变
    assert _normalize_cn_fund({"roe": 6.2})["roe"] == 0.062


# ---- #5 简报 prompt 不再硬编码数量 ----

def test_picks_prompt_no_hardcoded_count():
    """prompt 不含「6 只」「每个市场」,数量以注入的标的列表为准。"""
    from investbrief.picks.brief import PICKS_BRIEF_PROMPT
    assert "6 只" not in PICKS_BRIEF_PROMPT
    assert "每个市场" not in PICKS_BRIEF_PROMPT


# ---- #9 主力资金取数失败时隐藏因子行 ----

def test_main_flow_none_returns_none():
    """raw=None → 隐藏该因子(返回 None),不再显示「—%」。"""
    from investbrief.picks.renderer import _explain_factor
    assert _explain_factor("main_flow", {"raw": None}, {}) is None


def test_main_flow_with_value():
    from investbrief.picks.renderer import _explain_factor
    s = _explain_factor("main_flow", {"raw": 1.5}, {})
    assert s is not None and "1.50" in s


# ---- #11 标题恰好一个 🎯 ----

def test_picks_title_has_one_emoji():
    """render 给 title 自带一个 🎯,模板不再叠加。"""
    from investbrief.mail.render import render_picks_template
    html = render_picks_template(
        "email_picks.j2",
        {"data_time": "2026-07-11 18:00", "picks_brief": "<p>x</p>", "picks_sections": ""},
        "zh-CN",
    )
    assert html.count("🎯") == 1


# ---- #13 标普点数用默认深色,不随涨跌染色 ----

def test_sp500_point_neutral_color():
    """标普点数 cell 不含涨跌色;涨跌色只给独立的「标普涨跌」格。"""
    from investbrief.market.overseas import render_overseas_card
    html = render_overseas_card({"sp500": {"point": 7575.39, "change": 0.42}})
    # change>0 → sp_color=#e74c3c(红);点数区(标普500 到 标普涨跌 之间)不应被染红
    point_block = html.split("标普500")[1].split("标普涨跌")[0]
    assert "#e74c3c" not in point_block
