"""akshare 模块级 _throttle：多线程下请求间隔 >= _MIN_INTERVAL。无网络。"""
import time
import threading
from investbrief.datasources import akshare as ak_mod


def test_throttle_enforces_min_interval(monkeypatch):
    monkeypatch.setattr(ak_mod, "_MIN_INTERVAL", 0.05)  # 加速
    timestamps = []
    lock = threading.Lock()

    def worker():
        ak_mod._throttle()
        with lock:
            timestamps.append(time.monotonic())

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads: t.start()
    for t in threads: t.join()

    # 4 次调用，相邻间隔应 >= ~0.05s（允许调度抖动，取 0.03 下限）
    timestamps.sort()
    gaps = [timestamps[i+1] - timestamps[i] for i in range(len(timestamps)-1)]
    assert min(gaps) >= 0.03, f"节流失效，最小间隔 {min(gaps):.3f}s"


def test_patched_session_request_throttles_eastmoney(monkeypatch):
    """d851197: 节流从 _with_retry 移到 _patched_session_request(HTTP 层)。
    eastmoney 请求触发 _throttle,非 eastmoney 不节流。"""
    monkeypatch.setattr(ak_mod, "_MIN_INTERVAL", 0.0)
    calls = {"throttle": 0, "http": 0}
    orig_throttle = ak_mod._throttle

    def spy():
        calls["throttle"] += 1
        orig_throttle()

    def fake_http(self, method, url, **kw):
        calls["http"] += 1
        return "resp"

    monkeypatch.setattr(ak_mod, "_throttle", spy)
    monkeypatch.setattr(ak_mod, "_orig_session_request", fake_http)

    ak_mod._patched_session_request("sess", "GET", "https://push2.eastmoney.com/api")
    assert calls["throttle"] >= 1
    assert calls["http"] == 1

    calls["throttle"] = 0
    ak_mod._patched_session_request("sess", "GET", "https://api.tavily.com/search")
    assert calls["throttle"] == 0   # 非 eastmoney 不节流


def test_with_retry_does_not_self_throttle(monkeypatch):
    """d851197: _with_retry 不再自己 _throttle(节流下放 patch 层,避免双重节流)。"""
    monkeypatch.setattr(ak_mod, "_MIN_INTERVAL", 0.0)
    calls = {"throttle": 0, "fn": 0}
    orig_throttle = ak_mod._throttle

    def spy():
        calls["throttle"] += 1
        orig_throttle()
    monkeypatch.setattr(ak_mod, "_throttle", spy)

    def fn():
        calls["fn"] += 1
        return "ok"
    ak_mod._with_retry(fn, label="t")
    assert calls["throttle"] == 0   # _with_retry 不再直接节流
    assert calls["fn"] == 1
