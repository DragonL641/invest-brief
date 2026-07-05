"""BaseData._retry_api 重试逻辑测试（#11 回归）。

_retry_api 是所有数据源失败重试的核心，此前零测试。用 __new__ 绕过 __init__
（避免建 SQLite DB），直接测方法。
"""
import pytest


def _bare_base_data():
    """构造不触发 __init__（不建 DB）的 BaseData 实例。

    BaseData 是 ABC（update_all/update_incremental 抽象），需用具体子类实例化。
    """
    from investbrief.data.base import BaseData

    class _Concrete(BaseData):
        def update_all(self): pass
        def update_incremental(self): pass

    return _Concrete.__new__(_Concrete)


def test_retry_api_succeeds_after_transient_failures(monkeypatch):
    sleeps = []
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))
    state = {"n": 0}

    def flaky():
        state["n"] += 1
        if state["n"] < 3:
            raise RuntimeError("transient")
        return "ok"

    bd = _bare_base_data()
    assert bd._retry_api(flaky) == "ok"
    assert state["n"] == 3        # 第 3 次成功
    assert len(sleeps) == 2       # 前 2 次失败后各 sleep 一次


def test_retry_api_raises_after_all_attempts_fail(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)

    def always_fail():
        raise RuntimeError("permanent")

    bd = _bare_base_data()
    with pytest.raises(RuntimeError, match="permanent"):
        bd._retry_api(always_fail)


def test_retry_api_returns_on_first_success(monkeypatch):
    sleeps = []
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))

    def ok():
        return "immediate"

    bd = _bare_base_data()
    assert bd._retry_api(ok) == "immediate"
    assert sleeps == []  # 无重试无 sleep
