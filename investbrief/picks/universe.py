# investbrief/picks/universe.py
"""CN spot 快照 + profile 粗筛 → 候选池。

粗筛只用 spot 可得字段:A股(stock_zh_a_spot_em)有 成交额/总市值/60日涨跌幅/PE/PB。
多日精确门槛(20d均额/5d涨幅)留到深拉阶段(Task 6 data.py)用历史校验。
"""
from __future__ import annotations

import pandas as pd

_CN = {"symbol": "代码", "name": "名称", "amount": "成交额", "cap": "总市值",
       "chg60": "60日涨跌幅", "pe": "市盈率-动态", "pb": "市净率",
       "price": "最新价"}


def get_spot_df(market: str = "cn"):
    """拉 CN spot 快照。失败返回 None。market 参数保留兼容,忽略(纯 CN)。"""
    from investbrief.datasources.akshare import AKShareClient
    return AKShareClient().get_cn_spot_df()


def coarse_filter(spot_df: pd.DataFrame, profile: dict, market: str = "cn") -> pd.DataFrame:
    """按 profile['universe'] 粗筛 spot DataFrame,返回候选子集。空/缺列 → 空 DataFrame。"""
    if spot_df is None or spot_df.empty:
        return pd.DataFrame()
    u = profile.get("universe", {})
    df = _apply_cn(spot_df, u)
    return df.reset_index(drop=True)


def _apply_cn(df: pd.DataFrame, u: dict) -> pd.DataFrame:
    name_col, amount_col = _CN["name"], _CN["amount"]
    cap_col, chg60_col = _CN["cap"], _CN["chg60"]

    if u.get("exclude_st", True) and name_col in df.columns:
        df = df[~df[name_col].astype(str).str.contains("ST", na=False)]
    if u.get("min_turnover_cn") and amount_col in df.columns:
        df = df[pd.to_numeric(df[amount_col], errors="coerce") >= u["min_turnover_cn"]]
    if u.get("trend_60d_positive") and chg60_col in df.columns:
        df = df[pd.to_numeric(df[chg60_col], errors="coerce") > 0]
    band = u.get("market_cap_cn")
    if band and cap_col in df.columns and len(band) == 2:
        lo, hi = band
        cap = pd.to_numeric(df[cap_col], errors="coerce")
        df = df[(cap >= lo) & (cap <= hi)]
    # 沪深主板(代码 60/00 开头),排除创业板(30)/科创板(688)/北交所(920/8/4)
    if u.get("mainboard_only") and _CN["symbol"] in df.columns:
        code = df[_CN["symbol"]].astype(str)
        df = df[code.str[:2].isin(["60", "00"])]
    # 股价上限(资金量约束)
    if u.get("max_price_cn") and _CN["price"] in df.columns:
        df = df[pd.to_numeric(df[_CN["price"]], errors="coerce") < u["max_price_cn"]]
    return df
