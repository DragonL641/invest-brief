"""brief prompt 包含新维度字段。"""
from investbrief.holdings.analyzer import HoldingResult
from unittest.mock import patch, MagicMock

from investbrief.holdings.brief import (
    _build_prompt, _format_holding, _fallback_stock_conclusion, generate_stock_conclusion,
)


def test_prompt_includes_insider():
    r = HoldingResult(symbol="002371", market="cn", type="stock", name="北方华创",
                      insider={"direction": "sell", "net_amount": -800000})
    prompt = _build_prompt([r])
    assert "高管" in prompt or "增减持" in prompt or "减持" in prompt


def test_prompt_includes_events():
    r = HoldingResult(symbol="AAPL", market="us", type="stock", name="Apple",
                      events={"next_earnings": "2026-08-01", "days_to_next": 20})
    prompt = _build_prompt([r])
    assert "财报" in prompt or "2026-08-01" in prompt


def test_prompt_includes_cn_activity():
    r = HoldingResult(symbol="002371", market="cn", type="stock", name="北方华创",
                      cn_activity={"dragon_tiger_count": 2, "institution_research_count": 3})
    prompt = _build_prompt([r])
    assert "龙虎榜" in prompt or "机构调研" in prompt


def test_prompt_includes_forecast():
    r = HoldingResult(symbol="AAPL", market="us", type="stock", name="Apple",
                      forecast={"eps_next": 2.1, "yoy_pct": 18.0})
    prompt = _build_prompt([r])
    assert "EPS" in prompt or "盈利" in prompt or "2.1" in prompt


def test_format_holding_includes_key_dimensions():
    r = HoldingResult(
        symbol="601138", market="cn", type="stock", name="工业富联",
        price={"current": 64.72, "change_pct": 1.09},
        rating={"distribution": {"buy": 5, "sell": 1}, "total": 6, "price_target": {"mean": 70, "upside_pct": 8.2}},
        fundamentals={"pe": 30.3, "roe": 18.5, "revenue_growth": 15.0},
        technicals={"ma_alignment": "bullish", "rsi": 55, "macd_cross": "golden", "return_60d": 12.3},
    )
    text = _format_holding(r)
    assert "601138" in text and "工业富联" in text
    assert "64.72" in text
    assert "buy" in text or "评级分布" in text
    assert "bullish" in text
    assert "30.3" in text
    assert "ai_conclusion" not in text


def test_format_holding_includes_extended_fundamentals():
    """C4: 基本面补 gross_margin / net_margin / debt_ratio(存在时输出)。"""
    r = HoldingResult(
        symbol="600519", market="cn", type="stock", name="贵州茅台",
        fundamentals={
            "pe": 30.0, "roe": 30.0, "revenue_growth": 15.0,
            "gross_margin": 91.0, "net_margin": 50.0, "debt_ratio": 25.0,
        },
        technicals={"ma_alignment": "bullish"},
    )
    text = _format_holding(r)
    assert "毛利率" in text and "91.0" in text
    assert "净利率" in text and "50.0" in text
    assert "负债率" in text and "25.0" in text


def test_format_holding_omits_missing_extended_fundamentals():
    """C4: gross_margin/net_margin/debt_ratio 缺失时不输出(优雅降级)。"""
    r = HoldingResult(
        symbol="AAPL", market="us", type="stock", name="Apple",
        fundamentals={"pe": 30.0, "roe": 100.0, "revenue_growth": 10.0},
        technicals={"ma_alignment": "bullish"},
    )
    text = _format_holding(r)
    assert "毛利率" not in text
    assert "净利率" not in text
    assert "负债率" not in text


def test_format_holding_includes_position_60d_and_return_10d():
    """C4: 技术面补 position_60d(60日区间位置) + return_10d 进 AI prompt 上下文。"""
    r = HoldingResult(
        symbol="601138", market="cn", type="stock", name="工业富联",
        technicals={
            "ma_alignment": "bullish", "rsi": 55, "macd_cross": "golden",
            "volume_ratio": 1.2, "return_5d": 3.0, "return_10d": 5.5,
            "return_20d": 8.0, "return_60d": 12.3, "position_60d": 0.85,
            "boll_position": 0.7, "new_high_60d": True,
        },
    )
    text = _format_holding(r)
    assert "区间位置" in text
    assert "0.85" in text
    assert "10日" in text and "5.5" in text


def test_fallback_bullish():
    r = HoldingResult(symbol="601138", market="cn", type="stock",
                      rating={"distribution": {"buy": 5, "outperform": 2, "sell": 1}},
                      technicals={"ma_alignment": "bullish"})
    assert "偏多" in _fallback_stock_conclusion(r)


def test_fallback_bearish():
    r = HoldingResult(symbol="AAPL", market="us", type="stock",
                      rating={"distribution": {"strong_sell": 3, "sell": 2, "buy": 1}},
                      technicals={"ma_alignment": "bearish"})
    assert "偏空" in _fallback_stock_conclusion(r)


def test_fallback_insufficient_data():
    r = HoldingResult(symbol="002335", market="cn", type="stock")
    assert "数据不足" in _fallback_stock_conclusion(r)


def _sample_holding():
    return HoldingResult(
        symbol="601138", market="cn", type="stock", name="工业富联",
        price={"current": 64.72, "change_pct": 1.09},
        rating={"distribution": {"buy": 5, "sell": 1}, "total": 6},
        technicals={"ma_alignment": "bullish"},
    )


@patch("investbrief.core.llm.get_client")
@patch("investbrief.core.llm.default_model", return_value="test-model")
def test_generate_stock_conclusion_success(mock_model, mock_get_client):
    mock_client = MagicMock()
    mock_client.messages.create.return_value.content = [MagicMock(text="偏多。均线多头，趋势向上，建议持有。")]
    mock_get_client.return_value = mock_client
    result = generate_stock_conclusion(_sample_holding())
    assert "偏多" in result
    mock_client.messages.create.assert_called_once()


@patch("investbrief.core.llm.get_client", side_effect=RuntimeError("no key"))
def test_generate_stock_conclusion_llm_init_fail_fallback(mock_get_client):
    result = generate_stock_conclusion(_sample_holding())
    assert result
    assert "偏多" in result


def test_generate_stock_conclusion_skips_error_holding():
    r = HoldingResult(symbol="XXX", market="cn", type="stock", error="分析失败")
    assert generate_stock_conclusion(r) == ""


def test_extract_technicals_backfills_19_fields():
    """_extract_technicals should surface 19 indicator fields (18 + regime)."""
    import pandas as pd
    from investbrief.holdings.analyzer import _extract_technicals

    # 70 rows of synthetic OHLCV so all windows (5/10/20/60) compute
    n = 70
    hist = pd.DataFrame({
        "close": [100 + i * 0.5 + (i % 5) for i in range(n)],
        "volume": [1000 + i * 10 for i in range(n)],
    })
    result = _extract_technicals(hist)
    expected_keys = {
        "ma_alignment", "rsi", "macd_cross", "return_20d", "return_60d", "position_60d",
        "ma5", "ma20", "ma60", "macd_dif", "macd_bar", "boll_position",
        "return_5d", "return_10d", "volume_ratio",
        "new_high_60d", "new_low_60d", "high_60d",
        "regime",
    }
    assert set(result.keys()) == expected_keys, (
        f"missing: {expected_keys - set(result.keys())}; "
        f"extra: {set(result.keys()) - expected_keys}"
    )
    # New fields should have real values (not None) for this synthetic uptrend
    assert result["ma5"] is not None
    assert result["volume_ratio"] is not None
    assert result["return_5d"] is not None
    # regime inferred for this uptrend synthetic
    assert result["regime"] in ("trending_up", "trending_down", "volatile", "sideways")

