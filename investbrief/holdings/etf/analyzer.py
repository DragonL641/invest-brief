"""ETF 分析服务。

组合数据获取 → 指标计算 → 规则匹配 → AI 综合研判，返回完整分析结果。
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict

from investbrief.data.db_first import history_db_first, stock_db
from investbrief.datasources.akshare import AKShareClient
from investbrief.holdings.etf.indicators import compute_indicators
from investbrief.holdings.etf.engine import RuleEngine, RuleResult

logger = logging.getLogger(__name__)

_fetch_pool = ThreadPoolExecutor(max_workers=3)


@dataclass
class ETFAnalysisResult:
    symbol: str
    name: str
    price: float | None = None
    change_pct: float | None = None
    iopv: float | None = None
    premium_rate: float | None = None
    main_net_flow: float | None = None
    rule_results: list[dict] = field(default_factory=list)
    dimension_summary: dict = field(default_factory=dict)
    ai_conclusion: str = ""
    data_snapshot: dict = field(default_factory=dict)
    degraded: bool = False  # spot+hist 都缺 → 数据源全面不可用，renderer 显式标注


class ETFAnalyzer:
    def __init__(self):
        self.client = AKShareClient()
        self.engine = RuleEngine()

    def analyze(self, symbol: str, market_data: dict | None = None, *, with_ai: bool = True) -> ETFAnalysisResult:
        """对单只 ETF 执行完整分析。

        symbol: 6 位 ETF 代码。
        market_data: 可选，大盘环境数据（来自现有 cn 市场数据）。

        韧性：spot(em) 缺失不再短路 —— hist 走 DB-First(stock_daily 落库 + sina 非 em 兜底)
        支撑价格/技术指标/规则/AI 研判；仅当 spot+hist 都缺时 degraded=True。
        """
        # 1. 数据获取：name(同花顺非 em) + spot(em, 失败为 {}) + hist(DB-First) + valuation
        etf_name = self.client.get_etf_name(symbol) or symbol  # 独立 name（同花顺非 em，解耦 spot）
        spot = self.client.get_etf_spot(symbol) or {}
        futures = {
            _fetch_pool.submit(
                history_db_first, "cn", symbol,
                days=120, db=stock_db(),
                live_fetch=lambda sym, days=120: self.client.get_etf_hist(sym, days=days),
                live_fetch_full=lambda sym: self.client.get_etf_hist(sym, start_date="20100101"),
            ): "hist",
            _fetch_pool.submit(self.client.get_index_valuation, symbol): "valuation",
        }
        results = {}
        for future in as_completed(futures):
            key = futures[future]
            try:
                results[key] = future.result()
            except Exception as e:
                logger.warning(f"Parallel fetch failed for {key}: {e}")
                results[key] = None

        hist = results.get("hist")
        valuation = results.get("valuation")

        # spot 缺失时用 hist 末根收盘兜底 price/change_pct（消除 em spot 硬门禁）
        price = spot.get("price")
        change_pct = spot.get("change_pct")
        if price is None and hist is not None and not hist.empty and "close" in hist.columns:
            price = float(hist["close"].iloc[-1])
            if change_pct is None and len(hist) >= 2:
                prev = float(hist["close"].iloc[-2])
                if prev:
                    change_pct = round((price / prev - 1) * 100, 2)

        # 2. 指标计算
        indicators = compute_indicators(hist) if hist is not None else {}

        # 3. 合并数据为扁平 dict
        data = {**indicators, **spot}
        if valuation:
            data["pe_percentile"] = valuation.get("pe_percentile")
            data["pe_ttm"] = valuation.get("pe_ttm")

        # 4. 规则匹配
        rule_results = self.engine.evaluate(data)
        dim_summary = self.engine.dimension_summary(rule_results)

        # 5. AI 综合研判（dry-run 可跳过省 token）；effective_spot 含兜底价格
        ai_conclusion = ""
        if with_ai:
            effective_spot = {**spot, "price": price, "change_pct": change_pct, "name": etf_name}
            ai_conclusion = self._ai_synthesize(symbol, effective_spot, rule_results, dim_summary, market_data,
                                                regime=indicators.get("regime"))

        # 6. 构造结果（degraded: spot+hist 都缺 → 数据源全面不可用）
        return ETFAnalysisResult(
            symbol=symbol,
            name=etf_name,
            price=price,
            change_pct=change_pct,
            iopv=spot.get("iopv"),
            premium_rate=spot.get("premium_rate"),
            main_net_flow=spot.get("main_net_flow"),
            rule_results=[asdict(r) for r in rule_results if r.matched],
            dimension_summary=dim_summary,
            ai_conclusion=ai_conclusion,
            data_snapshot=data,
            degraded=(not spot) and (hist is None or hist.empty),
        )

    def _ai_synthesize(
        self,
        symbol: str,
        spot: dict,
        rule_results: list[RuleResult],
        dim_summary: dict,
        market_data: dict | None,
        regime: str | None = None,
    ) -> str:
        """调用 Claude 进行综合研判。"""
        from investbrief.core.llm import call_claude
        from investbrief.holdings.regime_prompts import regime_hint

        hint = regime_hint(regime)
        regime_line = f"\n【当前市场状态：{regime}】{hint}" if hint else ""

        # 构造规则匹配摘要
        matched_rules = []
        for r in rule_results:
            if r.matched:
                matched_rules.append(f"  {r.dimension}/{r.name}({r.signal}): {r.detail or r.description}")
        rules_text = "\n".join(matched_rules) if matched_rules else "  无匹配规则"

        # 维度汇总
        dim_text = "\n".join(
            f"  {dim}: bullish={counts.get('bullish',0)}, bearish={counts.get('bearish',0)}, "
            f"warning={counts.get('warning',0)}, neutral={counts.get('neutral',0)}"
            for dim, counts in dim_summary.items()
        )

        # 大盘环境
        market_text = ""
        if market_data:
            indices = market_data.get("indices", {}).get("data", [])
            if indices:
                for idx in indices[:3]:
                    market_text += f"  {idx.get('name','')}: {idx.get('price','')} ({idx.get('change_pct','')}%)\n"

        prompt = f"""你是一位ETF投资顾问。基于以下信息给出综合研判。
{regime_line}

ETF: {symbol} {spot.get('name', '')}
当前价格: {spot.get('price')}  涨跌幅: {spot.get('change_pct')}%
IOPV: {spot.get('iopv')}  溢价率: {spot.get('premium_rate')}%
主力净流入: {spot.get('main_net_flow')}

=== 规则匹配结果 ===
{rules_text}

=== 维度汇总 ===
{dim_text if dim_text else '  无数据'}

=== 大盘环境 ===
{market_text if market_text else '  未获取'}

要求：
1. 综合所有维度给出整体判断（偏多/偏空/中性）
2. 如果有矛盾信号，指出矛盾并给出你的倾向
3. 给出具体操作建议（买入/持有/观望/减仓）
4. 150字以内，第一句话直接给结论，不要铺垫和套话
5. 用中文回答"""

        text = call_claude(
            [{"role": "user", "content": prompt}],
            max_tokens=512,
        )
        return text if text else self._fallback_conclusion(dim_summary)

    def _fallback_conclusion(self, dim_summary: dict) -> str:
        """AI 不可用时的 fallback 结论(基于加权和)。"""
        if not dim_summary:
            return "数据不足，无法生成结论。"
        total_bullish = sum(d.get("bullish", 0) for d in dim_summary.values())
        total_bearish = sum(d.get("bearish", 0) for d in dim_summary.values())
        total_warning = sum(d.get("warning", 0) for d in dim_summary.values())
        if total_bearish > total_bullish:
            return f"偏空。偏空分 {total_bearish:.1f} vs 偏多分 {total_bullish:.1f}，建议观望。"
        if total_bullish > total_bearish + 1:
            return f"偏多。偏多分 {total_bullish:.1f} vs 偏空分 {total_bearish:.1f}，趋势向好。"
        if total_warning > 0:
            return f"中性偏谨慎。警告分 {total_warning:.1f}，注意风险。"
        return f"中性。偏多分 {total_bullish:.1f}，偏空分 {total_bearish:.1f}，多空均衡。"
