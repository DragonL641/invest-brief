# tests/test_picks_universe.py
"""picks.universe: spot 快照粗筛(纯函数,对 DataFrame 操作)。"""
import pandas as pd

from investbrief.picks import universe


def _cn_row(symbol, name, amount, cap, chg60, pe=15.0, pb=2.0):
    return {"代码": symbol, "名称": name, "成交额": amount, "总市值": cap,
            "60日涨跌幅": chg60, "市盈率-动态": pe, "市净率": pb}


def test_coarse_filter_cn_excludes_st_and_illiquid():
    df = pd.DataFrame([
        _cn_row("000001", "平安银行", 2e8, 3e11, 5.0),     # 通过
        _cn_row("000002", "ST万科", 3e8, 1e11, 8.0),        # ST 剔除
        _cn_row("000003", "小票", 5e7, 2e9, 12.0),          # 流动性不足
        _cn_row("000004", "下跌票", 2e8, 3e11, -5.0),       # 60日趋势向下
    ])
    profile = {"universe": {"exclude_st": True, "min_turnover_cn": 1.0e8,
                            "trend_60d_positive": True}}
    out = universe.coarse_filter(df, profile, market="cn")
    symbols = set(out["代码"].tolist())
    assert symbols == {"000001"}


def test_coarse_filter_empty_df_returns_empty():
    out = universe.coarse_filter(pd.DataFrame(), {"universe": {}}, market="cn")
    assert out.empty


def test_coarse_filter_market_cap_band_medium():
    df = pd.DataFrame([
        _cn_row("000001", "大盘", 2e8, 2e11, 5.0),
        _cn_row("000002", "中盘", 2e8, 3e10, 5.0),   # 50~1000亿 内
        _cn_row("000003", "小盘", 2e8, 3e9, 5.0),    # <50亿 外
    ])
    profile = {"universe": {"exclude_st": True, "min_turnover_cn": 1.0e8,
                            "trend_60d_positive": True, "market_cap_cn": [5.0e9, 1.0e11]}}
    out = universe.coarse_filter(df, profile, market="cn")
    assert set(out["代码"].tolist()) == {"000002"}


# --- 主板 + 股价门槛(配置化 mainboard_only / max_price_cn) ---


def _spot_cn(rows):
    """构造 CN spot DataFrame。rows = [{代码,名称,成交额,最新价,...}]"""
    return pd.DataFrame(rows)


def test_apply_cn_mainboard_only_keeps_60_00_drops_others():
    """mainboard_only: 只留 60/00 开头,排除 300/688/920。"""
    df = _spot_cn([
        {"代码": "600519", "名称": "贵州茅台", "成交额": 1e9, "最新价": 30},
        {"代码": "000001", "名称": "平安银行", "成交额": 1e9, "最新价": 30},
        {"代码": "002028", "名称": "思源电气", "成交额": 1e9, "最新价": 30},
        {"代码": "300750", "名称": "宁德时代", "成交额": 1e9, "最新价": 30},   # 创业板
        {"代码": "688981", "名称": "中芯国际", "成交额": 1e9, "最新价": 30},   # 科创板
        {"代码": "920819", "名称": "北证股", "成交额": 1e9, "最新价": 30},     # 北交所
    ])
    out = universe._apply_cn(df, {"mainboard_only": True})
    codes = set(out["代码"].astype(str))
    assert codes == {"600519", "000001", "002028"}, f"应只留主板,实际 {codes}"


def test_apply_cn_max_price_drops_above_threshold():
    """max_price_cn=40: 只留最新价 < 40；停牌(None 价)被排除。"""
    df = _spot_cn([
        {"代码": "600001", "名称": "A", "成交额": 1e9, "最新价": 30},
        {"代码": "600002", "名称": "B", "成交额": 1e9, "最新价": 45},
        {"代码": "600003", "名称": "C", "成交额": 1e9, "最新价": 100},
        {"代码": "600004", "名称": "停牌", "成交额": 1e9, "最新价": None},  # 停牌 NaN 价 → 排除
    ])
    out = universe._apply_cn(df, {"max_price_cn": 40})
    assert set(out["代码"].astype(str)) == {"600001"}  # B/C/停牌 都排除


def test_apply_cn_mainboard_and_price_combined():
    """主板 + 股价同时生效。"""
    df = _spot_cn([
        {"代码": "600001", "名称": "A", "成交额": 1e9, "最新价": 30},   # 主板+低价 ✓
        {"代码": "600002", "名称": "B", "成交额": 1e9, "最新价": 50},   # 主板+高价 ✗
        {"代码": "300001", "名称": "C", "成交额": 1e9, "最新价": 20},   # 创业板+低价 ✗
    ])
    out = universe._apply_cn(df, {"mainboard_only": True, "max_price_cn": 40})
    assert set(out["代码"].astype(str)) == {"600001"}


def test_apply_cn_no_mainboard_field_keeps_all():
    """无 mainboard_only 字段 → 不限板块(向后兼容)。"""
    df = _spot_cn([
        {"代码": "600001", "名称": "A", "成交额": 1e9, "最新价": 30},
        {"代码": "300001", "名称": "C", "成交额": 1e9, "最新价": 30},
    ])
    out = universe._apply_cn(df, {})
    assert len(out) == 2  # 不过滤


# --- 候选 cap 基线(Task 2) ---


def test_candidate_cap_halved():
    """cap 缩小一半：swing30/medium40/long30。"""
    from investbrief.pipelines.picks import _candidate_cap
    assert _candidate_cap("swing") == 30
    assert _candidate_cap("medium") == 40
    assert _candidate_cap("long") == 30
    assert _candidate_cap("unknown") == 30  # 默认
