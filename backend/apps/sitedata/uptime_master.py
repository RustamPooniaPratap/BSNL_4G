"""Uptime Master import into the new data layer (approved 4 Nov 2026), for the two workbook formats in use.

Formats (detected by sheet name; a workbook with neither sheet is refused):
- "Up-Time Report" (e.g. "4G_LWE_Consolidated", "RJ, MP & OD - Uptime Report"): read by the existing parser
  (uptimedb.parser.parse_workbook). Header row with Circle, btsIpId, site columns, "O&M Start - <Mon-YY>" flags and
  a run of date columns with daily outage minutes. Some files have a Project column; the RJ, MP & OD report has none
  (it covers 4G Saturation only), so the uploader must state the project, as with the existing import. When the file
  does have a Project column and a project is stated, rows of another project are rejected. Its "O&M Start - <Mon-YY>"
  flags are not imported: they are only compared with the matrix O&M Start Date (reported).
- "Day Wise Outage" (e.g. "LWE Uptime Report day wise"): read by the existing day-wise parser (uptimedb.daywise.parse).
  Circle as a state name, "Site ID as per Nirikshan" (the master site ID; the numeric "Site ID" is a serial number and
  is not used), a run of date columns with daily outage minutes, then the same dates as uptime fractions. There is no
  Project column: the uploader states the project. Its undated "O&M Start" column is not used; its monthly
  "Outage Min" blocks are snapshots and are not imported.

Rules, the same for both formats:
- Sites are matched to the site master by BSNL Site ID. The workbook never creates a site and never changes an
  attribute the Consolidation Matrix holds (including the O&M Start Date); differences are reported and the matrix value
  is kept. A site not in the site master stays unmatched (no record, exception report) until it is added to the matrix. Columns only the
  Uptime Master has (EB, OD EB working status, Solar Logic Done Date) are stored as written (Up-Time Report only).
- Only the months in scope are imported: settings.SITEDATA_MASTER_DAILY_MONTHS when a deployment lists them, otherwise
  every month from settings.SITEDATA_DAILY_FROM (September 2026, the start of the new data layer) to the current month,
  so a new month's Uptime Master can be imported while the earlier monthly snapshots stay out.
- File-level duplicates are scoped to this importer: a file already committed into the new data layer is reported
  (already_imported); an import of the same file into the legacy uptimedb tables is listed for information only and
  never blocks this import. Record-level protection is daily.py's (one record per site, date and technology; source
  precedence; authorized corrections are never overwritten).
- Values follow the shared rules (rules.check_outage): a blank cell is "not reported" (no record, never 0, counted); a
  cell that is not a number, or outage outside 0-1,440 minutes, is rejected with its original value, never capped.
- A site on more than one row of the file is ambiguous: all of its rows are rejected (identical repeats in the
  day-wise sheet are one row plus counted duplicates).
- Rows the file itself cannot place (no site ID, no or unknown circle, unknown project) are rejected and listed.
- Daily values follow daily.py: first accepted value wins, a different later value is logged as a conflict.
Counts are site-days: received = accepted + duplicate + conflict + superseded + rejected + unmatched. Every rejected row and
site-day and every unmatched site is in the upload's exception report.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from openpyxl import load_workbook

from apps.accounts.audit import audit
from apps.uptimedb import daywise
from apps.uptimedb.parser import SHEET_NAME as UP_TIME_SHEET
from apps.uptimedb.parser import ParseError, parse_workbook

from . import daily, exceptions, rules, uploads
from .identifiers import key_of
from .models import Site, Technology, UploadBatch

KIND = UploadBatch.Kind.UPTIME_MASTER
UP_TIME_REPORT, DAY_WISE = 'up_time_report', 'day_wise_outage'
UPTIME_ONLY = {'eb': 'EB', 'od_eb_working_status': 'OD EB working status', 'solar_logic_done': 'Solar Logic Done Date'}
# Matrix attribute -> Up-Time Report field, compared (never written).
COMPARED = {'circle': 'circle', 'site_name': 'site_name', 'oa': 'oa', 'ba': 'ba', 'ci_name': 'ci_name', 'ie_name': 'ie_name', 'on_air': 'on_air'}
MAX_LISTED = 200


@dataclass
class SourceRow:
    row: int | None
    site_id: str
    project: str
    circle: str
    days: dict  # date -> outage minutes (a number as written)
    invalid: list  # (date, text as written) of cells that are not numbers
    blank_days: int = 0  # in-scope date cells left blank (not reported)
    om: dict = field(default_factory=dict)  # month -> (flag, raw)
    uptime_fields: dict | None = None  # None: the format has no such columns
    compare: dict = field(default_factory=dict)  # matrix field -> value in the file


@dataclass
class Source:
    format: str
    sheet: str
    rows: list = field(default_factory=list)
    rejected: list = field(default_factory=list)  # row-level rejections: {'row', 'site_id', 'code', 'message', 'site_days'}
    duplicate_site_days: int = 0
    notes: list = field(default_factory=list)
    months_in_file: list = field(default_factory=list)


def months_in_scope() -> set[date]:
    """The months whose daily values are imported (see the module notes)."""
    listed = getattr(settings, 'SITEDATA_MASTER_DAILY_MONTHS', None)
    if listed:
        return {date(int(t.split('-')[0]), int(t.split('-')[1]), 1) for t in listed}
    year, month = (int(x) for x in getattr(settings, 'SITEDATA_DAILY_FROM', '2026-09').split('-'))
    first, last = date(year, month, 1), timezone.localdate().replace(day=1)
    out = set()
    while first <= last:
        out.add(first)
        first = date(first.year + (first.month == 12), first.month % 12 + 1, 1)
    return out


def earlier_imports(checksum: str, exclude: int | None = None) -> dict:
    """Imports of the same file (by checksum): into the new data layer (this importer; a committed one makes the
    preview report already_imported) and into the legacy uptimedb tables (information only, another destination)."""
    from apps.uptimedb.models import DataImportBatch
    previous = (UploadBatch.objects.filter(kind=KIND, processing_status=UploadBatch.Processing.COMMITTED, checksum_sha256=checksum)
                .exclude(pk=exclude).order_by('committed_at').first())
    legacy = DataImportBatch.objects.filter(checksum_sha256=checksum, status=DataImportBatch.Status.COMMITTED).order_by('committed_at')
    return {
        'already_imported': {'batch': previous.pk, 'committed_at': previous.committed_at.isoformat()} if previous else None,
        'legacy_imports': [{'batch': b.pk, 'committed_at': b.committed_at.isoformat() if b.committed_at else None} for b in legacy],
    }


def detect_format(path: Path) -> tuple[str, list[str]]:
    try:
        book = load_workbook(path, read_only=True)
    except Exception as exc:  # not an xlsx, damaged, encrypted
        raise uploads.UploadRejected(f'The file cannot be opened as an Excel workbook ({type(exc).__name__}).') from exc
    try:
        names = list(book.sheetnames)
    finally:
        book.close()
    if UP_TIME_SHEET in names:
        return UP_TIME_REPORT, names
    if daywise.SHEET in names:
        return DAY_WISE, names
    raise uploads.UploadRejected(f'The workbook has neither an "{UP_TIME_SHEET}" nor a "{daywise.SHEET}" sheet (sheets: {", ".join(names)}).')


def _in_scope(day: date, scope: set[date]) -> bool:
    return day.replace(day=1) in scope


def read_up_time_report(path: Path, name: str, project: str | None, scope: set[date]) -> Source:
    try:
        parsed = parse_workbook(path, filename=name, default_project=project)
    except ParseError as exc:
        message = str(exc)
        if 'Project' in message and project is None:
            message += ' State the project of this file (4G Saturation or LWE) when uploading it.'
        raise uploads.UploadRejected(message) from exc
    source = Source(UP_TIME_REPORT, parsed.sheet, months_in_file=sorted(parsed.daily_months))
    # Non-numeric daily cells (the parser flags them and keeps them empty): rejected here, with their text.
    invalid_by_row = defaultdict(list)
    for issue in parsed.issues:
        if issue['code'] == 'non_numeric':
            try:
                day = date.fromisoformat(issue['message'][:10])
            except ValueError:
                continue  # a monthly snapshot column: not imported
            invalid_by_row[issue['row']].append((day, issue['message'].split("'")[1] if "'" in issue['message'] else ''))
        elif issue['severity'] == 'rejected':
            source.rejected.append({'row': issue['row'], 'site_id': issue['site_id'], 'code': issue['code'], 'message': issue['message'], 'site_days': 0})
    # A site ID on several rows: the parser keeps the first; here every row of that site is rejected.
    repeated = {key_of(i['site_id']) for i in parsed.issues if i['code'] == 'duplicate_key'}
    for (row_project, circle, key), site in parsed.sites.items():
        days_all = parsed.daily.get((row_project, circle, key), {})
        days = {d: v[0] for d, v in days_all.items() if _in_scope(d, scope) and v[0] is not None}
        invalid = [x for x in invalid_by_row.get(site['source_row'], []) if _in_scope(x[0], scope)]
        blank = sum(1 for d, v in days_all.items() if _in_scope(d, scope) and v[0] is None) - len(invalid)
        site_days = len(days) + len(invalid)
        if key in repeated:
            source.rejected.append({'row': site['source_row'], 'site_id': site['site_id'], 'code': 'duplicate_site',
                                    'message': 'The site ID is on more than one row of the file; none of its rows is imported.', 'site_days': site_days})
            continue
        if project and parsed.has_project_column and row_project != project:
            source.rejected.append({'row': site['source_row'], 'site_id': site['site_id'], 'code': 'not_stated_project',
                                    'message': f'Project {row_project}, but this upload was stated as {project}.', 'site_days': site_days})
            continue
        om = {m: (r['om_start'], r['om_start_raw']) for m, r in parsed.monthly.get((row_project, circle, key), {}).items()
              if m in scope and r.get('om_start_raw') is not None}
        source.rows.append(SourceRow(
            row=site['source_row'], site_id=site['site_id'], project=row_project, circle=circle, days=days, invalid=invalid, blank_days=max(blank, 0),
            om=om, uptime_fields={label: site.get(f) for f, label in UPTIME_ONLY.items() if site.get(f)},
            compare={f: site.get(src) for f, src in COMPARED.items()}))
    return source


def read_day_wise(path: Path, name: str, project: str | None, scope: set[date]) -> Source:
    if project is None:
        raise uploads.UploadRejected(f'The "{daywise.SHEET}" sheet has no Project column. State the project of this file (4G Saturation or LWE) when uploading it.')
    try:
        parsed = daywise.parse(path, filename=name)
    except daywise.DaywiseError as exc:
        raise uploads.UploadRejected(str(exc)) from exc
    source = Source(DAY_WISE, parsed.sheet, months_in_file=sorted({d.strftime('%Y-%m') for d in parsed.dates}))
    if not parsed.has_uptime:
        source.notes.append('No second run of the same dates (uptime fractions) was found; outage minutes are used as always.')
    header = _header_row(path, parsed.sheet, parsed.header_row)
    if 'o&m start' in header:
        source.notes.append('The "O&M Start" column has no month in its header and is not used: O&M Start comes from the matrix O&M Start Date.')
    from apps.organization.services import AliasResolver
    circles = AliasResolver('daywise_report')
    by_key = defaultdict(list)
    for r in parsed.rows:
        by_key[key_of(r['site_id'])].append(r)
    for key, rows in by_key.items():
        for r in rows:
            r['_days'] = {d: v[0] for d, v in r['days'].items() if _in_scope(d, scope)}
            r['_invalid'] = [x for x in r['invalid'] if _in_scope(x[0], scope)]
            r['_site_days'] = len(r['_days']) + len(r['_invalid'])
        if not key:
            for r in rows:
                source.rejected.append({'row': r['row'], 'site_id': '', 'code': 'missing_site_id', 'message': 'No site ID ("Site ID as per Nirikshan").', 'site_days': r['_site_days']})
            continue
        if len(rows) > 1:
            same = all((r['circle_raw'], r['_days'], r['_invalid']) == (rows[0]['circle_raw'], rows[0]['_days'], rows[0]['_invalid']) for r in rows[1:])
            if not same:
                for r in rows:
                    source.rejected.append({'row': r['row'], 'site_id': r['site_id'], 'code': 'duplicate_site',
                                            'message': f'The site ID is on {len(rows)} rows with different values; none of them is imported.', 'site_days': r['_site_days']})
                continue
            source.duplicate_site_days += sum(r['_site_days'] for r in rows[1:])
        r = rows[0]
        circle = daywise.canonical_circle(r['circle_raw'], project, circles) if r['circle_raw'] else None
        if circle is None:
            source.rejected.append({'row': r['row'], 'site_id': r['site_id'], 'code': 'unknown_circle',
                                    'message': f'Circle "{r["circle_raw"]}" is blank or not a known circle name.', 'site_days': r['_site_days']})
            continue
        in_scope_dates = [d for d in parsed.dates if _in_scope(d, scope)]
        source.rows.append(SourceRow(row=r['row'], site_id=r['site_id'], project=project, circle=circle, days=r['_days'], invalid=r['_invalid'],
                                     blank_days=len(in_scope_dates) - r['_site_days'], compare={'circle': circle}))
    return source


def _header_row(path: Path, sheet: str, row: int) -> set[str]:
    book = load_workbook(path, read_only=True)
    try:
        values = next(book[sheet].iter_rows(min_row=row, max_row=row, values_only=True), ())
    finally:
        book.close()
    return {' '.join(str(v).split()).casefold() for v in values if isinstance(v, str)}


def _same(a, b) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) == bool(b)
    return ' '.join(str(a or '').split()).casefold() == ' '.join(str(b or '').split()).casefold()


def analyse(path: Path, name: str, project: str | None = None) -> dict:
    if project is not None and project not in Technology.values:
        raise uploads.UploadRejected(f'Unknown project {project!r}; choose 4G Saturation or LWE.')
    scope = months_in_scope()
    fmt, sheets = detect_format(path)
    source = (read_up_time_report if fmt == UP_TIME_REPORT else read_day_wise)(path, name, project, scope)
    from .unmatched import site_lookup
    sites = site_lookup()  # master BSNL Site IDs, then Admin-approved alternate identifiers
    rejected = list(source.rejected)  # row-level
    cells_rejected = []  # site-day level
    unmatched, unmatched_days = [], 0
    differences, diff_examples = Counter(), []
    values, uptime_fields, om_differences = [], {}, []
    blank_days = 0

    def reject_row(r, code, message):
        rejected.append({'row': r.row, 'site_id': r.site_id, 'code': code, 'message': message, 'site_days': len(r.days) + len(r.invalid)})

    for r in source.rows:
        site = sites.get(key_of(r.site_id))
        blank_days += r.blank_days
        if site is None:
            # Pending: kept in the staged copy and listed with its dates; never a site, never a KPI (unmatched.py).
            unmatched.append((r, len(r.days) + len(r.invalid)))
            unmatched_days += len(r.days) + len(r.invalid)
            continue
        if site.reporting_scope != Site.Scope.DASHBOARD:
            reject_row(r, 'outside_scope', f'{site.bsnl_site_id} ({site.entity}) is outside the dashboard reporting scope.')
            continue
        if site.technology != r.project:
            reject_row(r, 'technology_mismatch', f'{r.project} in the file, {site.technology} in the site master.')
            continue
        for f, value in r.compare.items():
            if not _same(getattr(site, f), value):
                differences[f] += 1
                if len(diff_examples) < 30:
                    diff_examples.append({'site_id': site.bsnl_site_id, 'field': f, 'matrix': getattr(site, f), 'uptime_master': value})
        if r.uptime_fields is not None and r.uptime_fields != site.uptime_master_fields:
            uptime_fields[site.pk] = r.uptime_fields
        for month, (flag, raw) in r.om.items():  # information only: the matrix date decides
            derived = rules.om_effective_from(site.om_start_date, month) is not None
            if bool(flag) != derived:
                om_differences.append({'site_id': site.bsnl_site_id, 'month': month.strftime('%Y-%m'), 'uptime_master_flag': raw,
                                       'matrix_om_start_date': site.om_start_date.isoformat() if site.om_start_date else None, 'matrix_derived': derived})
        for day, text in r.invalid:
            checked = rules.check_outage(text)
            cells_rejected.append({'row': r.row, 'site_id': r.site_id, 'date': day.isoformat(), 'value': text, 'code': checked.code, 'message': checked.message})
        for day, outage in sorted(r.days.items()):
            checked = rules.check_outage(outage)
            if not checked.usable:
                cells_rejected.append({'row': r.row, 'site_id': r.site_id, 'date': day.isoformat(), 'value': outage, 'code': checked.code, 'message': checked.message})
                continue
            values.append(daily.DailyValue(site.pk, site.technology, site.circle, day, rules.availability_from_outage(checked.value), checked.value,
                                           r.row, r.site_id))
    classified = daily.classify(values, KIND)
    rejected_days = sum(x['site_days'] for x in rejected) + len(cells_rejected)
    received = len(values) + rejected_days + unmatched_days + source.duplicate_site_days
    counts = {'received': received, 'rejected': rejected_days, 'unmatched': unmatched_days, 'accepted': len(classified.new),
              'duplicate': len(classified.duplicate) + source.duplicate_site_days, 'conflict': len(classified.conflict),
              'superseded': len(classified.superseded)}
    reasons = Counter()
    for x in rejected:
        reasons[x['code']] += x['site_days']
    for x in cells_rejected:
        reasons[x['code']] += 1
    report = {
        'format': source.format, 'sheet': source.sheet, 'sheets': sheets, 'project_stated': project,
        'months_in_scope': sorted(m.strftime('%Y-%m') for m in scope), 'months_in_file': source.months_in_file,
        'rows_read': len(source.rows) + len(source.rejected),
        'rejected_rows': uploads.examples(rejected, MAX_LISTED), 'rejected_rows_count': len(rejected),
        'rejected_rows_by_reason': dict(Counter(x['code'] for x in rejected)),
        'rejected_cells': uploads.examples(cells_rejected, MAX_LISTED), 'rejected_site_days_by_reason': dict(reasons),
        'not_reported_site_days': blank_days, 'duplicate_rows_site_days': source.duplicate_site_days,
        'sites_not_in_site_master': [r.site_id for r, _ in unmatched][:MAX_LISTED], 'sites_not_in_site_master_count': len(unmatched),
        # Per unmatched site: what is pending until it is resolved (unmatched.py); the values stay in the staged copy.
        'unmatched_sites': [{'site_id': r.site_id, 'project': r.project, 'circle': r.circle, 'row': r.row, 'site_days': n,
                             'first_date': min([*r.days, *(d for d, _ in r.invalid)]).isoformat() if n else None,
                             'last_date': max([*r.days, *(d for d, _ in r.invalid)]).isoformat() if n else None}
                            for r, n in unmatched][:MAX_LISTED],
        'matrix_attribute_differences': dict(differences), 'matrix_attribute_difference_examples': diff_examples,
        'om_start_flags_differing_from_matrix': len(om_differences), 'om_start_flag_difference_examples': om_differences[:30],
        'uptime_only_fields_changed': len(uptime_fields),
        'conflicts': daily.conflict_examples(classified), 'notes': source.notes,
        'warnings': [w for w in (
            f'{len(rejected)} row(s) rejected.' if rejected else '',
            f'{len(cells_rejected)} site-day value(s) rejected.' if cells_rejected else '',
            f'{len(unmatched)} site(s) of the workbook are not in the site master and were not imported.' if unmatched else '',
            f'{len(classified.conflict)} site-day value(s) differ from a stored value of equal precedence and were logged as conflicts.' if classified.conflict else '',
            f'{len(classified.superseded)} stored raw CSV value(s) are replaced by this Uptime Master (higher precedence); the replaced values are logged.' if classified.superseded else '',
            'No daily values in the months in scope.' if not received else '',
        ) if w],
    }
    items = [exceptions.record(source_file=name, code=x['code'], row=x['row'], site_id=x['site_id'], message=x['message'],
                               related=f"{x['site_days']} site-day(s) in scope") for x in rejected]
    items += [exceptions.record(source_file=name, code=x['code'], row=x['row'], site_id=x['site_id'], report_date=x['date'], value=x['value'],
                                message=x['message']) for x in cells_rejected]
    items += [exceptions.record(source_file=name, code='site_not_in_master', severity=exceptions.UNMATCHED, row=r.row, site_id=r.site_id, circle=r.circle,
                                message='Not in the Consolidation Matrix site master: kept unmatched and excluded until the site is added '
                                        'through the authorized master-data process.', related=f'{n} site-day(s) in scope')
              for r, n in unmatched]
    items += daily.exception_items(classified, name)
    return {'classified': classified, 'values': values, 'uptime_fields': uptime_fields, 'counts': counts, 'report': report, 'exceptions': items}


def preview(path: Path, name: str, *, project: str | None = None, user=None) -> UploadBatch:
    batch = uploads.new_batch(KIND, path, name, user, technology=project or '')
    try:
        result = analyse(Path(batch.stored_path), name, project)
    except uploads.UploadRejected as exc:
        batch.error = str(exc)
        return uploads.record_preview(batch, {}, {'error': str(exc)}, failed=True)
    report = {**result['report'], **earlier_imports(batch.checksum_sha256, exclude=batch.pk)}
    if report['already_imported']:
        report['warnings'] = [*report['warnings'], f"This exact file was already imported into the new data layer (upload "
                              f"#{report['already_imported']['batch']}); committing again adds no record that is already stored."]
    return uploads.record_preview(batch, result['counts'], report, exception_items=result['exceptions'])


def commit(batch: UploadBatch, *, user=None, request=None) -> UploadBatch:
    uploads.require_previewed(batch)
    result = analyse(uploads.staged_file(batch), batch.original_filename, batch.technology or None)
    if not uploads.same_counts(batch, result['counts']):
        raise uploads.UploadRejected('The database changed since the preview; preview the file again before committing.')
    with transaction.atomic():
        daily.write(batch, result['classified'])
        for site_id, fields in result['uptime_fields'].items():
            Site.objects.filter(pk=site_id).update(uptime_master_fields=fields)
        uploads.mark_committed(batch)
    audit('sitedata.uptime_master_committed', request, batch=batch.pk, file=batch.original_filename, **result['counts'])
    return batch
