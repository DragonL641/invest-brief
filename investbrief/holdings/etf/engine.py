"""规则匹配引擎。

从 strategies/etf_rules.yaml 加载（YAML），对分析数据逐条评估，返回匹配结果。
使用受限 eval 执行规则条件表达式，仅允许白名单内操作。
"""
import logging
from dataclasses import dataclass

import yaml

from investbrief.core.strategy_loader import load_strategy

logger = logging.getLogger(__name__)

# eval 白名单：只允许基础比较运算
_SAFE_BUILTINS = {
    "True": True, "False": False, "None": None,
    "abs": abs, "round": round, "min": min, "max": max,
}


@dataclass
class RuleResult:
    rule_id: str
    dimension: str
    name: str
    description: str
    signal: str  # bullish / bearish / warning / neutral
    matched: bool
    weight: float
    detail: str = ""


class RuleEngine:
    def __init__(self, rules_path: str | None = None):
        if rules_path:
            with open(rules_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        else:
            data = load_strategy("etf_rules")
        # enabled 字段过滤（缺省视为 True）
        self.rules = [r for r in data["rules"] if r.get("enabled", True)]
        self._validate_rules()

    def _validate_rules(self):
        """预检查规则 condition 表达式语法。"""
        for rule in self.rules:
            try:
                compile(rule["condition"], f"<rule:{rule['id']}>", "eval")
            except SyntaxError as e:
                logger.warning(f"Rule {rule['id']} has invalid condition: {e}")

    def evaluate(self, data: dict) -> list[RuleResult]:
        """遍历所有规则，对数据做匹配。

        data: 扁平化 dict，键名对应规则 condition 中的变量名。
        规则条件表达式通过受限 eval 执行，仅能访问 data 中的变量。
        """
        results = []
        for rule in self.rules:
            matched = False
            detail = ""
            try:
                # Restricted eval: only data dict accessible, no builtins
                matched = bool(
                    eval(rule["condition"], {"__builtins__": _SAFE_BUILTINS}, data)
                )
            except Exception as e:
                logger.debug(f"Rule {rule['id']} eval skipped: {e}")
                matched = False

            if matched:
                detail = _build_detail(rule, data)

            results.append(RuleResult(
                rule_id=rule["id"],
                dimension=rule["dimension"],
                name=rule["name"],
                description=rule["description"],
                signal=rule["signal"],
                matched=matched,
                weight=rule.get("weight", 1.0),
                detail=detail,
            ))
        return results

    def dimension_summary(self, results: list[RuleResult]) -> dict[str, dict]:
        """按维度汇总匹配结果。"""
        summary: dict[str, dict] = {}
        for r in results:
            if not r.matched:
                continue
            dim = r.dimension
            if dim not in summary:
                summary[dim] = {"bullish": 0, "bearish": 0, "warning": 0, "neutral": 0}
            if r.signal in summary[dim]:
                summary[dim][r.signal] += 1
        return summary


def _build_detail(rule: dict, data: dict) -> str:
    """根据规则 ID 生成可读的详情文本。"""
    rid = rule["id"]
    try:
        if rid == "ma_bullish_alignment":
            return f"MA5({data.get('ma5')}) > MA10({data.get('ma10')}) > MA20({data.get('ma20')})"
        if rid == "ma_bearish_alignment":
            return f"MA5({data.get('ma5')}) < MA10({data.get('ma10')}) < MA20({data.get('ma20')})"
        if rid.startswith("ma5_cross"):
            return f"MA5: {data.get('ma5_prev')} → {data.get('ma5')}, MA20: {data.get('ma20_prev')} → {data.get('ma20')}"
        if rid.startswith("macd_"):
            return f"DIF={data.get('macd_dif')}, DEA={data.get('macd_dea')}, 柱={data.get('macd_bar')}"
        if rid.startswith("rsi_"):
            return f"RSI(14) = {round(data.get('rsi', 0), 1)}"
        if "new_" in rid:
            return f"当前价 {data.get('close', data.get('price'))}"
        if rid.startswith("return_5d"):
            return f"近5日 {data.get('return_5d')}%"
        if rid.startswith("return_20d"):
            return f"近20日 {data.get('return_20d')}%"
        if "main_net_inflow" in rid:
            flow = data.get("main_net_flow", 0)
            return f"主力流入 {abs(flow):.0f} 元" if flow else ""
        if "main_net_outflow" in rid:
            flow = data.get("main_net_flow", 0)
            return f"主力流出 {abs(flow):.0f} 元" if flow else ""
        if "premium_high" in rid:
            return f"溢价率 {data.get('premium_rate')}%，偏高"
        if "premium_discount" in rid:
            return f"溢价率 {data.get('premium_rate')}%，折价交易"
        if "pe_undervalued" in rid:
            return f"PE百分位 {data.get('pe_percentile')}%，低估"
        if "pe_overvalued" in rid:
            return f"PE百分位 {data.get('pe_percentile')}%，高估"
        if "pe_fair" in rid:
            return f"PE百分位 {data.get('pe_percentile')}%，合理"
        if "volume_amplified" in rid:
            return f"量比 {data.get('volume_ratio')}，放量"
        if "volume_shrunk" in rid:
            return f"量比 {data.get('volume_ratio')}，缩量"
    except Exception:
        pass
    return rule["description"]
