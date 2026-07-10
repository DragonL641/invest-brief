# investbrief/picks/universe.py
"""全市场 spot 快照 + profile 粗筛 → 候选池。

粗筛只用 spot 可得字段:A股(stock_zh_a_spot_em)有 成交额/总市值/60日涨跌幅/PE/PB;
美股字段覆盖弱,部分条件降级(见 _apply_us)。多日精确门槛(20d均额/5d涨幅)
留到深拉阶段(Task 6 data.py)用历史校验。
"""
from __future__ import annotations

import pandas as pd

_CN = {"symbol": "代码", "name": "名称", "amount": "成交额", "cap": "总市值",
       "chg60": "60日涨跌幅", "pe": "市盈率-动态", "pb": "市净率",
       "price": "最新价"}


def get_spot_df(market: str):
    """拉 spot 快照。market∈{cn,us}。失败返回 None。"""
    from investbrief.datasources.akshare import AKShareClient
    c = AKShareClient()
    return c.get_cn_spot_df() if market == "cn" else c.get_us_spot_df()


def coarse_filter(spot_df: pd.DataFrame, profile: dict, market: str) -> pd.DataFrame:
    """按 profile['universe'] 粗筛 spot DataFrame,返回候选子集。空/缺列 → 空 DataFrame。"""
    if spot_df is None or spot_df.empty:
        return pd.DataFrame()
    u = profile.get("universe", {})
    df = _apply_cn(spot_df, u) if market == "cn" else _apply_us(spot_df, u)
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


def _apply_us(df: pd.DataFrame, u: dict) -> pd.DataFrame:
    """美股 spot 字段名与覆盖不固定,按实际存在的列尽量筛;列缺失则跳过该条件。"""
    cols = set(df.columns)
    name_col = next((c for c in ("名称", "name") if c in cols), None)
    if u.get("exclude_st", True) and name_col:
        df = df[~df[name_col].astype(str).str.contains("ST|退", na=False)]
    amount_col = next((c for c in ("成交额", "amount", "turnover") if c in cols), None)
    if u.get("min_turnover_us") and amount_col:
        df = df[pd.to_numeric(df[amount_col], errors="coerce") >= u["min_turnover_us"]]
    # 注意:stock_us_spot_em 只有当日涨跌幅(1d),无 60日涨跌幅;若把 "涨跌幅"
    # 列入候选会误用 1d 数据执行 60d 趋势过滤。这里只接受真正的 60d 列,
    # 缺失则该条件降级为 no-op(美股粗筛偏松,深拉阶段补 yfinance 历史校验)。
    chg60_col = next((c for c in ("60日涨跌幅", "changepercent") if c in cols), None)
    if u.get("trend_60d_positive") and chg60_col:
        df = df[pd.to_numeric(df[chg60_col], errors="coerce") > 0]
    cap_col = next((c for c in ("总市值", "marketCap", "marketcap") if c in cols), None)
    band = u.get("market_cap_us")
    if band and band != "mid" and cap_col and isinstance(band, list) and len(band) == 2:
        lo, hi = band
        cap = pd.to_numeric(df[cap_col], errors="coerce")
        df = df[(cap >= lo) & (cap <= hi)]
    return df
