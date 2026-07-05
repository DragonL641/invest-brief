"""Scheduler 测试：cron 选取 + timezone 从 config 读取（#9/#15 回归）。

run_scheduler 主循环需要 mock 时钟 + 子线程，这里只覆盖纯函数 first_enabled_cron
与 _first_enabled_timezone（它们决定调度行为，是 #9 timezone 被忽略的修复点）。
"""
from investbrief.pipelines.scheduler import first_enabled_cron, _first_enabled_timezone


def test_first_enabled_cron_dict_schedule():
    cfg = {"markets": {"us": {"enabled": True, "schedule": {"cron": "0 23 * * 1-5"}}}}
    assert first_enabled_cron(cfg) == "0 23 * * 1-5"


def test_first_enabled_cron_list_schedule():
    cfg = {"markets": {"us": {"enabled": True,
                              "schedule": [{"cron": "30 22 * * 1-5", "timezone": "Asia/Shanghai"}]}}}
    assert first_enabled_cron(cfg) == "30 22 * * 1-5"


def test_first_enabled_cron_prefers_us_over_cn():
    cfg = {"markets": {
        "us": {"enabled": True, "schedule": {"cron": "0 23 * * 1-5"}},
        "cn": {"enabled": True, "schedule": {"cron": "0 17 * * 1-5"}},
    }}
    assert first_enabled_cron(cfg) == "0 23 * * 1-5"  # us 优先


def test_first_enabled_cron_skips_disabled():
    cfg = {"markets": {
        "us": {"enabled": False, "schedule": {"cron": "0 23 * * 1-5"}},
        "cn": {"enabled": True, "schedule": {"cron": "0 17 * * 1-5"}},
    }}
    assert first_enabled_cron(cfg) == "0 17 * * 1-5"


def test_first_enabled_cron_none_when_no_market():
    assert first_enabled_cron({"markets": {}}) is None


def test_first_enabled_timezone_dict():
    cfg = {"markets": {"us": {"enabled": True,
                              "schedule": {"cron": "0 23 * * 1-5", "timezone": "America/New_York"}}}}
    # 修复前：硬编码 Asia/Shanghai，忽略 config；修复后：读取 config 的 timezone
    assert _first_enabled_timezone(cfg) == "America/New_York"


def test_first_enabled_timezone_list():
    cfg = {"markets": {"us": {"enabled": True,
                              "schedule": [{"cron": "0 23 * * 1-5", "timezone": "Asia/Shanghai"}]}}}
    assert _first_enabled_timezone(cfg) == "Asia/Shanghai"


def test_first_enabled_timezone_defaults_shanghai_when_missing():
    cfg = {"markets": {"us": {"enabled": True, "schedule": {"cron": "0 23 * * 1-5"}}}}  # 无 timezone
    assert _first_enabled_timezone(cfg) == "Asia/Shanghai"
