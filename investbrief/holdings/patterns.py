"""持仓 K 线形态识别(第一梯队 5 形态)。

纯函数,自给自足:从 OHLCV DataFrame 自行计算趋势/量能/形态判定,
不依赖外部 technicals(其字段是「最新一日」语义,而形态可能在 i<最新日触发)。

定位:辅助择时,非买卖指令。tier=B 形态,扣费后效力有限(Marshall 2006)。
三要素(位置=趋势 + 量能 + 次日确认)过滤裸形态噪音。
"""
import logging

logger = logging.getLogger(__name__)

# ---- 阈值常量(可调)----
VOLUME_RATIO_MIN = 1.5       # 放量阈值
TREND_WINDOW = 20            # 趋势收益窗口
TREND_THR = 0.02             # 趋势阈值:|trend_ret|<此值视为震荡/不明,丢弃
BODY_RATIO_MIN = 0.5         # 实体占全幅(三白兵/黑乌鸦)
LOOKBACK_DEFAULT = 5         # 默认回看交易日
VOL_MA_WINDOW = 5            # 量比均线窗口


def detect_patterns(hist_df, *, lookback: int = LOOKBACK_DEFAULT) -> list[dict]:
    """检测近 lookback 根内的 K 线反转形态(第一梯队 5 形态)。

    返回 list[dict],按 trigger_date 降序(最近在前)。失败/数据不足 → []。
    """
    if hist_df is None or not hasattr(hist_df, "empty") or hist_df.empty:
        return []
    if not {"open", "high", "low", "close", "volume"}.issubset(hist_df.columns):
        return []
    if len(hist_df) < 5:
        return []
    return []


def _bullish_engulfing(O, H, L, C, i):
    """看涨吞没:前根阴 + 本根阳,实体吞没前根完整区间。命中返回 (id, cn),否则 None。"""
    if i < 1:
        return None
    if not (C[i - 1] < O[i - 1]):          # 前根阴
        return None
    if not (C[i] >= O[i]):                 # 本根阳
        return None
    if O[i] <= L[i - 1] and C[i] >= H[i - 1]:
        return ("bullish_engulfing", "看涨吞没")
    return None


def _bearish_engulfing(O, H, L, C, i):
    """看跌吞没:前根阳 + 本根阴,实体吞没前根完整区间。"""
    if i < 1:
        return None
    if not (C[i - 1] >= O[i - 1]):         # 前根阳
        return None
    if not (C[i] < O[i]):                  # 本根阴
        return None
    if O[i] >= H[i - 1] and C[i] <= L[i - 1]:
        return ("bearish_engulfing", "看跌吞没")
    return None


def _three_line_strike(O, H, L, C, i):
    """三线打击(看涨):前3根逐级走低阴线 + 本根大阳吞没三根全部区间。"""
    if i < 3:
        return None
    for k in (i - 3, i - 2, i - 1):
        if not (C[k] < O[k]):              # 前三根均阴
            return None
    if not (C[i - 3] > C[i - 2] > C[i - 1]):  # 逐级走低
        return None
    if not (C[i] >= O[i]):                 # 本根阳
        return None
    hh = max(H[i - 3], H[i - 2], H[i - 1])
    ll = min(L[i - 3], L[i - 2], L[i - 1])
    if C[i] >= hh and O[i] <= ll:
        return ("three_line_strike", "三线打击")
    return None
