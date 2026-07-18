"""持仓 K 线形态识别(第一梯队 5 形态)。

纯函数,自给自足:从 OHLCV DataFrame 自行计算趋势/量能/形态判定,
不依赖外部 technicals(其字段是「最新一日」语义,而形态可能在 i<最新日触发)。

定位:辅助择时,非买卖指令。tier=B 形态,扣费后效力有限(Marshall 2006)。
位置过滤(趋势方向)+ 量能/次日确认标注,滤除震荡区裸形态噪音。
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

    返回 list[dict],按 trigger_date 降序(最近在前);同日多形态取首个命中。
    失败/数据不足 → []。
    """
    if hist_df is None or not hasattr(hist_df, "empty") or hist_df.empty:
        return []
    try:
        df = hist_df.sort_index()
    except Exception as e:
        logger.warning(f"detect_patterns sort_index failed: {e}")
        return []
    if not {"open", "high", "low", "close", "volume"}.issubset(df.columns):
        return []
    if len(df) < 5:
        return []

    O = df["open"].to_numpy(dtype=float)
    H = df["high"].to_numpy(dtype=float)
    L = df["low"].to_numpy(dtype=float)
    C = df["close"].to_numpy(dtype=float)
    V = df["volume"].to_numpy(dtype=float)
    idx = df.index
    n = len(df)

    results = []
    start = max(3, n - lookback)           # 三线打击需回看 3 根
    for i in range(start, n):
        ctx = _context(C, V, i)
        hit = _detect_at(O, H, L, C, i, ctx)
        if hit is None:
            continue
        hit["trigger_date"] = _date_str(idx[i])
        hit["status"] = _confirm(C, i, hit["direction"])
        results.append(hit)

    results.sort(key=lambda r: r["trigger_date"], reverse=True)
    seen = set()
    deduped = []
    for r in results:                       # 同日去重留首个
        if r["trigger_date"] in seen:
            continue
        seen.add(r["trigger_date"])
        deduped.append(r)
    return deduped


def _context(C, V, i):
    """触发日 i 的局部上下文:近 TREND_WINDOW 日 close 趋势收益 + 量比。"""
    j = max(0, i - TREND_WINDOW)
    if i - 1 > j and C[j] > 0:
        trend_ret = (C[i - 1] - C[j]) / C[j]     # 用 i-1,避开形态本身大阳/阴的扭曲
    else:
        trend_ret = 0.0
    vlo = max(0, i - VOL_MA_WINDOW)
    vol_ma = V[vlo:i].mean() if i > vlo else 0.0
    vol_ratio = V[i] / vol_ma if vol_ma > 0 else 0.0
    return {"trend_ret": trend_ret, "vol_ratio": vol_ratio}


def _confirm(C, i, direction):
    """次日确认:i+1 不存在 → pending;方向一致 → confirmed;否则 unconfirmed。"""
    if i + 1 >= len(C):
        return "pending"
    if direction == "bull":
        return "confirmed" if C[i + 1] > C[i] else "unconfirmed"
    return "confirmed" if C[i + 1] < C[i] else "unconfirmed"


def _detect_at(O, H, L, C, i, ctx):
    """对触发日 i 套 5 形态(判定顺序:三线打击→吞没→白兵/乌鸦;更具体优先)+ 三要素位置过滤。

    位置过滤:看涨需 trend_ret < -TREND_THR(跌势);看跌需 trend_ret > TREND_THR(涨势);
    |trend_ret| <= TREND_THR(震荡/不明)→ 丢弃。返回命中 dict 或 None。
    """
    tr = ctx["trend_ret"]
    vol_confirmed = ctx["vol_ratio"] >= VOLUME_RATIO_MIN

    bull = _three_line_strike(O, H, L, C, i)
    if bull is None:
        bull = _bullish_engulfing(O, H, L, C, i)
    if bull is None:
        bull = _three_white_soldiers(O, H, L, C, i)
    if bull is not None:
        if tr < -TREND_THR:                    # 跌势 → 看涨有效
            return _wrap(bull, "bull", vol_confirmed)
        return None                            # 非跌势(涨势/震荡)→ 丢弃

    bear = _bearish_engulfing(O, H, L, C, i)
    if bear is None:
        bear = _three_black_crows(O, H, L, C, i)
    if bear is not None:
        if tr > TREND_THR:                     # 涨势 → 看跌有效
            return _wrap(bear, "bear", vol_confirmed)
        return None
    return None


def _wrap(hit, direction, vol_confirmed):
    id_, cn = hit
    return {
        "name": id_,
        "name_cn": cn,
        "direction": direction,
        "volume_confirmed": bool(vol_confirmed),
        "tier": "B",
    }


def _date_str(label):
    s = str(label)
    return s[:10]


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


def _in_body(O, C, k, prev):
    """第 k 根 open 是否落在第 prev 根实体 [min(O,C), max(O,C)] 内。"""
    lo = min(O[prev], C[prev])
    hi = max(O[prev], C[prev])
    return lo <= O[k] <= hi


def _three_white_soldiers(O, H, L, C, i):
    """三白兵:三根阳线逐级走高,开盘在前根实体内,实体较长。"""
    if i < 2:
        return None
    for k in (i - 2, i - 1, i):
        if not (C[k] >= O[k]):             # 均阳
            return None
        body = abs(C[k] - O[k])
        rng = H[k] - L[k]
        if rng <= 0 or body / rng < BODY_RATIO_MIN:
            return None
    if not (C[i - 2] < C[i - 1] < C[i]):   # 逐级走高
        return None
    if not (_in_body(O, C, i - 1, i - 2) and _in_body(O, C, i, i - 1)):
        return None
    return ("three_white_soldiers", "三白兵")


def _three_black_crows(O, H, L, C, i):
    """三只黑乌鸦:三根阴线逐级走低,开盘在前根实体内,实体较长。"""
    if i < 2:
        return None
    for k in (i - 2, i - 1, i):
        if not (C[k] < O[k]):              # 均阴
            return None
        body = abs(C[k] - O[k])
        rng = H[k] - L[k]
        if rng <= 0 or body / rng < BODY_RATIO_MIN:
            return None
    if not (C[i - 2] > C[i - 1] > C[i]):   # 逐级走低
        return None
    if not (_in_body(O, C, i - 1, i - 2) and _in_body(O, C, i, i - 1)):
        return None
    return ("three_black_crows", "三只黑乌鸦")
