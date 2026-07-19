"""multpl.com 月度历史序列爬虫（Shiller PE / 10Y 美债）。

移植自 golden-butterfly-dashboard fetch_data.py。走系统代理（trust_env 默认 True，
与 gold_data FRED 一致；multpl 是海外站）。
"""
import io
import logging

import pandas as pd
import requests

logger = logging.getLogger(__name__)

_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
_TIMEOUT = 30


def fetch_multpl_series(path: str) -> pd.DataFrame:
    """爬 multpl.com 月度序列。

    path 例: '/shiller-pe' | '/10-year-treasury-rate'
    返回 DataFrame[date, value]（date 升序，value 已清洗为 float）。
    HTTP 错误 / 解析失败抛异常（由调用方 try/except 兜底）。
    """
    url = f"https://multpl.com{path}/table/by-month"
    r = requests.get(url, headers=_UA, timeout=_TIMEOUT)
    r.raise_for_status()
    dfs = pd.read_html(io.StringIO(r.text), match="Date")
    df = dfs[0].copy()
    # 清洗数值：去 % / 各类空格(含 en-space U+2002、nbsp U+00A0、thin U+2009、narrow nbsp U+202F)
    # / 千位逗号。multpl 偶尔在数值内部塞 en-space(如 "1 ensp 34.5")，不清洗会被 to_numeric 丢行。
    # re 模块把 \uXXXX 解释为对应 Unicode 码位；\s 已 Unicode-aware，这里显式列出做文档+防御。
    df["Value"] = (df["Value"].astype(str)
                   .str.replace("%", "", regex=False)
                   .str.replace(r"[\s\u00A0\u2002\u2007\u2009\u202F]", "", regex=True)
                   .str.replace(",", "", regex=False)
                   .str.strip())
    df["Value"] = pd.to_numeric(df["Value"], errors="coerce")
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date", "Value"]).sort_values("Date").reset_index(drop=True)
    df.columns = ["date", "value"]
    logger.info("multpl %s fetched %d rows", path, len(df))
    return df
