"""Read an RCA workbook (Date, Project, Circle, Site ID, ..., RCA) into validated rows.

Circle names and codes resolve through the Organization's RCA workbook aliases (read once per file); otherwise no
database access. The data sheet is found by its header (for example "Sheet1" of a plain RCA file, or
"RCA Backup" of the Daily RCA Compilation, whose header is on row 2 and whose "Sheet1" is a pivot table);
columns are found by header text. Values are trimmed but otherwise kept as written: Final Bucket and Sub Bucket are
validated against the approved taxonomy (apps.rca.taxonomy, spaces and case ignored) and never renamed or corrected;
normalised companions (project, circle code, ``*_key``) are added for filtering only. Every problem is reported with its Excel row;
rows with errors are rejected, never repaired.

Validation priorities (business rules of 4 Nov 2026):

1. Duplicates (mandatory). A record is identified by Site ID (with its project), Reporting Date, Final Bucket and Sub
   Bucket (``duplicate_key``). A site can have several records on one date when the Final Bucket or Sub Bucket differs.
   A later row with the same four values is a ``duplicate_record`` and rejected, even when its RCA description or
   Outage Min. differ (they are not part of the key). A blank Sub Bucket is a value: two rows with the same site, date,
   Final Bucket and a blank Sub Bucket are duplicates. Buckets are compared as uploaded, ignoring case and
   spacing (``text_key``); placeholders ("-") count as blank. Each rejection names the site and both Excel rows.
2. Final Bucket (highest priority). It must be one of the 10 approved Final Buckets (taxonomy.APPROVED). A blank or
   unapproved value is an error, reported with its value, row count and example rows; it is never renamed, remapped or
   discarded. The importer refuses a file with any such row (``final_bucket_file_error``).
3. Sub Bucket (Bucket - 2), validated against the row's Final Bucket. An approved Sub Bucket of another Final Bucket
   only is a classification mismatch and rejects the row (``sub_bucket_classification_mismatch``). A blank value, or one
   that is not an approved Sub Bucket of any Final Bucket, is a warning only; the value is kept as written.
4. RCA description, no priority. A blank or placeholder description is a note only; descriptions are never classified
   here.
5. Basic integrity (date, project, circle, Site ID, Outage Min., report scope) rejects the row; an outage over one day
   is a separate warning and the value is kept.

The importer matches stored records by the same key (importer._identity), so preview and import apply one rule.
``occurrence`` ranks a site's rows of a date by Final Bucket and Sub Bucket; the importer numbers new records after the
ones already stored.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

from openpyxl import load_workbook

from . import taxonomy

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
# Circle names and codes -> the dashboard's circle codes: Organization > Code Mapping, source "RCA workbook".
ALIAS_SOURCE = 'rca_workbook'
PLACEHOLDERS = {'', '-', '--', 'na', 'n/a', '#n/a', 'nil', 'null', 'none', '0'}
MAX_EXAMPLES = 20
EXAMPLE_ROWS = 5  # Excel rows listed per reported value
FINAL_BUCKET_ERRORS = ('missing_final_bucket', 'final_bucket_not_approved')


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


def duplicate_key(reporting_date: str, project: str, site: str, final_bucket_key: str, bucket_2_key: str) -> tuple:
    """The identity of an RCA record: site (project, Site ID key), reporting date, Final Bucket and Sub Bucket keys.

    Not the RCA description and not the outage: rows that differ only there are the same record. A blank Sub Bucket
    ("" key, also for placeholders) is a value of its own.
    """
    return (reporting_date, project, site, final_bucket_key, bucket_2_key)


def row_key(row: dict) -> tuple:
    return duplicate_key(row['reporting_date'], row['project'], row['site_key'], row['final_bucket_key'], row['bucket_2_key'])


def repeated_keys(rows: list[dict]) -> list[tuple]:
    """Keys that occur more than once among the rows (empty for rows validated with the duplicate rule)."""
    return [k for k, n in Counter(row_key(r) for r in rows).items() if n > 1]


def final_bucket_file_error(report: dict) -> str:
    """Why the file cannot be imported because of its Final Buckets (blank when every row has an approved one)."""
    problems = report.get('final_bucket_problems') or []
    if not problems:
        return ''
    n = sum(p['rows'] for p in problems)
    values = ', '.join(f'"{p["value"] or "blank"}" ({p["rows"]:,})' for p in problems[:10])
    return (f'{n:,} rows have a missing or unapproved Final Bucket ({values}). Every RCA record needs one of the approved '
            'Final Buckets; correct the workbook and upload it again. Nothing can be imported.')


def parse(path: Path, filename: str, *, period: tuple[date, date] | None = None, projects: set[str] | None = None,
          known_sites: dict[tuple[str, str], str] | None = None, circle: str | None = None, single_date: bool = False) -> dict:
    """Validated rows and a report: counts, issues (with Excel rows) and the distinct source labels.

    For an upload with report details the caller also passes what the rows must match: a date no later than the
    end of ``period`` (first, last day), a project of ``projects`` and a site of ``known_sites`` ((project, site
    key) -> circle in the Up-Time Report). A row that does not match is rejected. Rows dated before the period are
    kept and marked ``earlier_date``: the Daily RCA Compilation is cumulative and repeats the earlier days.

    A circle upload also passes ``circle`` (rows of another circle, or of a site the Up-Time Report lists under another
    circle, are rejected) and ``single_date`` (a row of any date other than the reporting date is an ``other_date``
    error: the importer refuses such a file as a whole).
    """
    expected_circle = circle
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
    first_row: dict[tuple, tuple[int, tuple]] = {}  # duplicate_key -> (first Excel row, its values as read)
    duplicates: dict[tuple, dict] = {}  # duplicate_key -> the first row and the rejected later rows
    final_problems: dict[tuple, dict] = {}  # (Final Bucket as written, code) -> rows and example Excel rows
    sub_problems: dict[tuple, dict] = {}  # (Final Bucket, Bucket - 2 as written, code) -> rows and example Excel rows
    mismatches: dict[tuple, dict] = {}  # (Final Bucket, Sub Bucket of another Final Bucket) -> rows and example Excel rows
    trimmed = 0
    blank_rows = 0

    from apps.organization.services import AliasResolver
    circles = AliasResolver(ALIAS_SOURCE)
    first_row_site: dict[tuple, str] = {}
    classified: Counter = Counter()  # rows per classification status (taxonomy.STATUS_LABELS)

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
        circle = circles.resolve(circle_raw, project)
        if circle is None:
            errors.append(('unknown_circle', f'Circle "{circle_raw}" is not a known circle.'))
        outage, valid = _number(cell('outage_minutes'))
        if not valid:
            errors.append(('invalid_outage', f'Outage Min. "{_text(cell("outage_minutes"))}" is not a number.'))
        elif outage is not None and outage < 0:
            errors.append(('negative_outage', f'Outage Min. {outage:g} is negative.'))

        if period and day and day > period[1]:
            errors.append(('after_reporting_period', f'Date {day.isoformat()} is after the reporting date ({period[1].isoformat()}).'))
        if single_date and period and day and day != period[0] and day <= period[1]:
            errors.append(('other_date', f'Date {day.isoformat()} is not the reporting date ({period[0].isoformat()}).'))
        if expected_circle and circle and circle != expected_circle:
            errors.append(('outside_circle', f'Circle {circle} is not the selected circle {expected_circle}.'))
        if projects is not None and project and project not in projects:
            errors.append(('outside_project_scope', f'Project {project} is outside the upload\'s project scope ({" and ".join(sorted(projects))}).'))
        uptime_circle = None
        if known_sites is not None and project and site_id:
            uptime_circle = known_sites.get((project, site_key(site_id)))
            if uptime_circle is None:
                errors.append(('unknown_site', f'Site ID is not in the Up-Time Report for {project}.'))
            elif expected_circle and uptime_circle != expected_circle:
                errors.append(('site_of_other_circle', f'The Up-Time Report lists this {project} site under {uptime_circle}, not {expected_circle}.'))

        # 2. Final Bucket: one of the approved major categories; blank or anything else is an error, kept as written.
        resolved = taxonomy.resolve(values['final_bucket'], values['bucket_2'])
        if taxonomy.is_blank(values['final_bucket']):
            final_code = 'missing_final_bucket'
            errors.append((final_code, f'Final Bucket is "{values["final_bucket"] or "blank"}": every RCA record needs an approved Final Bucket.'))
        elif resolved.status == 'unapproved':
            final_code = 'final_bucket_not_approved'
            errors.append((final_code, f'Final Bucket "{values["final_bucket"]}" is not one of the approved Final Buckets: '
                                       'kept as written, not renamed or reassigned.'))
        else:
            final_code = None
        if final_code:
            entry = final_problems.setdefault((values['final_bucket'], final_code), {'rows': 0, 'examples': []})
            entry['rows'] += 1
            if len(entry['examples']) < EXAMPLE_ROWS:
                entry['examples'].append(offset)
        # 3. A Sub Bucket of another Final Bucket only (e.g. "SSA OFC" under BSNL Media) is a classification mismatch.
        if resolved.status == 'mismatch':
            errors.append(('sub_bucket_classification_mismatch',
                           f'Sub Bucket "{values["bucket_2"]}" belongs to {" / ".join(resolved.other_final_buckets)}, not to '
                           f'{resolved.final_bucket}: classification mismatch, the row is rejected (values kept as written).'))
            entry = mismatches.setdefault((resolved.final_bucket, values['bucket_2']), {'rows': 0, 'examples': [],
                                                                                         'belongs_to': list(resolved.other_final_buckets)})
            entry['rows'] += 1
            if len(entry['examples']) < EXAMPLE_ROWS:
                entry['examples'].append(offset)

        # 1. Duplicates: the same site, date, Final Bucket and Sub Bucket as an earlier row (description and outage ignored).
        if day and project and site_id:
            identity = duplicate_key(day.isoformat(), project, site_key(site_id), text_key(values['final_bucket']), text_key(values['bucket_2']))
            as_read = tuple(_text(v) for v in raw)
            if identity in first_row:
                first, first_values = first_row[identity]
                how = 'identical in every column' if as_read == first_values else 'the RCA description, outage or other columns differ'
                sub = values['bucket_2'] if not is_placeholder(values['bucket_2']) else 'blank'
                errors.append(('duplicate_record', f'Duplicate of Excel row {first}: same Site ID {site_id}, date {day.isoformat()}, '
                                                   f'Final Bucket "{values["final_bucket"] or "blank"}" and Sub Bucket "{sub}" ({how}). '
                                                   'This row is rejected.'))
                group = duplicates.setdefault(identity, {'site_id': first_row_site[identity], 'project': project,
                                                         'reporting_date': day.isoformat(), 'final_bucket': values['final_bucket'],
                                                         'sub_bucket': '' if is_placeholder(values['bucket_2']) else values['bucket_2'],
                                                         'first_row': first, 'rejected_rows': []})
                group['rejected_rows'].append(offset)
                group.setdefault('identical', 0)
                group['identical'] += as_read == first_values
            else:
                first_row[identity] = (offset, as_read)
                first_row_site[identity] = site_id

        if errors:
            for code, message in errors:
                issue('error', code, offset, site_id, message)
            continue

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
        # Final Bucket and Sub Bucket are stored as uploaded (trimmed); the taxonomy only classifies them.
        classified[taxonomy.count_status(resolved.status)] += 1
        # 3. Sub Bucket blank or not approved anywhere: a warning only (never blocks); the value is kept as written.
        sub_code = ('sub_bucket_missing' if taxonomy.is_blank(values['bucket_2'])
                    else 'sub_bucket_not_approved' if resolved.status == 'final_only' else None)
        if sub_code:
            entry = sub_problems.setdefault((values['final_bucket'], values['bucket_2'], sub_code), {'rows': 0, 'examples': []})
            entry['rows'] += 1
            if len(entry['examples']) < EXAMPLE_ROWS:
                entry['examples'].append(offset)
            issue('warning', sub_code, offset, site_id,
                  f'Bucket - 2 is blank under {values["final_bucket"]}: kept as not recorded; does not block the import.'
                  if sub_code == 'sub_bucket_missing' else
                  f'Bucket - 2 "{values["bucket_2"]}" is not an approved Sub Bucket of {values["final_bucket"]}: kept as written; '
                  'does not block the import.')
        # 4. RCA description: a note only; the description is kept as written and not classified here.
        if is_placeholder(values['rca_text']):
            issue('info', 'unclassified_rca_text', offset, site_id,
                  f'RCA is "{values["rca_text"] or "blank"}": kept as written, counted as unclassified; does not block the import.')

        rows.append({
            **values,
            'reporting_date': day.isoformat(), 'project': project, 'circle': circle, 'site_key': site_key(site_id),
            'om_start': om_start, 'outage_minutes': None if outage is None else round(outage, 4),
            'final_bucket_key': text_key(values['final_bucket']), 'bucket_2_key': text_key(values['bucket_2']),
            'rca_key': text_key(values['rca_text']), 'source_row': offset,
            'earlier_date': bool(period) and day < period[0],
        })

    # Rank of each record among its site's records of the date, by Final Bucket and Sub Bucket (unique per the key).
    by_site: dict[tuple, list[dict]] = {}
    for row in rows:
        by_site.setdefault((row['reporting_date'], row['project'], row['site_key']), []).append(row)
    for group in by_site.values():
        for n, row in enumerate(sorted(group, key=lambda r: (r['final_bucket_key'], r['bucket_2_key'])), start=1):
            row['occurrence'] = n

    classification_mismatches = [{'final_bucket': final, 'value': value, 'belongs_to': e['belongs_to'], 'rows': e['rows'],
                                  'example_rows': e['examples']}
                                 for (final, value), e in sorted(mismatches.items(), key=lambda kv: -kv[1]['rows'])]
    final_bucket_problems = [{'value': value, 'code': code, 'rows': e['rows'], 'example_rows': e['examples']}
                             for (value, code), e in sorted(final_problems.items(), key=lambda kv: -kv[1]['rows'])]
    sub_bucket_problems = [{'final_bucket': final, 'value': value, 'code': code, 'rows': e['rows'], 'example_rows': e['examples']}
                           for (final, value, code), e in sorted(sub_problems.items(), key=lambda kv: -kv[1]['rows'])]
    duplicate_groups = sorted(duplicates.values(), key=lambda g: g['first_row'])
    duplicate_rows = sum(len(g['rejected_rows']) for g in duplicate_groups)
    identical_rows = sum(g['identical'] for g in duplicate_groups)
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
            # 1. Rows rejected as duplicates of an earlier row (same site, date, Final Bucket and Sub Bucket), also those with
            # other errors; groups: distinct duplicated keys.
            'duplicates': {
                'rows': duplicate_rows, 'groups': len(duplicate_groups), 'sites': len({(g['project'], g['site_id'].upper()) for g in duplicate_groups}),
                'identical_rows': identical_rows, 'differing_rows': duplicate_rows - identical_rows,
                'examples': duplicate_groups[:MAX_EXAMPLES],
            },
            # 2. Missing or unapproved Final Bucket values (rows rejected; the file cannot be imported).
            'final_bucket_problems': final_bucket_problems,
            'final_bucket_error_rows': sum(p['rows'] for p in final_bucket_problems),
            # 3. Sub Buckets of another Final Bucket (rows rejected).
            'classification_mismatches': classification_mismatches,
            'classification_mismatch_rows': sum(p['rows'] for p in classification_mismatches),
            # 3. Sub Bucket warnings of valid rows (never block).
            'sub_bucket_warnings': {
                'rows': sum(p['rows'] for p in sub_bucket_problems),
                'missing_rows': sum(p['rows'] for p in sub_bucket_problems if p['code'] == 'sub_bucket_missing'),
                'not_approved_rows': sum(p['rows'] for p in sub_bucket_problems if p['code'] == 'sub_bucket_not_approved'),
                'values': sub_bucket_problems[:MAX_EXAMPLES * 5],
            },
            # 4. Valid rows whose RCA description is blank or a placeholder (never block).
            'rca_description_warnings': sum(1 for r in rows if not r['rca_key']),
            'outage_over_day_rows': sum(1 for i in issues if i['code'] == 'outage_over_day'),
            'sites_with_several_records': sum(1 for r in rows if r['occurrence'] == 2),
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
            # Rows by approved-classification status (taxonomy): approved pairs, approved Final Bucket only, not approved, blank.
            'classification': {k: classified.get(k, 0) for k in taxonomy.STATUS_LABELS},
            'severity_counts': {k: severities.get(k, 0) for k in ('error', 'warning', 'info')},
            'issue_counts': dict(Counter(i['code'] for i in issues)),
            'issues': issues[:MAX_EXAMPLES * 10],
            'all_issues': issues,
        },
    }
