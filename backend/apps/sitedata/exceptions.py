"""Exception reports: every record an upload does not import (rejected, unmatched, ambiguous) or flags for review, in
one format for every importer. The full list is written to a CSV per upload at preview
(settings.SITEDATA_EXCEPTION_DIR, default <DATA_DIR>/processed/sitedata/exceptions); the stored report keeps the counts,
examples and the file's path, relative to that directory (resolve() finds it on this server, including legacy absolute
paths of another machine by file name)."""
from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

from django.conf import settings

COLUMNS = ('upload', 'upload_kind', 'source_file', 'row', 'site_id', 'circle', 'report_date', 'identifier', 'value', 'code', 'severity', 'message', 'related')
REJECTED, UNMATCHED, REVIEW, INFO = 'rejected', 'unmatched', 'review', 'info'


def _as_written(value) -> str:
    """The original value as text: a whole number without '.0' (the parsers return numbers as floats), others in full."""
    if value is None:
        return ''
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def record(*, source_file: str, code: str, message: str, severity: str = REJECTED, row=None, site_id='', circle='', report_date=None,
           identifier='', value='', related='') -> dict:
    return {'source_file': source_file, 'row': row, 'site_id': site_id or '', 'circle': circle or '',
            'report_date': report_date.isoformat() if hasattr(report_date, 'isoformat') else (report_date or ''),
            'identifier': identifier or '', 'value': _as_written(value), 'code': code, 'severity': severity,
            'message': message, 'related': related or ''}


def exception_dir() -> Path:
    path = Path(getattr(settings, 'SITEDATA_EXCEPTION_DIR', '') or Path(settings.DATA_DIR) / 'processed' / 'sitedata' / 'exceptions')
    path.mkdir(parents=True, exist_ok=True)
    return path


def write(batch, items: list[dict]) -> str:
    """Write the upload's exception CSV; returns its path relative to exception_dir() ('' when there is nothing to
    report)."""
    if not items:
        return ''
    path = exception_dir() / f'upload-{batch.pk}-{batch.kind}-exceptions.csv'
    with open(path, 'w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for item in items:
            writer.writerow({**item, 'upload': batch.pk, 'upload_kind': batch.kind})
    return path.name


def resolve(stored: str) -> Path | None:
    """The exception CSV of a stored report reference on this server (None when the upload had nothing to report).
    The file may still be missing: check is_file()."""
    from .uploads import resolve_stored
    return resolve_stored(stored, exception_dir())


def summary(items: list[dict], limit: int = 50) -> dict:
    return {'total': len(items), 'by_code': dict(Counter(i['code'] for i in items)),
            'by_severity': dict(Counter(i['severity'] for i in items)), 'examples': items[:limit]}
