"""统一的时区感知时间工具（避免 naive datetime 在非 CN 服务器/容器错位）。

Docker 默认 UTC，naive datetime.now() 会比上海时间慢 8 小时，导致邮件标题日期、
cutoff 时间窗口、经济日历"今天"判定全部偏移；mail Date 头缺 %z 偏移可能被
QQ/Exchange 判为垃圾邮件。统一用 now_cn() 取上海时区感知时间。
"""
from datetime import datetime
from zoneinfo import ZoneInfo

CN_TZ = ZoneInfo("Asia/Shanghai")


def now_cn() -> datetime:
    """返回上海时区感知的当前时间（替代裸 datetime.now()）。"""
    return datetime.now(CN_TZ)
