# tests/test_picks_renderer.py
"""picks.renderer: 卡片/段落 HTML。"""
from investbrief.picks import renderer


def _pick(symbol="000001", composite=85.0):
    return {
        "symbol": symbol, "name": "测试股", "market": "cn", "profile": "swing",
        "composite": composite, "rank": 1,
        "factor_scores": {"trend_strength": {"raw": 0.12, "pct": 90.0, "weighted": 27.0}},
        "triggers": ["trend_strength 处于池内前 10%"],
        "price": 10.5, "key_mas": {"ma20": 10.0, "ma60": 9.5, "ma120": 9.0},
        "stop_level": 9.2, "industry": "银行", "data_time": "2026-07-06 18:00",
    }


def test_render_pick_card_contains_symbol_and_composite():
    html = renderer.render_pick_card(_pick())
    assert "000001" in html
    assert "85.0" in html or "85" in html
    assert "趋势强度" in html          # 中文因子名
    assert "现价" in html and "10.50" in html   # 现价块 + 值


def test_render_pick_card_handles_none_pick():
    """无候选(pick=None)→ 占位卡片。"""
    html = renderer.render_pick_card(None, profile="swing", market="cn")
    assert "无符合条件" in html or "暂无" in html


def test_render_pick_section_wraps_card():
    section = renderer.render_pick_section("swing", _pick("000001"))
    assert "000001" in section
    assert "波段" in section            # 段落标题


# ---------- Task2: 标题加价位行 + 综合分弱化 + 删 _price_dim ----------
def _sample_pick():
    return {
        "symbol": "000001", "name": "平安银行", "market": "cn",
        "composite": 72.3, "price": 7.59,
        "key_levels": {"resistance": 8.50, "support": 6.80},
        "stop_level": 6.20,
        "fundamentals": {"pe": 15.5, "pb": 2.3, "roe": 0.12},
        "technicals": {"ma20": 7.3, "ma60": 7.2, "rsi": 58},
        "factor_scores": {},
    }


def test_card_head_has_price_levels_row():
    """标题区含现价/压力/支撑/止损价位行。"""
    html = renderer.render_pick_card(_sample_pick(), "swing", "cn")
    assert "7.59" in html
    assert "8.50" in html or "8.5" in html    # 压力位
    assert "6.80" in html or "6.8" in html    # 支撑位
    assert "6.20" in html or "6.2" in html    # 止损
    assert "price-row" in html   # 值在 price-row 容器内，不是散落到 dims


def test_composite_score_deemphasized():
    """综合分弱化(card-score class:小号灰色,不再是显眼大号彩色)。"""
    html = renderer.render_pick_card(_sample_pick(), "swing", "cn")
    assert "72.3" in html or "72" in html     # 综合分仍显示
    assert 'class="score-num"' not in html         # 旧显眼 class 没了
    assert 'class="card-score"' in html            # 新弱化 class(色/字号在 styles.css)


def test_no_standalone_price_dim():
    """card-body 不再有独立的'价位'维度(已移标题)。"""
    html = renderer.render_pick_card(_sample_pick(), "swing", "cn")
    assert html.count("现价") == 1   # 只在标题出现一次,不在 dims


# ---------- Task3: 量化因子一行一个 + 右解释 ----------
def test_factor_dim_one_line_per_factor_with_explain():
    """量化因子:每个因子独立行 + 右边解释(实际指标值,非百分比)。"""
    pick = _sample_pick()
    pick["factor_scores"] = {
        "trend_strength": {"raw": None, "pct": 89.0, "weighted": 22.5},
        "low_volatility_20d": {"raw": 0.0234, "pct": 75.0, "weighted": 7.5},
    }
    pick["technicals"] = {"ma_alignment": "bullish", "ma60": 7.2, "close_vs_ma60_pct": 0.054}
    pick["price"] = 7.59
    html = renderer._factor_dim(pick)
    assert "趋势强度" in html
    assert "低波动" in html
    # 解释含实际值(波动率 0.0234 / 多头排列)
    assert "0.0234" in html or "多头排列" in html
    # 不再显示百分比进度条
    assert "fbar-track" not in html
    assert "89%" not in html and "75%" not in html


# ---------- Task4: 技术面按类别分行(均线/动能/涨跌) ----------
def test_technicals_dim_grouped_by_category():
    """技术面按类别分3行:均线/动能/涨跌。return_*d 是百分数值(生产惯例,core/ta.py:104 *100)。"""
    pick = _sample_pick()
    pick["technicals"] = {
        "ma20": 7.3, "ma60": 7.2, "ma120": 7.0, "ma_alignment": "bullish",
        "close_vs_ma60_pct": 0.054,
        "rsi": 58, "macd_cross": "golden", "macd_bar": 0.12,
        "return_5d": 2.1, "return_20d": 8.5, "return_60d": 15.2,  # 百分比值
    }
    html = renderer._technicals_dim(pick)
    # 3 类分行
    assert "均线" in html
    assert "动能" in html
    assert "涨跌" in html
    # 均线类:MA 值 + 多头排列 + 距MA60(decimal → +5.4%)
    assert "7.3" in html and "多头排列" in html
    assert "+5.4%" in html
    # 动能类:RSI + 金叉
    assert "58" in html and "金叉" in html
    # 涨跌类:百分比值 → /100 归一化后 +2.1% / +8.5% / +15.2%(不被放大成 +210%)
    assert "+2.1%" in html
    assert "+8.5%" in html
    assert "+15.2%" in html
    assert "+210%" not in html   # 防回归:不能把百分比当十进制


def test_technicals_dim_macd_bar_fallback():
    """macd_cross 缺失但有 macd_bar → 红柱/绿柱(保留信息,不退化为 —)。"""
    pick = _sample_pick()
    pick["technicals"] = {"rsi": 50, "macd_bar": 0.15}  # 无 macd_cross,bar>0
    html = renderer._technicals_dim(pick)
    assert "红柱" in html
    pick["technicals"] = {"rsi": 50, "macd_bar": -0.08}  # bar<0
    html = renderer._technicals_dim(pick)
    assert "绿柱" in html


def test_technicals_dim_skips_ma_row_when_no_ma_data():
    """均线行无 MA 数据(ma20/60/120 全空)→ 跳过均线行,仍有动能/涨跌。"""
    pick = _sample_pick()
    pick["technicals"] = {"rsi": 55, "return_5d": 1.2}
    html = renderer._technicals_dim(pick)
    assert "均线" not in html
    assert "动能" in html
    assert "涨跌" in html


# ---------- Task5: 机构态度丰富(评级分布详情 + 目标价区间) ----------
def test_rating_dim_rich_distribution_and_targets():
    """机构态度:评级分布详情(各家数+共识+总数) + 目标价详情(均值/最高/最低+空间)。
    upside_pct 是百分数值(21.2 = 21%),需 /100 归一化后 _ret(不放大成 2120%)。"""
    pick = _sample_pick()
    pick["rating"] = {
        "distribution": {"strong_buy": 12, "buy": 8, "hold": 3, "sell": 0, "strong_sell": 0},
        "total": 23,
        "price_target": {"current": 7.59, "mean": 9.20, "high": 10.5, "low": 8.0, "upside_pct": 21.2},
    }
    html = renderer._rating_dim(pick)
    # 评级分布详情
    assert "强烈买入" in html
    assert "12" in html              # strong_buy 数
    assert "共23家" in html or "23" in html  # 机构总数
    # 目标价详情
    assert "9.20" in html or "9.2" in html   # 均值
    assert "10.5" in html                     # 最高
    assert "8.0" in html or "8.00" in html    # 最低
    assert "+21" in html                      # 空间%(21.2 → +21%)
    # 防回归:不能把 upside_pct 百分数当小数放大成 +2120%
    assert "+2120%" not in html
    assert "+212%" not in html


def test_rating_dim_cn_distribution_merged():
    """CN schema(outperform/neutral/underperform)归并进 4 格,不丢失。
    holdings/analyzer.py:671-677 CN distribution 用 buy/outperform/neutral/underperform/sell;
    若不归并,outperform(15)会被静默丢弃,严重低估看多。"""
    pick = _sample_pick()
    pick["rating"] = {
        "distribution": {"buy": 5, "outperform": 15, "neutral": 3, "underperform": 1, "sell": 0},
        "total": 24,
    }
    html = renderer._rating_dim(pick)
    # outperform(15) 归并进"买入" → 买入=5+15=20
    assert "买入" in html and "20" in html
    # neutral(3) 归并进"持有" → 持有=3
    assert "持有" in html and "3" in html
    # underperform(1) 归并进"卖出" → 卖出=1
    assert "卖出" in html and "1" in html
    # 共识% = (buy5+outperform15)/24 = 83%
    assert "83" in html
