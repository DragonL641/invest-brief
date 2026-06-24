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


def get_upcoming_events_with_yfinance(days_ahead: int = 21) -> List[Dict[str, Any]]:
    """获取未来重大经济事件，聚合为大类（CPI/NFP/PCE/FOMC/GDP）。

    yfinance 经济日历返回细粒度指标系列（如 CPI 拆成同比/环比/Core 多条），
    这里按关键词聚合成大类、每类取最近一条；并用规则版（含 FOMC 硬编码）
    作为兜底与补充。
    """
    base = get_upcoming_events(days_ahead)  # 规则版：FOMC 硬编码 + CPI/NFP/PCE 估算
    try:
        from .clients import YFinanceClient
        client = YFinanceClient()
        if not client.enabled:
            return base

        now = datetime.now()
        start = now.strftime("%Y-%m-%d")
        end = (now + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
        events = client.get_economic_calendar(start=start, end=end, limit=30)
        if not events:
            return base

        categories = [
            ("CPI（消费者价格指数）", ("cpi",)),
            ("非农就业报告（NFP）", ("non farm", "nonfarm", "employment situation", "unemployment rate")),
            ("PCE 物价指数", ("pce", "personal consumption")),
            ("FOMC 议息会议", ("fomc", "federal funds", "interest rate decision")),
            ("GDP", ("gdp", "gross domestic")),
        ]

        def _cat(name: str):
            low = name.lower()
            for label, kws in categories:
                if any(k in low for k in kws):
                    return label
            return None

        by_cat: dict = {}
        for e in events:
            if not (-1 <= e["days_away"] <= days_ahead):
                continue
            cat = _cat(e.get("name", ""))
            if not cat:
                continue
            cur = by_cat.get(cat)
            if cur is None or e["days_away"] < cur["days_away"]:
                by_cat[cat] = {**e, "name": cat, "importance": "high"}

        if by_cat:
            merged = {e["name"]: e for e in base}  # 规则版兜底（FOMC 硬编码 + NFP/PCE 估算）
            merged.update(by_cat)  # yfinance 实际日期覆盖同名大类
            result = sorted(merged.values(), key=lambda x: x["days_away"])
            logger.info(f"Got {len(result)} major economic events (aggregated)")
            return result
    except Exception as e:
        logger.warning(f"yfinance economic calendar failed, using rules: {e}")

    return base
