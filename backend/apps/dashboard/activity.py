"""On-Air and O&M Start activity per month, from the escalation matrix in Data/reference.

The Master workbook only has month-end flags (On-Air today; "O&M Start - <month>" for some months), so
it cannot say when a site went On-Air or started O&M. The escalation matrix ("Consolidated Escalation
Matrix _<month>.xlsx", sheet "Raw Data") records a Site On Air Date and an O&M Start Date per site.
Sites are counted in the month of their date. Only Entity, Circle, Site ID and the two dates are read
(the file also holds contact details, which are not used).

A month the file does not cover yet (its latest date is before the month starts) is reported as not
available, never as 0. The file is never modified and is re-read when it changes.
"""
from __future__ import annotations

import calendar
import re
import threading
from datetime import date, datetime
from pathlib import Path

from django.conf import settings
from openpyxl import load_workbook

FILE_PATTERN = '*Escalation Matrix*.xlsx'
SHEET = 'Raw Data'
ENTITIES = {'4g saturation': '4G Saturation', 'lwe': 'LWE'}  # VI-HPSC / Sterlite rows are not dashboard sites
CIRCLES = {
    'odisha': 'OD', 'orissa': 'OD', 'rajasthan': 'RJ', 'madhya pradesh': 'MP', 'jharkhand': 'JH', 'bihar': 'BH',
    'chhattisgarh': 'CG', 'uttar pradesh': 'UP', 'west bengal': 'WB', 'andhra pradesh': 'AP', 'telangana': 'TL',
    'maharashtra': 'MH',
}
KINDS = {'on_air': 'Site On Air Date', 'om_start': 'O&M Start Date'}

_lock = threading.Lock()
_cache: dict = {'key': None, 'value': None}


class ActivityUnavailable(Exception):
    pass


def source_file() -> Path | None:
    folder = Path(settings.DATA_DIR) / 'reference'
    files = [p for p in folder.glob(FILE_PATTERN) if not p.name.startswith('~$')] if folder.is_dir() else []
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def _as_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None  # blank, "NO", "-": no date recorded


def _read(path: Path) -> dict:
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        if SHEET not in book.sheetnames:
            raise ActivityUnavailable(f'{path.name} has no "{SHEET}" sheet.')
        rows = book[SHEET].iter_rows(values_only=True)
        header, records = None, []
        for row in rows:
            cells = [str(v).strip() if v is not None else '' for v in row]
            if header is None:
                if 'BSNL Site ID' in cells:
                    header = {name: i for i, name in enumerate(cells) if name}
                    missing = [c for c in ('Entity', 'Circle Name', 'BSNL Site ID', *KINDS.values()) if c not in header]
                    if missing:
                        raise ActivityUnavailable(f'{path.name} ({SHEET}) is missing columns: {", ".join(missing)}.')
                continue
            get = lambda name: row[header[name]] if header[name] < len(row) else None  # noqa: E731
            entity = ENTITIES.get(str(get('Entity') or '').strip().casefold())
            site = str(get('BSNL Site ID') or '').strip()
            if not entity or not site:
                continue
            circle_raw = re.sub(r'\s+', ' ', str(get('Circle Name') or '')).strip()
            records.append({
                'report_type': entity, 'circle': CIRCLES.get(circle_raw.casefold(), circle_raw.upper()),
                **{kind: _as_date(get(column)) for kind, column in KINDS.items()},
            })
    finally:
        book.close()  # read-only mode keeps the file open otherwise
    if header is None:
        raise ActivityUnavailable(f'{path.name} ({SHEET}) has no "BSNL Site ID" header row.')
    latest = {kind: max((r[kind] for r in records if r[kind]), default=None) for kind in KINDS}
    return {'file': path.name, 'records': records, 'latest': latest}


def _load() -> dict:
    path = source_file()
    if path is None:
        raise ActivityUnavailable(f'No escalation matrix matching "{FILE_PATTERN}" in Data/reference.')
    key = (str(path), path.stat().st_mtime_ns)
    with _lock:
        if _cache['key'] != key:
            _cache.update(key=key, value=_read(path))
        return _cache['value']


def _month_start(value: date, back: int = 0) -> date:
    month = value.month - back
    year = value.year + (month - 1) // 12
    return date(year, (month - 1) % 12 + 1, 1)


def monthly_activity(month: date, report_type: str | None = None, circle: str | None = None) -> dict:
    """Sites that went On-Air / started O&M in ``month`` and the month before, for the filter."""
    data = _load()
    records = [r for r in data['records'] if (not report_type or r['report_type'] == report_type) and (not circle or r['circle'] == circle)]
    this, last = _month_start(month), _month_start(month, 1)

    def period(start: date, kind: str) -> dict:
        end = date(start.year, start.month, calendar.monthrange(start.year, start.month)[1])
        latest = data['latest'][kind]
        covered = latest is not None and latest >= start
        count = sum(1 for r in records if r[kind] and start <= r[kind] <= end) if covered else None
        return {'count': count, 'covered_to': min(latest, end).isoformat() if covered else None,
                'complete': covered and latest >= end}

    result = {}
    for kind in KINDS:
        now, before = period(this, kind), period(last, kind)
        result[kind] = {
            'this_month': now, 'last_month': before,
            'change': now['count'] - before['count'] if now['count'] is not None and before['count'] is not None else None,
            'latest_date': data['latest'][kind].isoformat() if data['latest'][kind] else None,
        }
    return {
        'source': data['file'], 'sites': len(records),
        'month': {'key': this.strftime('%Y-%m'), 'label': this.strftime('%b-%y')},
        'previous_month': {'key': last.strftime('%Y-%m'), 'label': last.strftime('%b-%y')},
        **result,
    }
