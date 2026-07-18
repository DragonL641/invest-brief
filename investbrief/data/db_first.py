"""历史日线 DB-First fast-path（stock_daily 跨日复用）。

从 holdings/analyzer.py 下沉，供 stock 与 ETF 分析共用，消除 etf→holdings 耦合。
纯逻辑 + DB 读写；live_fetch / live_fetch_full 由调用方注入（data 层不依赖 datasources），
DB 异常一律吞掉回退 live 结果（DB 非强依赖，pipeline 不阻塞）。

三级 fast-path：
1. stock_daily 有 today bar → 直接返回 DB（0 网络请求）。
2. DB 空 或 行数不足(< 500 天) + live_fetch_full → 拉全历史 → 回写。
3. DB 有历史没 today → live_fetch(symbol, days) 近期增量 → 回写。

symbol 写入用裸 6 位代码、market 由调用方指定（stock/etf 都用 "cn"，stock_daily 表
PK=(market,symbol,date)，ETF 代码与股票不冲突，零 schema 改动）。
"""
import logging

import pandas as pd

logger = logging.getLogger(__name__)


# 共享 stock_daily 句柄（stock/etf 分析共用同一 SQLite 连接，WAL + busy_timeout）。
_stock_db_handle = None


def stock_db():
    """共享 BaseData 句柄用于 stock_daily DB-First（stock/etf 共用）。

    CNData(db_path=DB_PATH) 只触发 BaseData.__init__ → _ensure_tables（CREATE TABLE IF NOT EXISTS），
    无 refresh / 网络副作用。惰性初始化，跨调用复用同一连接。
    """
    global _stock_db_handle
    if _stock_db_handle is None:
        from investbrief.core.config import DB_PATH
        from investbrief.data.cn_data import CNData
        _stock_db_handle = CNData(db_path=DB_PATH)
    return _stock_db_handle


def close_stock_db():
    """关闭共享 stock_daily 句柄（scheduler 长跑下 atexit 兜底，与 FactorCache 生命周期对齐）。"""
    global _stock_db_handle
    if _stock_db_handle is not None:
        try:
            _stock_db_handle.close()
        except Exception:
            pass
        _stock_db_handle = None


def history_db_first(market: str, symbol: str, *, days: int, db, live_fetch, live_fetch_full=None):
    """holdings history DB-First fast-path。

    1. stock_daily 有 today bar → 直接返回 DB（0 网络请求）。
    2. DB 空 或 行数不足(< 500 天, 不够全历史/回测) + live_fetch_full → 拉全历史 → 回写。
    3. DB 有历史没今天 → live_fetch(symbol, days) 近期增量 → 回写。
    任一步失败 → 回退 live_fetch 原始结果（DB 不是强依赖，pipeline 不阻塞）。

    列归一化覆盖源形状：
    - CN akshare get_stock_history / get_etf_hist: lowercase 列 + DatetimeIndex(date) + amount
    date 是 index（非列），需从 index 合成并 strftime 成 "YYYY-MM-DD"（匹配 has_today_bar 的 isoformat）。
    """
    try:
        if db is not None and db.has_today_bar(market, symbol):
            cached = db.query_stock_daily(market, symbol, n=days)
            if cached is not None and not cached.empty:
                # 归一化成与 live 一致的 shape（DatetimeIndex + ohlcv[+amount]），对齐 compute_indicators 契约：
                # query_stock_daily 返回 date 为列 + market/symbol 多余列；live 路径（akshare）date 是 index。
                dt_idx = pd.to_datetime(cached["date"])
                cached = cached.drop(columns=[c for c in ("market", "symbol", "date") if c in cached.columns])
                return cached.set_index(dt_idx)
    except Exception as e:
        logger.warning(f"history_db_first DB read {market}:{symbol} failed: {e}")
    # DB 空 或 行数不足(< 500 天) → 全历史(回测铺路); 否则近期增量(今天)
    db_insufficient = True
    try:
        if db is not None:
            probe = db.query_stock_daily(market, symbol, n=1000)
            db_insufficient = probe is None or len(probe) < 500
    except Exception:
        db_insufficient = True
    if db_insufficient and live_fetch_full is not None:
        df = live_fetch_full(symbol)
    else:
        df = live_fetch(symbol, days)
    try:
        if db is not None and isinstance(df, pd.DataFrame) and not df.empty:
            rows = df.rename(columns={
                "Open": "open", "High": "high", "Low": "low",
                "Close": "close", "Volume": "volume",
                "Date": "date",  # 兼容个别 mock 把 Date 作为列
            }).copy()
            rows["market"] = market
            rows["symbol"] = symbol
            if "date" not in rows.columns:
                rows["date"] = df.index  # akshare 源 date 是 index
            rows["date"] = pd.to_datetime(rows["date"]).dt.strftime("%Y-%m-%d")
            db.upsert_stock_df(rows)
    except Exception as e:
        logger.warning(f"history_db_first DB write {market}:{symbol} failed: {e}")
    return df
