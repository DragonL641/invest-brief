# investbrief/picks/factors.py
"""picks 因子库:统一签名 fn(hist_df, fundamentals, valuation) → float|None。

FACTOR_REGISTRY 的 key 与 strategies/pick_profiles.yaml 的 factors 名对齐。
数据不足返回 None(由 engine 在截面标准化时降级)。
"""
from __future__ import annotations
import logging
from collections.abc import Callable

import pandas as pd

from investbrief.core import ta

logger = logging.getLogger(__name__)


# ---- swing(技术面) ----

def _trend_strength(hist, _fund, _val) -> float | None:
    if len(hist) < 60:
        return None
    close = hist["close"]
    ma60 = ta.sma(close, 60).iloc[-1]
    if pd.isna(ma60) or ma60 == 0:
        return None
    raw = close.iloc[-1] / ma60 - 1
    mas = ta.ma_set(close, (20, 60, 120))
    m20, m60, m120 = mas.get("ma20"), mas.get("ma60"), mas.get("ma120")
    aligned = bool(m20 and m60 and m120 and m20 > m60 > m120)
    return float(raw * (1.2 if aligned else 0.8))


def _momentum_60d_ex5(hist, _fund, _val) -> float | None:
    if len(hist) < 65:
        return None
    c = hist["close"]
    return float(c.iloc[-5] / c.iloc[-65] - 1)


def _ma20_deviation(hist, _fund, _val) -> float | None:
    if len(hist) < 20:
        return None
    c = hist["close"]
    ma20 = ta.sma(c, 20).iloc[-1]
    if pd.isna(ma20) or ma20 == 0:
        return None
    return abs(float(c.iloc[-1] / ma20 - 1))   # invert 由 engine 处理


def _volume_price(hist, _fund, _val) -> float | None:
    """放量上涨日均量 / 缩量回调日均量(近10日)。"""
    if len(hist) < 11:
        return None
    recent = hist.iloc[-10:]
    up = recent[recent["close"].diff() > 0]
    dn = recent[recent["close"].diff() < 0]
    up_v = up["volume"].mean() if len(up) else None
    dn_v = dn["volume"].mean() if len(dn) else None
    if not up_v or not dn_v or dn_v == 0:
        return None
    return float(up_v / dn_v)


def _low_volatility_20d(hist, _fund, _val) -> float | None:
    """20 日日收益 std(invert 由 engine 处理:越小越好)。"""
    return ta.volatility(hist["close"], 20)


# ---- medium(基本面+技术) ----

def _growth(hist, fund, _val) -> float | None:
    ry, py = fund.get("revenue_yoy"), fund.get("profit_yoy")
    if ry is None or py is None:
        return None
    base = (ry + py) / 2
    # 加速加成:本期>上期(简化:有 profit_yoy 即视为正)
    return float(base * 1.15 if base > 0 else base)


def _quality(hist, fund, _val) -> float | None:
    roe = fund.get("roe")
    gm = fund.get("gross_margin")
    fcf = 1.0 if fund.get("fcf_positive") else 0.0
    if roe is None:
        return None
    gm = gm or 0.0
    # 低杠杆加成：debt_ratio 小=质量好。缺失走 0.5 中性（同 _moat 的 capex 模式）。
    debt = fund.get("debt_ratio")
    leverage_term = (1 - debt) if debt is not None else 0.5
    return float(roe * 100 + gm * 50 + fcf * 5 + leverage_term * 30)   # 粗合成,截面 rank 后尺度无关


def _valuation(hist, _fund, val) -> float | None:
    """估值因子:低估值好(invert 由 engine 截面 rank)。

    优先用 3 年分位(pe_pct_3y/pb_pct_3y);当前 data 未实现估值历史 →
    回退当前 PE/PB(spot 现成),截面 rank + invert 同样保证"低 PE 排前"。
    """
    pe_pct, pb_pct = val.get("pe_pct_3y"), val.get("pb_pct_3y")
    if pe_pct is not None or pb_pct is not None:
        parts = [x for x in (pe_pct, pb_pct) if x is not None]
        return float(sum(parts) / len(parts))
    pe, pb = val.get("pe"), val.get("pb")
    parts = [x for x in (pe, pb) if x is not None and x > 0]
    return float(sum(parts) / len(parts)) if parts else None


def _momentum_12m_ex1m(hist, _fund, _val) -> float | None:
    if len(hist) < 252:
        # 数据不足(美股/A股可能没满一年),用可得的更长窗口退化
        if len(hist) < 60:
            return None
        return float(hist["close"].iloc[-21] / hist["close"].iloc[0] - 1)
    c = hist["close"]
    return float(c.iloc[-21] / c.iloc[-252] - 1)


# ---- long(基本面) ----

def _moat(hist, fund, _val) -> float | None:
    gm = fund.get("gross_margin")
    capex = fund.get("capex_ratio")   # capex/revenue,低=轻资产=护城河
    if gm is None:
        return None
    capex_term = (1 - capex) if capex is not None else 0.5
    return float(gm * 100 + capex_term * 30)


def _profitability_stability(hist, fund, _val) -> float | None:
    """连续盈利年数(quality 子维度,从 quality 拆出独立成因子)。

    越多越稳 → 截面 rank 后越大越好(不 invert)。数据由 pipeline 注入
    fund['profitable_years'](picks.data.fetch_profitable_years, 30d 缓存;
    CN 同花顺年度报告期 / US yfinance financials)。

    gate min_profitable_years=3 做二元剔除后, 3 年 vs 8 年原本无区分度;
    本因子让"连续盈利能力"在通过 gate 的候选中有独立 gradation。
    """
    years = fund.get("profitable_years")
    if years is None:
        return None
    try:
        return float(years)
    except (TypeError, ValueError):
        return None


def _main_flow(hist, fund, _val) -> float | None:
    """主力资金近5日净流入占比均值(%)。正值=净流入(偏多)。CN only(US → None)。

    数据由 pipelines/picks.py:_enrich 从 data.fetch_flow 注入 fund['main_flow_5d']。
    用 main_pct(净流入/成交额占比)做截面可比的归一化,避免大盘股绝对额碾压。
    """
    return fund.get("main_flow_5d")


FACTOR_LABELS: dict[str, str] = {
    # 因子英文 key → 中文展示名(engine.triggers / renderer 共用)
    "trend_strength": "趋势强度", "momentum_60d_ex5": "动量(60日)",
    "ma20_deviation": "均线位置", "volume_price": "量价配合",
    "low_volatility_20d": "低波动", "growth": "成长", "quality": "质量",
    "valuation": "估值",
    "momentum_12m_ex1m": "动量(12月)", "moat": "护城河",
    "profitability_stability": "盈利稳定性",
    "main_flow": "主力资金",
}


FACTOR_REGISTRY: dict[str, Callable] = {
    "trend_strength": _trend_strength,
    "momentum_60d_ex5": _momentum_60d_ex5,
    "ma20_deviation": _ma20_deviation,
    "volume_price": _volume_price,
    "low_volatility_20d": _low_volatility_20d,
    "growth": _growth,
    "quality": _quality,
    "valuation": _valuation,
    "momentum_12m_ex1m": _momentum_12m_ex1m,
    "moat": _moat,
    "profitability_stability": _profitability_stability,
    "main_flow": _main_flow,
}


# TODO D: 因子大类(technical/fundamental)。industry_neutralize 仅对 fundamental 因子做行业内中位数减法。
FACTOR_CATEGORY: dict[str, str] = {
    "trend_strength": "technical",
    "momentum_60d_ex5": "technical",
    "ma20_deviation": "technical",
    "volume_price": "technical",
    "low_volatility_20d": "technical",
    "momentum_12m_ex1m": "technical",
    "growth": "fundamental",
    "quality": "fundamental",
    "valuation": "fundamental",
    "moat": "fundamental",
    "profitability_stability": "fundamental",   # quality 子维度,参与行业中性化
    "main_flow": "flow",   # 资金面:不参与行业中性化(swing 也关了中性化)
}
