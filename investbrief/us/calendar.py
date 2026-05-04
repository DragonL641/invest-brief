"""
Economic Calendar - Upcoming economic events

Provides FOMC meeting dates (hardcoded) and programmatic calculation
of periodic economic releases (CPI, NFP, PCE, retail sales).
"""

import logging
from datetime import datetime, timedelta
from calendar import monthcalendar
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

# FOMC meeting dates (8 per year, update annually)
# Source: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
FOMC_DATES = [
    # 2025
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
    "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
    # 2026 (estimated - typically Jan, Mar, May, Jun, Jul, Sep, Oct, Dec)
    "2026-01-28", "2026-03-18", "2026-05-06", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
]

# Event definitions: name, frequency, calculation rule
PERIODIC_EVENTS = [
    {
        "name": "CPI（消费者价格指数）",
        "importance": "high",
        "rule": "nth_weekday",  # 2nd Wednesday of each month (approximate)
        "week": 2,
        "weekday": 2,  # Wednesday = 2
    },
    {
        "name": "非农就业报告（NFP）",
        "importance": "high",
        "rule": "nth_weekday",  # 1st Friday of each month
        "week": 1,
        "weekday": 4,  # Friday = 4
    },
    {
        "name": "PCE 物价指数",
        "importance": "high",
        "rule": "monthly_offset",  # ~4 weeks after CPI, roughly last week
        "month_offset": 0,
        "day": 26,
    },
    {
        "name": "零售销售",
        "importance": "medium",
        "rule": "monthly_offset",
        "month_offset": 0,
        "day": 15,
    },
]


def _nth_weekday_of_month(year: int, month: int, week: int, weekday: int) -> str:
    """Get the date of the nth occurrence of a weekday in a month."""
    cal = monthcalendar(year, month)
    count = 0
    for week_row in cal:
        day = week_row[weekday]
        if day == 0:
            continue
        count += 1
        if count == week:
            return f"{year}-{month:02d}-{day:02d}"
    return None


def get_upcoming_events(days_ahead: int = 21) -> List[Dict[str, Any]]:
    """Get upcoming economic events in the next N days."""
    now = datetime.now()
    cutoff = now + timedelta(days=days_ahead)
    events = []

    # FOMC dates
    for date_str in FOMC_DATES:
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            continue
        if now <= dt <= cutoff:
            events.append({
                "name": "FOMC 议息会议",
                "date": date_str,
                "importance": "high",
                "days_away": (dt - now).days,
            })

    # Periodic events
    for month_offset in range(0, 3):  # Current month + next 2
        target_date = now.replace(day=1) + timedelta(days=32 * month_offset)
        year = target_date.year
        month = target_date.month

        for event_def in PERIODIC_EVENTS:
            if event_def["rule"] == "nth_weekday":
                date_str = _nth_weekday_of_month(
                    year, month, event_def["week"], event_def["weekday"]
                )
            elif event_def["rule"] == "monthly_offset":
                day = min(event_def["day"], 28)
                date_str = f"{year}-{month:02d}-{day:02d}"
            else:
                continue

            if not date_str:
                continue

            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                continue

            if now <= dt <= cutoff:
                events.append({
                    "name": event_def["name"],
                    "date": date_str,
                    "importance": event_def["importance"],
                    "days_away": (dt - now).days,
                })

    events.sort(key=lambda x: x["days_away"])
    return events
