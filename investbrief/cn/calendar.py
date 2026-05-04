"""A股经济日历：央行、PMI、CPI、LPR 等重要日期。"""

import logging
from datetime import datetime, timedelta
from calendar import monthcalendar
from typing import Any

logger = logging.getLogger(__name__)

PERIODIC_EVENTS: list[dict[str, Any]] = [
    {"name": "LPR 报价", "importance": "high", "rule": "monthly_offset", "month_offset": 0, "day": 20},
    {"name": "官方 PMI", "importance": "high", "rule": "month_end", "month_offset": 0},
    {"name": "财新 PMI", "importance": "medium", "rule": "nth_weekday", "week": 1, "weekday": 2, "month_offset": 1},
    {"name": "CPI/PPI", "importance": "high", "rule": "nth_weekday", "week": 2, "weekday": 4, "month_offset": 1},
    {"name": "社融/M2 数据", "importance": "high", "rule": "monthly_offset", "month_offset": 1, "day": 12},
    {"name": "城镇调查失业率", "importance": "medium", "rule": "monthly_offset", "month_offset": 1, "day": 15},
]


def _nth_weekday_of_month(year: int, month: int, week: int, weekday: int) -> str:
    """计算某年某月第N个周X的日期。weekday: 0=周一, 4=周五。"""
    weeks = monthcalendar(year, month)
    if week <= len(weeks):
        day = weeks[week - 1][weekday]
        if day == 0:
            day = weeks[week][weekday] if week < len(weeks) else weeks[-1][weekday]
        return f"{year}-{month:02d}-{day:02d}"
    return ""


def _adjust_to_weekday(date_str: str) -> str:
    """如果日期落在周末，顺延到下一个周一。"""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    if dt.weekday() == 5:
        dt += timedelta(days=2)
    elif dt.weekday() == 6:
        dt += timedelta(days=1)
    return dt.strftime("%Y-%m-%d")


def get_upcoming_events(days_ahead: int = 30) -> list[dict[str, Any]]:
    """获取未来 N 天的 A 股经济事件。"""
    now = datetime.now()
    results = []

    for event in PERIODIC_EVENTS:
        for month_offset in range(0, 3):
            try:
                target_year = now.year
                target_month = now.month + month_offset + event.get("month_offset", 0)
                while target_month > 12:
                    target_month -= 12
                    target_year += 1

                rule = event["rule"]

                if rule == "monthly_offset":
                    day = event.get("day", 15)
                    date_str = f"{target_year}-{target_month:02d}-{day:02d}"
                    date_str = _adjust_to_weekday(date_str)
                elif rule == "nth_weekday":
                    date_str = _nth_weekday_of_month(
                        target_year, target_month,
                        event.get("week", 1), event.get("weekday", 4),
                    )
                elif rule == "month_end":
                    if target_month == 12:
                        next_month = datetime(target_year + 1, 1, 1)
                    else:
                        next_month = datetime(target_year, target_month + 1, 1)
                    last_day = (next_month - timedelta(days=1)).day
                    date_str = f"{target_year}-{target_month:02d}-{last_day:02d}"
                else:
                    continue

                event_date = datetime.strptime(date_str, "%Y-%m-%d")
                delta = (event_date - now).days
                if 0 <= delta <= days_ahead:
                    results.append({
                        "name": event["name"],
                        "date": date_str,
                        "importance": event["importance"],
                        "days_away": delta,
                    })
            except Exception as e:
                logger.warning(f"Failed to calculate date for {event['name']}: {e}")
                continue

    results.sort(key=lambda x: x["date"])
    return results
