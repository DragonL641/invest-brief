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


def test_volume_amplified_split_by_direction():
    """放量规则按涨跌拆分: 放量+涨= bullish; 放量+跌= bearish; 旧 volume_amplified 已删除。"""
    engine = RuleEngine()
    rule_ids = {r["id"] for r in engine.rules}
    assert "volume_amplified" not in rule_ids
    assert "volume_amplified_up" in rule_ids
    assert "volume_amplified_down" in rule_ids

    # 放量上涨 -> up 规则匹配, down 不匹配
    up_results = engine.evaluate({"volume_ratio": 2.0, "return_5d": 3.0})
    up_match = {r.rule_id: r.matched for r in up_results
                if r.rule_id in ("volume_amplified_up", "volume_amplified_down")}
    assert up_match["volume_amplified_up"] is True
    assert up_match["volume_amplified_down"] is False

    # 放量下跌 -> down 规则匹配, up 不匹配
    down_results = engine.evaluate({"volume_ratio": 2.0, "return_5d": -3.0})
    down_match = {r.rule_id: r.matched for r in down_results
                  if r.rule_id in ("volume_amplified_up", "volume_amplified_down")}
    assert down_match["volume_amplified_down"] is True
    assert down_match["volume_amplified_up"] is False


def test_volume_amplified_no_match_when_flat():
    """放量但 5日持平(return_5d=0): 两条规则都不匹配(0 既非 >0 也非 <0)。"""
    engine = RuleEngine()
    results = engine.evaluate({"volume_ratio": 2.0, "return_5d": 0.0})
    match = {r.rule_id: r.matched for r in results
             if r.rule_id in ("volume_amplified_up", "volume_amplified_down")}
    assert match["volume_amplified_up"] is False
    assert match["volume_amplified_down"] is False
