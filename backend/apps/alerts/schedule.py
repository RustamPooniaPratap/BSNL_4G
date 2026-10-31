"""Next run time of an automation, in its own timezone (stored in UTC). Monthly runs use days 1-28 so every month has them."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .models import Automation


def next_run(a: Automation, after: datetime) -> datetime | None:
    """The first run strictly after ``after``; None when the schedule has ended (or is event-driven)."""
    if a.frequency == Automation.Frequency.EVENT:
        return None
    tz = ZoneInfo(a.timezone)
    local_after = after.astimezone(tz)
    start = max(a.start_date or local_after.date(), local_after.date())
    at = lambda d: datetime.combine(d, a.run_time, tzinfo=tz)  # noqa: E731
    if a.frequency == Automation.Frequency.ONCE:
        d = a.start_date or local_after.date()
        return at(d) if at(d) > after else None
    candidate: date | None = None
    for offset in range(0, 400):
        d = start + timedelta(days=offset)
        if a.frequency == Automation.Frequency.WEEKLY and d.weekday() != a.weekday:
            continue
        if a.frequency == Automation.Frequency.MONTHLY and d.day != a.month_day:
            continue
        if at(d) > after:
            candidate = d
            break
    if candidate is None or (a.end_date and candidate > a.end_date):
        return None
    return at(candidate)
