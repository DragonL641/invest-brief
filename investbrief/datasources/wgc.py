"""WGC（世界黄金协会）fsapi JSON API — 黄金行业 AISC 季度序列。

端点从 goldhub/data/aisc-gold 页面 HTML 的 data-chart-data-endpoint 反向工程，
非公开文档化 API（v11）。匿名可用，无需 auth/UA/break-cache。
数据源：Metals Focus（WGC 官方合作伙伴），全球行业聚合 AISC。
失败返回 None（调用方落空，不 fallback 静态常量）。
"""
import logging

import requests

logger = logging.getLogger(__name__)

_WGC_AISC_URL = "https://fsapi.gold.org/api/productioncosts/v11/charts/aisc"
_TIMEOUT = 30


def fetch_gold_aisc() -> list[tuple[str, float]] | None:
    """抓 WGC AISC 季度序列。

    返回 [(季度标签如 'Q4 2025', 美元/盎司), ...]；失败/空/形状异常返回 None。
    """
    try:
        r = requests.get(_WGC_AISC_URL, timeout=_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        chart = (data or {}).get("chartData") or {}
        cats = chart.get("categories") or []
        vals = chart.get("data") or []
        if not cats or not vals or len(cats) != len(vals):
            logger.warning(
                "WGC AISC unexpected shape: cats=%d vals=%d", len(cats), len(vals)
            )
            return None
        return [(str(c), float(v)) for c, v in zip(cats, vals)]
    except Exception as e:
        logger.warning("WGC AISC fetch failed: %s", e)
        return None
