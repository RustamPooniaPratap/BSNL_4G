"""Read an RCA workbook (Date, Project, Circle, Site ID, ..., RCA) into validated rows.

No database access. The data sheet is found by its header (for example "Sheet1" of a plain RCA file, or
"RCA Backup" of the Daily RCA Compilation, whose header is on row 2 and whose "Sheet1" is a pivot table);
columns are found by header text. Values are trimmed but otherwise kept as written; normalised companions
(project, circle code, ``*_key``) are added for filtering only. Every problem is reported with its Excel row;
rows with errors are rejected, never repaired.

A site can have several RCA rows on one date (separate outages). Each row gets an ``occurrence``: its rank among
that site's rows of the date, ordered by cause and outage, so the rank does not depend on the row order of the
file. (reporting date, project, site, occurrence) identifies a record. A row identical to an earlier one in
every column is a duplicate and rejected.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

from openpyxl import load_workbook

SHEET_NAME = 'Sheet1'  # the usual data sheet; any sheet with the RCA header is accepted
HEADER_SEARCH_ROWS = 10
MINUTES_PER_DAY = 1440
# Header text (case and spaces ignored) -> field.
COLUMNS = {
    'date': 'reporting_date', 'project': 'project_raw', 'circle': 'circle_raw', 'site id': 'site_id',
    'site name': 'site_name', 'oa': 'oa', 'ba': 'ba', 'o&m start (yes/no)': 'om_start_raw', 'outage min.': 'outage_minutes',
    'final bucket': 'final_bucket', 'bucket - 2': 'bucket_2', 'rca': 'rca_text',
}
REQUIRED = ('date', 'project', 'circle', 'site id', 'outage min.', 'final bucket', 'bucket - 2', 'rca')
# Project labels -> the dashboard's report types. "4G Satu" is a shortened label: mapped, but flagged for confirmation.
PROJECTS = {'4g satu': '4G Saturation', '4g satu.': '4G Saturation', '4g saturation': '4G Saturation', 'lwe': 'LWE'}
PROJECTS_TO_CONFIRM = {'4g satu', '4g satu.'}
# Circle names -> the dashboard's circle codes (the codes themselves are accepted too).
CIRCLES = {
    'odisha': 'OD', 'orissa': 'OD', 'rajasthan': 'RJ', 'madhya pradesh': 'MP', 'jharkhand': 'JH', 'bihar': 'BH',
    'chhattisgarh': 'CG', 'chhatisgarh': 'CG', 'chattisgarh': 'CG', 'chattishgarh': 'CG', 'chhattishgarh': 'CG', 'uttar pradesh': 'UP', 'west bengal': 'WB', 'andhra pradesh': 'AP', 'telangana': 'TL',
    'maharashtra': 'MH',
}
CIRCLE_CODES = set(CIRCLES.values())
PLACEHOLDERS = {'', '-', '--', 'na', 'n/a', '#n/a', 'nil', 'null', 'none', '0'}
MAX_EXAMPLES = 20


class ParseError(ValueError):
    """The file cannot be read as an RCA workbook (no Sheet1 or missing columns)."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def site_key(site_id: str) -> str:
    return re.sub(r'\s+', ' ', site_id.strip()).upper()


def text_key(value: str) -> str:
    """Case and spacing ignored; blank and placeholders ("-") give "" (unclassified). Spelling is not changed."""
    key = re.sub(r'\s+', ' ', (value or '').strip()).casefold()
    return '' if key in PLACEHOLDERS else key


def is_placeholder(value: str) -> bool:
    return text_key(value) == ''


def _text(value) -> str:
    if value is None:
        return ''
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def _date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool) and 30000 < value < 80000:
        return (datetime(1899, 12, 30) + timedelta(days=int(value))).date()  # Excel date serial
    text = _text(value)
    for fmt in ('%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y', '%d.%m.%Y', '%d-%b-%Y', '%d-%b-%y'):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _number(value) -> tuple[float | None, bool]:
    """(value, valid). Blank is (None, True): not reported, never 0."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, True
    if isinstance(value, bool):
        return None, False
    if isinstance(value, (int, float)):
        return float(value), True
    try:
        return float(str(value).strip().replace(',', '')), True
    except ValueError:
        return None, False


def _header(value) -> str:
    return re.sub(r'\s+', ' ', _text(value)).casefold()


def _data_sheet(book, filename: str) -> tuple[str, int, list]:
    """(sheet name, 0-based header row, rows) of the one sheet whose header has every required column."""
    found, partial = [], []
    for ws in book.worksheets:
        rows = list(ws.iter_rows(values_only=True))
        for at, row in enumerate(rows[:HEADER_SEARCH_ROWS]):
            headers = {_header(h) for h in row or ()}
            if all(name in headers for name in REQUIRED):
                found.append((ws.title, at, rows))
                break
            if 'site id' in headers:
                partial.append((ws.title, [name for name in REQUIRED if name not in headers]))
    if len(found) > 1:
        names = ', '.join(f'"{name}"' for name, _, _ in found)
        raise ParseError(f'{filename} has more than one sheet with RCA records ({names}). Upload a workbook with one RCA data sheet.')
    if found:
        return found[0]
    labels = {'date': 'Date', 'project': 'Project', 'circle': 'Circle', 'site id': 'Site ID', 'outage min.': 'Outage Min.',
              'final bucket': 'Final Bucket', 'bucket - 2': 'Bucket - 2', 'rca': 'RCA'}
    if partial:
        name, missing = partial[0]
        raise ParseError(f'The "{name}" sheet is missing required columns: {", ".join(labels[m] for m in missing)}.')
    raise ParseError(f'No sheet of {filename} has the RCA columns ({", ".join(labels.values())}) in its first {HEADER_SEARCH_ROWS} rows '
                     f'(sheets: {", ".join(book.sheetnames)}).')


def _number_occurrences(rows: list[dict]) -> None:
    """Rank each row among the rows of its site and date (by cause, then outage, then Excel row)."""
    groups: dict[tuple, list[dict]] = {}
    for row in rows:
        groups.setdefault((row['reporting_date'], row['project'], row['site_key']), []).append(row)
    for group in groups.values():
        group.sort(key=lambda r: (r['final_bucket_key'], r['bucket_2_key'], r['rca_key'],
                                  -1 if r['outage_minutes'] is None else r['outage_minutes'], r['source_row']))
        for n, row in enumerate(group, start=1):
            row['occurrence'] = n


def parse(path: Path, filename: str, *, period: tuple[date, date] | None = None, projects: set[str] | None = None,
          known_sites: dict[tuple[str, str], str] | None = None) -> dict:
    """Validated rows and a report: counts, issues (with Excel rows) and the distinct source labels.

    For an upload with report details the caller also passes what the rows must match: a date no later than the
    end of ``period`` (first, last day), a project of ``projects`` and a site of ``known_sites`` ((project, site
    key) -> circle in the Up-Time Report). A row that does not match is rejected. Rows dated before the period are
    kept and marked ``earlier_date``: the Daily RCA Compilation is cumulative and repeats the earlier days.
    """
    try:
        book = load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:  # not an xlsx, or a damaged file
        raise ParseError(f'{filename} could not be opened as an Excel workbook ({exc.__class__.__name__}).') from exc
    try:
        sheet, header_at, raw_rows = _data_sheet(book, filename)
    finally:
        book.close()  # read-only mode keeps the file open otherwise

    header_row = raw_rows[header_at]
    headers = [_header(h) for h in header_row]
    index = {field: headers.index(name) for name, field in COLUMNS.items() if name in headers}
    unknown_columns = [_text(h) for h, key in zip(header_row, headers) if key and key not in COLUMNS]

    issues: list[dict] = []
    rows: list[dict] = []
    seen: dict[tuple, int] = {}  # every column as read -> first Excel row, to find exact duplicates
    trimmed = 0
    blank_rows = 0

    def issue(severity, code, row, site_id, message):
        issues.append({'severity': severity, 'code': code, 'row': row, 'site_id': site_id, 'message': message})

    for offset, raw in enumerate(raw_rows[header_at + 1:], start=header_at + 2):
        if raw is None or all(v is None or _text(v) == '' for v in raw):
            blank_rows += 1
            continue
        cell = lambda field: raw[index[field]] if field in index and index[field] < len(raw) else None  # noqa: E731
        values = {field: _text(cell(field)) for field in COLUMNS.values() if field not in ('reporting_date', 'outage_minutes')}
        trimmed += sum(1 for field in values if isinstance(cell(field), str) and cell(field) != cell(field).strip())
        site_id = values['site_id']
        errors = []

        day = _date(cell('reporting_date'))
        if day is None:
            errors.append(('invalid_date', f'Date "{_text(cell("reporting_date"))}" is not a valid date.'))
        if not site_id:
            errors.append(('missing_site_id', 'Site ID is blank.'))
        project = PROJECTS.get(values['project_raw'].casefold())
        if project is None:
            errors.append(('unknown_project', f'Project "{values["project_raw"]}" is not 4G Saturation or LWE.'))
        circle_raw = values['circle_raw']
        circle = CIRCLES.get(circle_raw.casefold()) or (circle_raw.upper() if circle_raw.upper() in CIRCLE_CODES else None)
        if circle is None:
            errors.append(('unknown_circle', f'Circle "{circle_raw}" is not a known circle.'))
        outage, valid = _number(cell('outage_minutes'))
        if not valid:
            errors.append(('invalid_outage', f'Outage Min. "{_text(cell("outage_minutes"))}" is not a number.'))
        elif outage is not None and outage < 0:
            errors.append(('negative_outage', f'Outage Min. {outage:g} is negative.'))

        if period and day and day > period[1]:
            errors.append(('after_reporting_period', f'Date {day.isoformat()} is after the reporting date ({period[1].isoformat()}).'))
        if projects is not None and project and project not in projects:
            errors.append(('outside_project_scope', f'Project {project} is outside the upload\'s project scope ({" and ".join(sorted(projects))}).'))
        uptime_circle = None
        if known_sites is not None and project and site_id:
            uptime_circle = known_sites.get((project, site_key(site_id)))
            if uptime_circle is None:
                errors.append(('unknown_site', f'Site ID is not in the Up-Time Report for {project}.'))

        key = tuple(_text(v) for v in raw)
        if key in seen:
            errors.append(('duplicate_row', f'Identical in every column to Excel row {seen[key]}.'))

        if errors:
            for code, message in errors:
                issue('error', code, offset, site_id, message)
            continue
        seen[key] = offset

        if uptime_circle and circle and uptime_circle != circle:
            issue('warning', 'circle_differs_from_uptime', offset, site_id,
                  f'The Up-Time Report lists this site under {uptime_circle}, the file under {circle}: kept as written.')
        if outage is None:
            issue('warning', 'blank_outage', offset, site_id, 'Outage Min. is blank: kept as not recorded (not 0).')
        elif outage > MINUTES_PER_DAY:
            issue('warning', 'outage_over_day', offset, site_id, f'Outage Min. {outage:g} is more than one day (1,440 min).')
        om = values['om_start_raw'].casefold()
        om_start = True if om == 'yes' else False if om == 'no' else None
        if om_start is None:
            issue('warning', 'om_start_unrecognised', offset, site_id, f'O&M Start "{values["om_start_raw"]}" is not Yes or No: kept as written.')
        for field, label in (('final_bucket', 'Final Bucket'), ('bucket_2', 'Bucket - 2'), ('rca_text', 'RCA')):
            if is_placeholder(values[field]):
                issue('info', f'unclassified_{field}', offset, site_id,
                      f'{label} is "{values[field] or "blank"}": counted as unclassified, not as a root cause.')

        rows.append({
            **values,
            'reporting_date': day.isoformat(), 'project': project, 'circle': circle, 'site_key': site_key(site_id),
            'om_start': om_start, 'outage_minutes': None if outage is None else round(outage, 4),
            'final_bucket_key': text_key(values['final_bucket']), 'bucket_2_key': text_key(values['bucket_2']),
            'rca_key': text_key(values['rca_text']), 'source_row': offset,
            'earlier_date': bool(period) and day < period[0],
        })

    _number_occurrences(rows)
    projects_raw = Counter(r['project_raw'] for r in rows)
    to_confirm = sorted(p for p in projects_raw if p.casefold() in PROJECTS_TO_CONFIRM)
    for label in to_confirm:
        issue('info', 'project_label_to_confirm', None, '',
              f'Project "{label}" ({projects_raw[label]:,} rows) is read as 4G Saturation; the source value is kept. Please confirm this label.')
    if trimmed:
        issue('info', 'whitespace_trimmed', None, '', f'{trimmed} values had leading or trailing spaces; they were trimmed.')

    variants = {}
    for field in ('final_bucket', 'bucket_2', 'om_start_raw'):
        groups: dict[str, set] = {}
        for r in rows:
            groups.setdefault(text_key(r[field]) if field != 'om_start_raw' else r[field].casefold(), set()).add(r[field])
        variants[field] = [sorted(v) for k, v in groups.items() if k and len(v) > 1]

    severities = Counter(i['severity'] for i in issues)
    return {
        'rows': rows,
        'report': {
            'filename': filename, 'sheet': sheet, 'header_row': header_at + 1,
            'sites_with_several_rows': sum(1 for r in rows if r['occurrence'] == 2),
            'rows_read': len(rows) + len({i['row'] for i in issues if i['severity'] == 'error'}),
            'valid_rows': len(rows),
            'rejected_rows': len({i['row'] for i in issues if i['severity'] == 'error'}),
            'blank_rows': blank_rows,
            'unknown_columns': unknown_columns,
            'dates': dict(sorted(Counter(r['reporting_date'] for r in rows).items())),
            'projects': dict(Counter(r['project'] for r in rows)),
            'projects_raw': dict(projects_raw),
            'circles': dict(sorted(Counter(f'{r["project"]}|{r["circle"]}' for r in rows).items())),
            'circle_names': dict(sorted(Counter(f'{r["circle_raw"]} -> {r["circle"]}' for r in rows).items())),
            'distinct_sites': len({(r['project'], r['site_key']) for r in rows}),
            'outage_minutes': round(sum(r['outage_minutes'] or 0 for r in rows), 2),
            'final_buckets': dict(Counter(r['final_bucket'] for r in rows).most_common()),
            'bucket_2': dict(Counter(r['bucket_2'] for r in rows).most_common()),
            'distinct_rca': len({r['rca_key'] for r in rows if r['rca_key']}),
            'label_variants': variants,
            'severity_counts': {k: severities.get(k, 0) for k in ('error', 'warning', 'info')},
            'issue_counts': dict(Counter(i['code'] for i in issues)),
            'issues': issues[:MAX_EXAMPLES * 10],
            'all_issues': issues,
        },
    }
