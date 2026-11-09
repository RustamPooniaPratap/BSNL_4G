"""The business rules of the new data layer, in one place (confirmed 4 Nov 2026). Every importer, the monthly
calculation and the dashboard dataset use these functions; no module has its own version.

Daily values (4G Saturation and LWE alike):
- Availability comes from the raw CSV column "Nw Avail (4G TCS)", read as a percentage (98.50 = 98.50%), never as a
  fraction. Valid range 0-100; anything else is rejected, never capped or corrected. A blank is "not reported": no
  record, never 0.
- Outage over a full 24-hour reporting day: outage = 1440 x (1 - availability / 100), unrounded; conversely
  availability = 100 x (1 - outage / 1440). Valid outage 0-1,440 minutes; anything else is rejected, never capped.

O&M Start:
- The Consolidation Matrix O&M Start Date is the only source. A site is O&M Start in a month when its O&M Start Date
  falls on or before the month's last day; its O&M days in that month start on the later of the 1st and the date.
- A missing or unreadable O&M Start Date: the site is not O&M Start (nothing is guessed) and is flagged for review.
- Uptime Master O&M flags are never used.

On-Air (decided 4 Nov 2026): the same rule with the matrix Site On-Air Date (on_air_effective_from); a site without a
readable On-Air Date is not On-Air and is flagged for review.

Periods (decided 4 Nov 2026):
- Weeks of a calendar month: 1-7, 8-14, 15-21 and 22 to the month's last day (weeks()).
- MTD runs from the 1st over consecutive dates that have data for the scope (any in-scope site has a value) and stops
  before the first date without data (mtd_dates()); later dates are not part of the MTD.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date

MINUTES_PER_DAY = 1440
AVAILABILITY_COLUMN = 'Nw Avail (4G TCS)'
AVAILABILITY_FIELD = 'avail_4g_tcs'  # raw CSV reader field of that column


@dataclass(frozen=True)
class Checked:
    value: float | None  # None when blank or rejected
    code: str | None = None  # None = usable; 'not_reported' = blank; otherwise a rejection reason
    message: str = ''

    @property
    def usable(self) -> bool:
        return self.code is None


def _number(raw) -> tuple[float | None, str]:
    """(number, text as written). Blank -> (None, '')."""
    if raw is None:
        return None, ''
    if isinstance(raw, bool):
        return None, str(raw)
    if isinstance(raw, (int, float)):
        return float(raw), str(raw)
    text = str(raw).strip()
    if not text:
        return None, ''
    try:
        return float(text.replace(',', '')), text
    except ValueError:
        return None, text


def check_availability(raw) -> Checked:
    """An availability percentage as written in the source."""
    value, text = _number(raw)
    if value is None and not text:
        return Checked(None, 'not_reported', f'{AVAILABILITY_COLUMN} is blank: not reported (not 0%).')
    if value is None:
        return Checked(None, 'invalid_availability', f'{AVAILABILITY_COLUMN} "{text}" is not a number.')
    if not 0 <= value <= 100:
        return Checked(None, 'availability_out_of_range', f'{AVAILABILITY_COLUMN} {text} is outside 0-100 (a percentage).')
    return Checked(value)


def check_outage(raw) -> Checked:
    """Daily outage minutes as written in the source."""
    value, text = _number(raw)
    if value is None and not text:
        return Checked(None, 'not_reported', 'Blank: not reported (not 0 minutes).')
    if value is None:
        return Checked(None, 'invalid_value', f'"{text}" is not a number.')
    if not 0 <= value <= MINUTES_PER_DAY:
        return Checked(None, 'outage_out_of_range', f'Outage {text} minutes is outside 0-{MINUTES_PER_DAY}.')
    return Checked(value)


def outage_from_availability(availability: float) -> float:
    if not 0 <= availability <= 100:
        raise ValueError('Availability must be between 0 and 100.')
    return MINUTES_PER_DAY * (1 - availability / 100)


def availability_from_outage(outage: float) -> float:
    if not 0 <= outage <= MINUTES_PER_DAY:
        raise ValueError(f'Outage must be between 0 and {MINUTES_PER_DAY} minutes.')
    return 100 * (1 - outage / MINUTES_PER_DAY)


def month_bounds(month: date) -> tuple[date, date]:
    return month.replace(day=1), month.replace(day=calendar.monthrange(month.year, month.month)[1])


def om_effective_from(om_start_date: date | None, month: date) -> date | None:
    """First O&M Start day of the site in the month; None when it is not O&M Start in that month (or has no date)."""
    start, end = month_bounds(month)
    if om_start_date is None or om_start_date > end:
        return None
    return max(om_start_date, start)


def om_start_date_issue(om_start_date: date | None, om_start_raw: str) -> str:
    """'' when the matrix has a readable date; 'invalid' when it has text that is not a date; 'missing' when blank."""
    return date_issue(om_start_date, om_start_raw)


def date_issue(value: date | None, raw: str) -> str:
    if value is not None:
        return ''
    return 'invalid' if (raw or '').strip() else 'missing'


def on_air_effective_from(on_air_date: date | None, month: date) -> date | None:
    """First On-Air day of the site in the month (the O&M rule applied to the Site On-Air Date)."""
    return om_effective_from(on_air_date, month)


WEEKS = ((1, 'Week 1', 1, 7), (2, 'Week 2', 8, 14), (3, 'Week 3', 15, 21), (4, 'Week 4', 22, None))  # None = month end


def weeks(month: date) -> list[tuple[str, date, date]]:
    """(label, first day, last day) of the month's four weeks; Week 4 ends on the month's last day."""
    start, end = month_bounds(month)
    return [(label, start.replace(day=a), end if b is None else start.replace(day=b)) for _n, label, a, b in WEEKS]


def mtd_dates(dates_with_data, month: date, until: date | None = None) -> list[date]:
    """MTD dates: from the 1st, every consecutive date with data, stopping before the first date without data
    (and at ``until`` when given)."""
    have = set(dates_with_data)
    start, end = month_bounds(month)
    end = min(end, until) if until else end
    out, day = [], start
    while day <= end and day in have:
        out.append(day)
        day = date.fromordinal(day.toordinal() + 1)
    return out
