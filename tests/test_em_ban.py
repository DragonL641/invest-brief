# tests/test_em_ban.py
"""eastmoney 封禁 negative cache 单测: 触发阈值/成功清零/_with_retry 短路/封禁期 raise。

封禁状态是 akshare 模块级 global, 每测前 _reset 清零(monkeypatch teardown 自动还原)。
"""
import pytest

from investbrief.datasources import akshare as ak


def _reset(monkeypatch):
    monkeypatch.setattr(ak, "_em_ban_until", 0.0)
    monkeypatch.setattr(ak, "_em_consecutive_fail", 0)


def test_three_failures_trigger_ban(monkeypatch):
    _reset(monkeypatch)
    assert not ak._is_em_banned()
    ak._record_em_outcome(success=False)
    ak._record_em_outcome(success=False)
    assert not ak._is_em_banned(), "2 次失败不应触发封禁"
    ak._record_em_outcome(success=False)
    assert ak._is_em_banned(), "连续 3 次应触发封禁"


def test_success_resets_counter(monkeypatch):
    _reset(monkeypatch)
    ak._record_em_outcome(success=False)
    ak._record_em_outcome(success=False)
    ak._record_em_outcome(success=True)  # 成功清零
    ak._record_em_outcome(success=False)
    ak._record_em_outcome(success=False)
    assert not ak._is_em_banned(), "清零后需重新累计 3 次才封禁"


def test_with_retry_short_circuits_on_banned(monkeypatch):
    """_EMBanned → _with_retry 立即返回 None, 不重试(不进 retry 循环)。"""
    _reset(monkeypatch)
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise ak._EMBanned("banned")

    r = ak._with_retry(fn, label="t", attempts=3)
    assert r is None
    assert calls["n"] == 1, "封禁应立即返回, 不重试"


def test_with_retry_still_retries_non_banned(monkeypatch):
    """非 _EMBanned 异常仍按 attempts 重试(回归: 新分支不破坏旧重试)。"""
    _reset(monkeypatch)
    monkeypatch.setattr(ak.time, "sleep", lambda *a, **k: None)  # 跳过退避
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise ValueError("other")

    r = ak._with_retry(fn, label="t", attempts=3)
    assert r is None
    assert calls["n"] == 3, "普通异常应重试满 3 次"


def test_patched_request_raises_when_banned(monkeypatch):
    """封禁窗口内, _patched_session_request 对 eastmoney URL 直接 raise _EMBanned(不连接)。"""
    _reset(monkeypatch)
    for _ in range(3):
        ak._record_em_outcome(success=False)
    with pytest.raises(ak._EMBanned):
        ak._patched_session_request(self=None, method="GET",
                                    url="https://push2.eastmoney.com/api/qt/stock/get")
