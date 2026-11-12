"""Reader of a day-wise outage workbook (e.g. "LWE Uptime Report day wise", sheet "Day Wise Outage"): one row per site,
a run of date columns with daily outage minutes and, optionally, a second run of the same dates with the daily uptime
fraction. Parsing only; the import into the data layer is sitedata.uptime_master.

- Columns are found by header text. The first run of date headers is outage minutes, the second (only when it repeats
  exactly the same dates) the uptime fraction. Blank cells and placeholders are "not reported"; text that is not a
  number is invalid.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from openpyxl import load_workbook

from .uptime_report import _number, _pct, sha256

SHEET = 'Day Wise Outage'
ID_HEADERS = ('site id as per nirikshan', 'btsipid')  # the master's site ID column, in order of preference
MINUTES_PER_DAY = 1440
MAX_LISTED = 200


class DaywiseError(ValueError):
    """The file cannot be read as a day-wise outage sheet."""


def canonical_circle(name: str, project: str | None = None, resolver=None) -> str | None:
    """Circle code for a circle written as a code or a state name: Organization > Code Mapping, source "Day-wise outage
    report" (only established aliases; None when unknown)."""
    from apps.organization.services import AliasResolver
    return (resolver or AliasResolver('daywise_report')).resolve(name, project)


@dataclass
class Parsed:
    filename: str
    checksum: str
    sheet: str
    header_row: int
    id_column: str
    dates: list[date]
    has_uptime: bool
    rows: list[dict] = field(default_factory=list)  # {'row', 'site_id', 'circle_raw', 'days': {date: (outage, uptime_pct)}, 'invalid': [...]}
    file_totals: dict = field(default_factory=dict)  # row -> the sheet's own outage total for the month, when present


def _header(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return ' '.join(str(value).split()) if value is not None else ''


def _runs(headers: list) -> list[tuple[int, int]]:
    """Consecutive runs of date headers as (start, end) column ranges."""
    runs, start = [], None
    for i, h in enumerate(headers + ['']):
        if isinstance(h, date) and start is None:
            start = i
        elif not isinstance(h, date) and start is not None:
            runs.append((start, i))
            start = None
    return runs


def parse(path: Path, *, filename: str | None = None, sheet: str = SHEET) -> Parsed:
    try:
        wb = load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:  # not an xlsx, damaged, encrypted
        raise DaywiseError(f'The file cannot be opened as an Excel workbook ({type(exc).__name__}).') from exc
    try:
        if sheet not in wb.sheetnames:
            raise DaywiseError(f'No "{sheet}" sheet; found: {", ".join(wb.sheetnames)}.')
        grid = [list(r) for r in wb[sheet].iter_rows(values_only=True)]
    finally:
        wb.close()  # read-only workbooks keep the file open until closed
    for header_index, raw in enumerate(grid[:15]):
        headers = [_header(v) for v in raw]
        lower = [h.lower() if isinstance(h, str) else '' for h in headers]
        id_col = next((lower.index(name) for name in ID_HEADERS if name in lower), None)
        if id_col is not None and 'circle' in lower:
            break
    else:
        raise DaywiseError('No header row with "Circle" and a site ID column ("Site ID as per Nirikshan" or "btsIpId").')
    runs = _runs(headers)
    if not runs:
        raise DaywiseError('No date columns in the header row.')
    o_start, o_end = runs[0]
    dates = headers[o_start:o_end]
    if len(set(dates)) != len(dates):
        raise DaywiseError('The daily date columns repeat a date.')
    u_run = next((r for r in runs[1:] if headers[r[0]:r[1]] == dates), None)
    circle_col = lower.index('circle')
    # The month's own outage total: the "Outage Min" column before the "<Mon>'YY MTD" uptime column of the dates' month.
    month_total_col = None
    for i, h in enumerate(headers[:o_start]):
        if isinstance(h, str) and h.lower() == 'outage min' and i + 1 < len(headers):
            nxt = headers[i + 1]
            if isinstance(nxt, str) and dates[0].strftime('%b').lower() in nxt.lower() and str(dates[0].year)[2:] in nxt:
                month_total_col = i
    parsed = Parsed(filename=filename or path.name, checksum=sha256(path), sheet=sheet, header_row=header_index + 1,
                    id_column=headers[id_col], dates=list(dates), has_uptime=u_run is not None)
    for offset, raw in enumerate(grid[header_index + 1:], start=header_index + 2):
        if not any(v not in (None, '') for v in raw):
            continue
        cells = list(raw) + [None] * (len(headers) - len(raw))
        site_id = '' if cells[id_col] is None else str(cells[id_col]).strip()
        days, invalid = {}, []
        for k, day in enumerate(dates):
            outage, problem = _number(cells[o_start + k])
            if problem is not None:
                invalid.append((day, problem))
                continue
            if outage is None:
                continue  # not reported: nothing is written, never zero
            uptime = _number(cells[u_run[0] + k])[0] if u_run else None
            days[day] = (outage, _pct(uptime))
        parsed.rows.append({'row': offset, 'site_id': site_id, 'circle_raw': '' if cells[circle_col] is None else str(cells[circle_col]).strip(),
                            'days': days, 'invalid': invalid})
        if month_total_col is not None:
            parsed.file_totals[offset] = _number(cells[month_total_col])[0]
    return parsed


