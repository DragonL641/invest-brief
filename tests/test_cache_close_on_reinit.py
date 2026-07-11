"""FactorCache.init_cache 重复调用必须 close 旧实例,避免 scheduler 每日累积 SQLite 连接。

背景: scheduler 每日调 init_cache(path),原实现直接覆盖模块单例,旧实例的 SQLite
连接无人 close → 连接泄漏。修复后 init_cache 在新建前先 close 旧的。
"""
from unittest.mock import MagicMock

from investbrief.holdings import analyzer as analyzer_mod
from investbrief.picks import data as picks_data_mod


def test_holdings_init_cache_closes_old_instance(tmp_path):
    """重复 init_cache: 旧 FactorCache 实例的 close() 应被调用。"""
    analyzer_mod.init_cache(str(tmp_path / "h1.db"))
    old = analyzer_mod._factor_cache()
    assert old is not None
    old.close = MagicMock(wraps=old.close)

    analyzer_mod.init_cache(str(tmp_path / "h2.db"))
    old.close.assert_called_once()
    # 清理: 新实例 close 避免泄漏
    new = analyzer_mod._factor_cache()
    if new is not None:
        new.close()
    analyzer_mod._fcache = None


def test_picks_init_cache_closes_old_instance(tmp_path):
    """picks/data.py init_cache 重复调用: 旧 _cache 的 close() 应被调用。"""
    picks_data_mod.init_cache(str(tmp_path / "p1.db"))
    old = picks_data_mod.cache()
    assert old is not None
    old.close = MagicMock(wraps=old.close)

    picks_data_mod.init_cache(str(tmp_path / "p2.db"))
    old.close.assert_called_once()
    # 清理
    new = picks_data_mod.cache()
    if new is not None:
        new.close()
    picks_data_mod._cache = None


def test_holdings_init_cache_none_is_safe(tmp_path):
    """_fcache=None(首次 init 或 reset 后)→ 不抛异常,正常创建。"""
    analyzer_mod._fcache = None
    analyzer_mod.init_cache(str(tmp_path / "h.db"))
    assert analyzer_mod._factor_cache() is not None
    analyzer_mod._factor_cache().close()
    analyzer_mod._fcache = None
