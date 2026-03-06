"""Time utilities: timezone constants and date-range helpers."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone


CST = timezone(timedelta(hours=8))
UTC = timezone.utc


def today_cst() -> date:
    return datetime.now(CST).date()


def cst_day_window(d: date) -> tuple[datetime, datetime]:
    """Return (start_of_day, end_of_day) in CST as UTC-aware datetimes."""
    start = datetime(d.year, d.month, d.day, tzinfo=CST)
    end = datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=CST)
    return start, end


def date_range(start: date, end: date) -> list[date]:
    """Inclusive list of dates from start to end."""
    result: list[date] = []
    cur = start
    while cur <= end:
        result.append(cur)
        cur += timedelta(days=1)
    return result
