"""ETF 规则引擎:dimension_summary 加权汇总 + fallback 加权结论。

C1 修复:etf_rules.yaml 配置了 weight(0.3~1.2)但引擎原只计数,
导致金叉(1.2)与 5d涨跌(0.5)等价。修复后 dimension_summary 累加 weight,
_fallback_conclusion 用加权和判多空。
"""
from investbrief.holdings.etf.engine import RuleEngine, RuleResult
from investbrief.holdings.etf.analyzer import ETFAnalyzer


def _rr(dimension, signal, weight, matched=True):
    return RuleResult(
        rule_id=f"r-{dimension}-{signal}", dimension=dimension, name="t",
        description="", signal=signal, matched=matched, weight=weight,
    )


def test_dimension_summary_sums_weights_not_counts():
    """金叉 weight=1.2 与 5d涨跌 weight=0.5 不再等价:汇总值即 weight 之和。"""
    engine = RuleEngine()
    results = [
        _rr("技术面", "bullish", 1.2),   # 金叉级
        _rr("趋势面", "bullish", 0.5),   # 5d涨跌级
        _rr("技术面", "bearish", 1.0),
        _rr("资金面", "neutral", 0.3),
        _rr("技术面", "bullish", 0.0, matched=False),  # 不匹配,不累加
    ]
    summary = engine.dimension_summary(results)
    assert summary["技术面"]["bullish"] == 1.2
    assert summary["技术面"]["bearish"] == 1.0
    assert summary["趋势面"]["bullish"] == 0.5
    assert summary["资金面"]["neutral"] == 0.3


def test_dimension_summary_weights_break_tie_that_counts_would_not():
    """一个高权重 bullish(1.2) vs 两个低权重 bearish(各 0.5):
    计数法 bearish=2 > bullish=1(偏空);加权法 bullish=1.2 > bearish=1.0(偏多)。
    """
    engine = RuleEngine()
    results = [
        _rr("技术面", "bullish", 1.2),
        _rr("技术面", "bearish", 0.5),
        _rr("技术面", "bearish", 0.5),
    ]
    summary = engine.dimension_summary(results)
    assert summary["技术面"]["bullish"] > summary["技术面"]["bearish"]


def test_dimension_summary_ignores_unmatched():
    engine = RuleEngine()
    results = [_rr("技术面", "bullish", 1.0, matched=False)]
    assert engine.dimension_summary(results) == {}


def test_fallback_conclusion_uses_weighted_scores():
    """_fallback_conclusion 读取加权后的 dim_summary,输出"分"而非"项"。"""
    analyzer = ETFAnalyzer()
    dim = {"技术面": {"bullish": 2.4, "bearish": 0.5, "warning": 0.0, "neutral": 0.0}}
    text = analyzer._fallback_conclusion(dim)
    assert "偏多" in text
    assert "2.4" in text
    assert "项" not in text   # 不再说"项"(现在是加权和)


def test_fallback_conclusion_bearish_when_weighted_bearish_dominates():
    analyzer = ETFAnalyzer()
    dim = {"技术面": {"bullish": 0.5, "bearish": 2.0, "warning": 0.0, "neutral": 0.0}}
    assert "偏空" in analyzer._fallback_conclusion(dim)


def test_fallback_conclusion_empty():
    analyzer = ETFAnalyzer()
    assert "数据不足" in analyzer._fallback_conclusion({})


def test_dimension_summary_float_init():
    """汇总 dict 初始为 float(0.0),便于累加 float weight。"""
    engine = RuleEngine()
    results = [_rr("技术面", "bullish", 0.8)]
    summary = engine.dimension_summary(results)
    assert isinstance(summary["技术面"]["bullish"], float)
