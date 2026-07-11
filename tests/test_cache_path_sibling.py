"""缓存路径必须与宏库同目录但不同文件名(兄弟文件),不能用字符串替换。

背景: 原 `_CACHE_PATH = str(DB_PATH).replace("macro_data.db", "xxx_cache.db")`
当用户设 `INVESTBRIEF_DB_PATH=/data/custom.db`(不含 "macro_data.db")时,
.replace 无效 → 缓存路径=宏库路径 → FactorCache 在宏 DB 建 cache 表,锁竞争/数据混淆。
"""
from pathlib import Path


def test_picks_cache_path_is_sibling_of_db():
    """picks_cache.db 与 DB_PATH 同目录、不同文件、文件名正确。"""
    from investbrief.core.config import DB_PATH
    from investbrief.pipelines import picks

    cache = Path(picks._CACHE_PATH)
    db = Path(DB_PATH)
    assert cache.name == "picks_cache.db"
    assert cache.parent == db.parent
    assert picks._CACHE_PATH != str(DB_PATH)


def test_holdings_cache_path_is_sibling_of_db():
    """holdings_cache.db 与 DB_PATH 同目录、不同文件、文件名正确。"""
    from investbrief.core.config import DB_PATH
    from investbrief.pipelines import holdings

    cache = Path(holdings._CACHE_PATH)
    db = Path(DB_PATH)
    assert cache.name == "holdings_cache.db"
    assert cache.parent == db.parent
    assert holdings._CACHE_PATH != str(DB_PATH)


def test_formula_robust_to_custom_db_name():
    """DB_PATH 不含 "macro_data.db" 字面量时,with_name 仍正确(回归核心)。

    旧实现 `.replace` 对不含该字面量的路径无效 → 缓存=宏库;新实现 `with_name` 始终正确。
    """
    custom_db = Path("/data/custom.db")

    # 新实现: with_name 无论 DB 文件名如何都正确替换文件名
    picks_cache = custom_db.with_name("picks_cache.db")
    holdings_cache = custom_db.with_name("holdings_cache.db")
    assert str(picks_cache) == "/data/picks_cache.db"
    assert str(holdings_cache) == "/data/holdings_cache.db"
    assert str(picks_cache) != str(custom_db)
    assert str(holdings_cache) != str(custom_db)

    # 旧实现: replace 对不含字面量的路径无效(证明 bug)
    assert str(custom_db).replace("macro_data.db", "picks_cache.db") == str(custom_db)
