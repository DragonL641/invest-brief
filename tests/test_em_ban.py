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


# --- 封禁事件日志(运维可观测) ---
def test_ban_logged_once_per_window(monkeypatch, caplog):
    """新进入封禁窗口时 INFO 恰好一次; 窗口内继续失败不重复刷。"""
    _reset(monkeypatch)
    with caplog.at_level("INFO", logger="investbrief.datasources.akshare"):
        for _ in range(3):
            ak._record_em_outcome(success=False)  # 第 3 次触发封禁 → 1 条 INFO
        for _ in range(5):
            ak._record_em_outcome(success=False)  # 封禁期内继续失败 → 不再打
    ban_logs = [r for r in caplog.records if "eastmoney banned" in r.message]
    assert len(ban_logs) == 1, f"应只打 1 次, 实际 {len(ban_logs)}"


def test_ban_logged_again_after_recovery(monkeypatch, caplog):
    """成功清零后(封禁窗口已过期, 符合真实时序)再次累计达阈值 → 第 2 次封禁 INFO。

    真实时序: 封禁窗口(300s)未过期时请求被短路 raise _EMBanned, 不会 record success;
    只有窗口过期后实连成功才清零。故此处用 monkeypatch time.monotonic 推进过窗口。
    """
    _reset(monkeypatch)
    t = [100.0]
    monkeypatch.setattr(ak.time, "monotonic", lambda: t[0])
    with caplog.at_level("INFO", logger="investbrief.datasources.akshare"):
        for _ in range(3):
            ak._record_em_outcome(success=False)  # 封禁 #1: _em_ban_until=400
        t[0] = 500.0                              # 窗口过期(此后请求才实连)
        ak._record_em_outcome(success=True)       # 清零
        for _ in range(3):
            ak._record_em_outcome(success=False)  # 封禁 #2: newly_banned=(500>=400)=True
    ban_logs = [r for r in caplog.records if "eastmoney banned" in r.message]
    assert len(ban_logs) == 2, f"应打 2 次(每窗口 1 次), 实际 {len(ban_logs)}"
