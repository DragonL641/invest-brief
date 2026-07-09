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


def test_with_retry_invokes_throttle(monkeypatch):
    """_with_retry 每次 fn() 前应 _throttle。"""
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
    assert calls["throttle"] >= 1
    assert calls["fn"] == 1
