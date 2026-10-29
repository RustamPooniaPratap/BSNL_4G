"""Raw daily CSV upload: preview (validate against the site master, nothing written to the daily table), explicit
commit (one transaction), validation report and consolidated export.

Shared by 4G Saturation and LWE; only the site resolver and the availability rule are project-specific
(resolvers.py, rules.py). Rules applied to every upload:
- the file's Report Date must be the entered reporting date (one date per file), and its Circle the selected circle;
- a row is importable only if its ID resolves to one master site of the selected project and circle, its
  availability is a number in 0-100, and the site appears once in the file (identical repeats are skipped,
  conflicting repeats rejected);
- an existing daily value of the site and date is never overwritten: identical values are skipped, different
  values are blocked as conflicts; a stored day without a value (not reported) is filled;
- outage minutes are calculated on the server (rules.outage_minutes); nothing the browser sends is used.

The commit re-reads the staged file (checksum verified), repeats the analysis and refuses if the approved records
differ from the preview. Master sites, monthly records and the dashboard source setting are never changed.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .. import datasource
from ..models import DataImportBatch, SiteDailyPerformance, UptimeSite
from . import parser
from .resolvers import resolver_for
from .rules import PROJECT_RULES, canonical_circle, outage_minutes, resolve_availability

PROJECTS = tuple(PROJECT_RULES)
ROW_PAGE = 100

# Reason code -> (accounting group, label shown in the preview and the validation report).
REASONS = {
    'ready': ('ready', 'Ready to import'),
    'fills_missing': ('ready', 'Ready to import (fills a day stored without a value)'),
    'identical': ('identical', 'Already stored with the same value: skipped'),
    'duplicate_row': ('duplicate', 'Repeat of an earlier row with the same value: skipped'),
    'conflicting_duplicate': ('duplicate', 'The site appears more than once with different values: not imported'),
    'conflict_existing': ('duplicate', 'A different value is already stored for this site and date: not overwritten'),
    'unknown_site': ('out_of_scope', 'Not in the approved site master (outside the project scope)'),
    'other_circle': ('scope_mismatch', 'Master site of another circle'),
    'other_project': ('scope_mismatch', 'Master site of another project'),
    'circle_mismatch': ('scope_mismatch', 'Circle in the file differs from the selected circle'),
    'blank_site_id': ('unresolved', 'Blank BTS IP ID'),
    'ambiguous_site': ('unresolved', 'Matches more than one master site'),
    'lwe_mapping_not_configured': ('unresolved', 'LWE identifier mapping not configured'),
    'missing_availability': ('availability', 'Availability missing'),
    'invalid_availability': ('availability', 'Availability not a number'),
    'availability_out_of_range': ('availability', 'Availability outside 0–100'),
    'date_mismatch': ('date', 'Report Date differs from the entered reporting date'),
    'invalid_date': ('date', 'Report Date missing or not a date'),
    'malformed_row': ('other', 'Malformed row (wrong number of cells)'),
}
IMPORTABLE = {'ready', 'fills_missing'}
SKIPPED = {'identical', 'duplicate_row'}


def _rejected(rows: list[dict]) -> int:
    """Rows neither importable nor skipped as already stored / repeated."""
    return sum(1 for i in rows if i['code'] not in IMPORTABLE | SKIPPED)


class RawUploadRejected(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


@dataclass
class Details:
    project: str
    circle: str
    reporting_date: date
    remarks: str = ''


# --- Analysis ------------------------------------------------------------------------------------

def analyse(path: Path, details: Details) -> dict:
    """Validate the file against the details, the site master and the stored daily values. Writes nothing."""
    rules = PROJECT_RULES[details.project]
    parsed = parser.parse(path, max_bytes=settings.MAX_UPLOAD_BYTES)
    resolver = resolver_for(details.project, details.circle)
    scope = resolver.scope_size()
    if scope == 0:
        raise RawUploadRejected(f'The site master has no {details.project} sites for circle {details.circle}, so nothing can be '
                                'validated. Import the Master workbook into the database first.', 409)

    file_issues: list[dict] = []
    dates = Counter(parser.parse_date(r.values['report_date']) for r in parsed.rows)
    valid_dates = {d for d in dates if d}
    circles = Counter(canonical_circle(r.values['circle']) for r in parsed.rows)
    if len(valid_dates) > 1:
        file_issues.append({'code': 'mixed_dates', 'message': 'The file has more than one Report Date ('
                            + ', '.join(f'{d:%d-%m-%Y}: {dates[d]} rows' for d in sorted(valid_dates)) + '). A file must hold one day.'})
    elif valid_dates and details.reporting_date not in valid_dates:
        only = next(iter(valid_dates))
        file_issues.append({'code': 'date_mismatch', 'message': f'The file is for {only:%d-%m-%Y}, not the entered reporting date '
                                                                f'{details.reporting_date:%d-%m-%Y}.'})
    if set(circles) - {details.circle}:
        written = sorted({r.values['circle'] for r in parsed.rows if canonical_circle(r.values['circle']) != details.circle})
        file_issues.append({'code': 'circle_mismatch', 'message': f'The file has rows of circle {", ".join(written)}, not the selected '
                                                                  f'circle {details.circle}.'})

    rows: list[dict] = []
    for m in parsed.malformed:
        rows.append({'line': m['line'], 'raw_id': '', 'code': 'malformed_row',
                     'message': f'{m["cells"]} cells where the header has {m["expected"]}.'})
    for raw in parsed.rows:
        v = raw.values
        item = {'line': raw.line, 'raw_id': v['site_id'], 'raw_circle': v['circle'], 'raw_date': v['report_date'],
                'raw_availability': v.get(rules.availability_field, ''), 'site': None, 'site_id': None, 'site_name': v.get('site_name', ''),
                'availability': None, 'outage_minutes': None, 'note': ''}
        day = parser.parse_date(v['report_date'])
        if day is None:
            item.update(code='invalid_date', message=f'Report Date "{v["report_date"]}" is missing or not a date.')
        elif day != details.reporting_date:
            item.update(code='date_mismatch', message=f'Report Date {v["report_date"]} is not {details.reporting_date:%d-%m-%Y}.')
        elif canonical_circle(v['circle']) != details.circle:
            item.update(code='circle_mismatch', message=f'Circle "{v["circle"]}" is not {details.circle}.')
        else:
            found = resolver.resolve(v['site_id'])
            if found.code:
                item.update(code=found.code, message=found.message)
            else:
                site = found.site
                item.update(site=site, site_id=site.site_id, site_name=site.site_name or item['site_name'])
                avail = resolve_availability(v, rules)
                if avail.code:
                    item.update(code=avail.code, message=avail.message)
                else:
                    item.update(code='ready', message='', availability=avail.value, outage_minutes=outage_minutes(avail.value), note=avail.note)
        rows.append(item)

    # Repeats of a site in the file: identical repeats are skipped, differing ones rejected (no value is chosen).
    by_site: dict[int, list[dict]] = defaultdict(list)
    for item in rows:
        if item['site'] is not None:
            by_site[item['site'].pk].append(item)
    for items in by_site.values():
        if len(items) < 2:
            continue
        values = {(i['code'], i['availability']) for i in items}
        if len(values) == 1:
            for repeat in items[1:]:
                repeat.update(code='duplicate_row', message=f'Same site and value as line {items[0]["line"]}: skipped.')
        else:
            lines = ', '.join(str(i['line']) for i in items)
            for i in items:
                i.update(code='conflicting_duplicate', message=f'The site appears on lines {lines} with different values; none is imported.')

    # Against the stored daily values.
    ready = [i for i in rows if i['code'] == 'ready']
    stored = {s: (o, u) for s, o, u in SiteDailyPerformance.objects.filter(
        date=details.reporting_date, site_id__in=[i['site'].pk for i in ready]).values_list('site_id', 'outage_minutes', 'uptime_pct')}
    for item in ready:
        if item['site'].pk not in stored:
            continue
        outage, uptime = stored[item['site'].pk]
        if outage is None:
            item.update(code='fills_missing', message='Stored for this date without a value; this upload fills it.')
        elif abs(outage - item['outage_minutes']) < 1e-6 and (uptime is None or abs(uptime - item['availability']) < 1e-6):
            item.update(code='identical', message='Already stored with the same value.')
        else:
            item.update(code='conflict_existing', message=f'Stored outage {outage:.2f} min{f" ({uptime}%)" if uptime is not None else ""} '
                                                          f'differs from {item["outage_minutes"]:.2f} min ({item["availability"]}%); not overwritten.')

    in_file = {i['site'].pk for i in rows if i['site'] is not None}
    missing_sites = list(UptimeSite.objects.filter(project=details.project, circle=details.circle).exclude(pk__in=in_file)
                         .order_by('site_key').values_list('site_id', flat=True))
    blocked = bool(file_issues)
    approved = sorted((i['site'].pk, round(i['outage_minutes'], 9), i['availability']) for i in rows if i['code'] in IMPORTABLE)
    groups = Counter(REASONS[i['code']][0] for i in rows)
    codes = Counter(i['code'] for i in rows)
    summary = {
        'total_rows': len(rows),
        'valid_in_scope': sum(1 for i in rows if i['site'] is not None and i['availability'] is not None),
        'ready_to_import': 0 if blocked else groups['ready'],
        'identical_skipped': groups['identical'],
        'out_of_scope': groups['out_of_scope'],
        'unresolved_or_ambiguous': groups['unresolved'],
        'availability_problems': groups['availability'],
        'duplicates_or_conflicts': groups['duplicate'],
        'date_mismatches': groups['date'],
        'project_or_circle_mismatches': groups['scope_mismatch'],
        'other_invalid': groups['other'],
        'by_code': dict(codes),
    }
    return {
        'rows': rows, 'summary': summary, 'file_issues': file_issues, 'blocked': blocked,
        'approved_fingerprint': hashlib.sha256(json.dumps(approved).encode()).hexdigest(), 'approved_count': len(approved),
        'file': {'encoding': parsed.encoding, 'header_line': parsed.header_line, 'preamble': parsed.preamble, 'blank_lines': parsed.blank_lines,
                 'columns': parsed.columns, 'unused_columns': len(parsed.unknown_headers),
                 'report_dates': sorted(d.isoformat() for d in valid_dates), 'circles_in_file': dict(circles)},
        'availability_rule': {'column': rules.availability_column, 'confirmed': rules.availability_confirmed,
                              'formula': 'outage minutes = 1440 × (1 − availability / 100)'},
        'resolver': {'project': details.project, 'configured': resolver.configured},
        'master_scope': {'sites': scope, 'sites_in_file': len(in_file), 'missing_from_file': len(missing_sites),
                         'missing_examples': missing_sites[:20]},
    }


def _row_json(item: dict) -> dict:
    group, label = REASONS[item['code']]
    return {
        'line': item['line'], 'raw_id': item['raw_id'], 'site_id': item.get('site_id'), 'site_name': item.get('site_name') or '',
        'circle': item.get('raw_circle', ''), 'report_date': item.get('raw_date', ''), 'raw_availability': item.get('raw_availability', ''),
        'availability': item.get('availability'), 'outage_minutes': None if item.get('outage_minutes') is None else round(item['outage_minutes'], 4),
        'status': group, 'code': item['code'], 'label': label, 'message': item.get('message', ''), 'note': item.get('note', ''),
    }


# --- Preview, commit, discard ----------------------------------------------------------------------

def _store(source: Path, batch: DataImportBatch) -> None:
    folder = Path(settings.DATA_DIR) / 'processed' / 'raw_uploads' / batch.reporting_date.isoformat()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f'{batch.pk}_{batch.checksum_sha256[:12]}.csv'  # a generated name: the upload's name is never a path
    shutil.copyfile(source, target)
    batch.stored_path = str(target)
    batch.save(update_fields=['stored_path'])


def preview(path: Path, filename: str, details: Details, *, user) -> DataImportBatch:
    checksum = parser.sha256(path)
    base = dict(kind=DataImportBatch.Kind.RAW_DAILY_CSV, original_filename=filename, checksum_sha256=checksum, sheet_name='CSV',
                stored_path='', imported_by=user, initiated_via='raw_csv_upload', project=details.project, circle=details.circle,
                reporting_date=details.reporting_date, remarks=details.remarks)
    try:
        result = analyse(path, details)
    except parser.RawParseError as exc:
        batch = DataImportBatch.objects.create(**base, status=DataImportBatch.Status.FAILED, error=str(exc))
        _store(path, batch)
        raise RawUploadRejected(str(exc)) from exc
    rows = result.pop('rows')
    report = {**result, 'rows': [_row_json(i) for i in rows]}
    previous = DataImportBatch.objects.filter(kind=DataImportBatch.Kind.RAW_DAILY_CSV, checksum_sha256=checksum,
                                              status=DataImportBatch.Status.COMMITTED).first()
    report['already_imported'] = {'batch': previous.pk, 'committed_at': previous.committed_at.isoformat()} if previous else None
    nothing = not result['blocked'] and result['summary']['ready_to_import'] == 0
    status = DataImportBatch.Status.REJECTED if result['blocked'] else DataImportBatch.Status.PREVIEWED
    error = ' '.join(i['message'] for i in result['file_issues']) if result['blocked'] else ''
    batch = DataImportBatch.objects.create(
        **base, status=status, error=error, report=report,
        rejected_count=_rejected(rows), skipped_count=sum(1 for i in rows if i['code'] in SKIPPED),
        counts={'summary': result['summary'], 'nothing_to_import': nothing},
    )
    _store(path, batch)
    return batch


def commit(batch: DataImportBatch, *, user) -> DataImportBatch:
    if batch.kind != DataImportBatch.Kind.RAW_DAILY_CSV:
        raise RawUploadRejected('Not a raw daily CSV upload.', 404)
    if batch.status != DataImportBatch.Status.PREVIEWED:
        raise RawUploadRejected(f'Upload #{batch.pk} is {batch.get_status_display().lower()}; only a validated upload can be imported.', 409)
    path = Path(batch.stored_path)
    if not path.is_file() or parser.sha256(path) != batch.checksum_sha256:
        raise RawUploadRejected('The stored copy of the file is missing or changed since validation; upload it again.', 409)
    details = Details(batch.project, batch.circle, batch.reporting_date, batch.remarks)
    with transaction.atomic():
        result = analyse(path, details)  # repeated inside the transaction: master or stored values may have changed
        if not result['blocked'] and result['approved_count'] == 0:
            raise RawUploadRejected('Nothing in this file can be imported (no row is ready). See the validation report for the reasons.', 409)
        if result['blocked'] or result['approved_fingerprint'] != batch.report.get('approved_fingerprint'):
            raise RawUploadRejected('The site master or the stored daily values changed since this file was validated, so the '
                                    'approved records differ. Validate the file again.', 409)
        rows = result['rows']
        new = [i for i in rows if i['code'] == 'ready']
        fills = [i for i in rows if i['code'] == 'fills_missing']
        SiteDailyPerformance.objects.bulk_create([
            SiteDailyPerformance(site=i['site'], date=details.reporting_date, outage_minutes=i['outage_minutes'],
                                 uptime_pct=i['availability'], batch=batch) for i in new], batch_size=2000)
        for i in fills:
            SiteDailyPerformance.objects.filter(site=i['site'], date=details.reporting_date, outage_minutes__isnull=True) \
                .update(outage_minutes=i['outage_minutes'], uptime_pct=i['availability'], batch=batch)
        summary = result['summary']
        batch.status = DataImportBatch.Status.COMMITTED
        batch.committed_at = timezone.now()
        batch.counts = {'summary': summary, 'daily': {
            'inserted': len(new), 'filled': len(fills), 'skipped_identical': summary['identical_skipped'],
            'skipped_repeats': summary['by_code'].get('duplicate_row', 0), 'rejected': _rejected(rows)}}
        batch.rejected_count, batch.skipped_count = _rejected(rows), sum(1 for i in rows if i['code'] in SKIPPED)
        batch.save(update_fields=['status', 'committed_at', 'counts', 'rejected_count', 'skipped_count'])
    datasource.clear_cache()  # the database-backed dashboard rebuilds from the new rows; the source setting is unchanged
    return batch


def discard(batch: DataImportBatch) -> DataImportBatch:
    if batch.status != DataImportBatch.Status.PREVIEWED:
        raise RawUploadRejected('Only a validated upload that was not imported can be discarded.', 409)
    batch.status = DataImportBatch.Status.DISCARDED
    batch.save(update_fields=['status'])
    return batch


# --- Reports and export ----------------------------------------------------------------------------

def rows_page(batch: DataImportBatch, *, status: str = '', page: int = 1) -> dict:
    rows = batch.report.get('rows', [])
    if status:
        rows = [r for r in rows if r['status'] == status]
    pages = max(1, -(-len(rows) // ROW_PAGE))
    page = min(max(1, page), pages)
    return {'count': len(rows), 'page': page, 'pages': pages, 'rows': rows[(page - 1) * ROW_PAGE: page * ROW_PAGE]}


def validation_csv(batch: DataImportBatch) -> str:
    """Every row that is not imported, with its reason, plus file-level problems."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(['file', 'line', 'raw_bts_ip_id', 'master_site_id', 'circle', 'report_date', 'availability', 'outage_minutes',
                     'status', 'reason_code', 'reason'])
    for issue in batch.report.get('file_issues', []):
        writer.writerow([batch.original_filename, '', '', '', '', '', '', '', 'file', issue['code'], issue['message']])
    if batch.error and not batch.report:
        writer.writerow([batch.original_filename, '', '', '', '', '', '', '', 'file', 'unreadable_file', batch.error])
    for r in batch.report.get('rows', []):
        if r['code'] in IMPORTABLE:
            continue
        writer.writerow([batch.original_filename, r['line'], r['raw_id'], r['site_id'] or '', r['circle'], r['report_date'],
                         r['raw_availability'], '' if r['outage_minutes'] is None else r['outage_minutes'], r['status'], r['code'],
                         r['message'] or r['label']])
    return out.getvalue()
