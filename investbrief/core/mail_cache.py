"""邮件日级缓存：磁盘 HTML 文件，按 key 存 reports/cache/。

macro/picks 用户无关（key=日期）；holdings per-user（key=日期+email+持仓指纹）。
文件名含日期 → 跨天自动不命中（无需主动失效/清理）。
"""
import hashlib
import logging
from pathlib import Path

from investbrief.core.config import REPORTS_DIR

logger = logging.getLogger(__name__)

CACHE_DIR: Path = REPORTS_DIR / "cache"


def make_key(kind: str, date: str, email: str | None = None,
             holdings: list | None = None) -> str:
    """构造缓存 key。

    - macro/picks: f"{kind}_{date}"（用户无关，一天一份）
    - holdings: f"holdings_{date}_{email}_{指纹8位}"（持仓 sorted(symbol:market:type) md5 前 8 位）
    """
    if kind in ("macro", "picks"):
        return f"{kind}_{date}"
    if not email:
        raise ValueError("holdings cache key requires email")
    digest = ""
    if holdings:
        keys = sorted(f"{h['symbol']}:{h.get('market', '')}:{h.get('type', '')}" for h in holdings)
        digest = hashlib.md5("|".join(keys).encode()).hexdigest()[:8]
    return f"holdings_{date}_{email}_{digest}"


def _path(key: str) -> Path:
    return CACHE_DIR / f"{key}.html"


def get_cache(key: str) -> str | None:
    """读缓存 HTML；不存在/读失败 → None（不抛，调用方 fallback build）。"""
    p = _path(key)
    if not p.exists():
        return None
    try:
        return p.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning(f"mail_cache read {key} failed: {e}")
        return None


def set_cache(key: str, html: str):
    """写缓存 HTML（覆盖；首次 mkdir）。写失败仅 warning，不阻塞。"""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _path(key).write_text(html, encoding="utf-8")
    except Exception as e:
        logger.warning(f"mail_cache write {key} failed: {e}")
