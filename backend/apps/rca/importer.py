"""Preview and commit an RCA workbook.

Preview parses and validates the file and compares every valid row with the database by its identity
(reporting date, project, site, occurrence): a site can have several RCA records on one date (separate outages),
ranked by cause and outage (see parser). Site ID alone never identifies a record. It writes only an RcaImportBatch. Commit runs in one transaction: new rows are inserted, identical
rows are left alone (so a repeat upload changes nothing), and rows whose source facts differ are never
overwritten silently: the uploader chooses to keep the stored values or to update them, and an update is
recorded in each record's history.

An upload with report details (report name, reporting date or period, project scope) is checked more strictly:
every row must carry a date no later than the reporting date, a project of the scope and a Site ID of the
Up-Time Report. Rows that fail are rejected; the valid rows are imported only after the uploader confirms
importing without them.

The daily workbook is cumulative (it repeats the earlier days), so each row is classified by its own date:
- rows of the reporting date (or period): the day's data. Stored records of that date and scope that the
  workbook no longer lists (a corrected workbook) are shown, and the uploader keeps or withdraws them;
- rows of earlier dates: history. Identical rows are skipped, differing rows are corrections that need the
  same explicit choice as any other difference, rows not stored yet are added under their own date, and
  nothing of an earlier date is ever withdrawn.
Withdrawn and overwritten records stay in the audit trail.

Two upload types (RcaImportBatch.upload_type), both into the same RcaRecord table through this importer:
- circle: one project, one circle, one reporting date. Rows of another project, circle or date are rejected, and a file
  holding another date is refused as a whole. Its records are compared only within that project, circle and date.
- consolidated: several circles and dates. The reporting date is the one entered, or else the latest date in the
  workbook. Rows of earlier dates are history, as above. Stored records the workbook no longer lists are offered for
  withdrawal only within the project/circle units it holds on the reporting date. Nothing outside the uploaded scope
  is ever withdrawn.
Each reporting date belongs to one daily reporting period (cycles.cycle_for_date), created when first needed; an
existing period containing the date is reused, so periods never overlap.

Outage minutes are stored as the RCA workbook gives them; the Up-Time Report's figures are never changed here.
"""
from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import parser
from .models import RcaEvent, RcaImportBatch, RcaRecord, RcaReportingCycle

SOURCE_FIELDS = ('project_raw', 'circle', 'circle_raw', 'site_id', 'site_name', 'oa', 'ba', 'om_start_raw', 'om_start',
                 'outage_minutes', 'final_bucket', 'final_bucket_key', 'bucket_2', 'bucket_2_key', 'rca_text', 'rca_key')
CONFLICT_ACTIONS = ('skip', 'overwrite')
MISSING_ACTIONS = ('keep', 'withdraw')
def project_scope(scope: str) -> set[str]:
    """The projects of an upload's scope: one project of the Organization, or "both" for every project."""
    from apps.organization.services import project_keys
    return set(project_keys()) if scope == 'both' else {scope}
MAX_CONFLICT_EXAMPLES = 50


class ImportRejected(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _identity(row: dict) -> tuple:
    return (row['reporting_date'], row['project'], row['site_key'], row.get('occurrence', 1))


def _compare(rows: list[dict], *, units: set[tuple[str, str, str]] | None = None) -> dict:
    """Split the rows into new / restored / unchanged / conflicting against the imported records in the database.

    ``units``: (reporting date, project, circle) combinations the upload answers for. Stored records of exactly those
    units that the workbook does not contain are listed as "missing" (offered for withdrawal); records of any other
    circle, project or date never are.
    """
    units = units or set()
    days = {date.fromisoformat(r['reporting_date']) for r in rows} | {date.fromisoformat(u[0]) for u in units}
    existing_qs = RcaRecord.all_objects.filter(source=RcaRecord.Source.IMPORT, reporting_date__in=days)
    existing = {(rec.reporting_date.isoformat(), rec.project, rec.site_key, rec.occurrence): rec for rec in existing_qs}
    new, restored, unchanged, conflicts = [], [], [], []
    for row in rows:
        record = existing.get(_identity(row))
        if record is None:
            new.append(row)
        elif record.withdrawn_at is not None:
            restored.append(row)  # withdrawn by an earlier correction, listed again: brought back with this file's values
        else:
            differences = {f: {'database': getattr(record, f), 'file': row[f]} for f in SOURCE_FIELDS
                           if not _same(getattr(record, f), row[f])}
            if differences:
                conflicts.append({'row': row['source_row'], 'site_id': row['site_id'], 'record_id': record.pk, 'differences': differences})
            else:
                unchanged.append(row)
    missing = []
    if units:
        listed = {_identity(r) for r in rows}
        missing = [{'record_id': rec.pk, 'site_id': rec.site_id, 'project': rec.project, 'circle': rec.circle,
                    'reporting_date': rec.reporting_date.isoformat(), 'outage_minutes': rec.outage_minutes,
                    'final_bucket': rec.final_bucket, 'source_file': rec.source_file}
                   for key, rec in sorted(existing.items())
                   if rec.withdrawn_at is None and (rec.reporting_date.isoformat(), rec.project, rec.circle) in units and key not in listed]
    return {'new': new, 'restored': restored, 'unchanged': unchanged, 'conflicts': conflicts, 'missing': missing, 'existing': existing}


def _same(a, b) -> bool:
    numeric = (int, float)
    if isinstance(a, numeric) and isinstance(b, numeric) and not isinstance(a, bool) and not isinstance(b, bool):
        return abs(float(a) - float(b)) < 1e-6
    if isinstance(a, str) or isinstance(b, str):
        return (a or '') == (b or '')
    return a == b


def _known_sites() -> dict[tuple[str, str], str]:
    from apps.uptimedb.models import UptimeSite
    return {(p, k): c for p, k, c in UptimeSite.objects.values_list('project', 'site_key', 'circle')}


def _store(path: Path, batch: RcaImportBatch) -> None:
    """Keep a copy of the uploaded workbook for audit (never modified). The stored name is generated, not the upload's."""
    folder = Path(settings.DATA_DIR) / 'processed' / 'rca_uploads' / f'{batch.period_start.isoformat()}_{batch.period_end.isoformat()}'
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f'{batch.pk}_{batch.checksum_sha256[:12]}{path.suffix.lower()}'
    shutil.copyfile(path, target)
    batch.stored_path = str(target)
    batch.save(update_fields=['stored_path'])


def _period(batch: RcaImportBatch) -> tuple[date, date] | None:
    return (batch.period_start, batch.period_end) if batch.period_start else None


def scope_units(batch_or_kind, rows: list[dict], *, day: date | None, project: str = '', circle: str | None = None) -> set[tuple[str, str, str]]:
    """The (date, project, circle) units an upload answers for (see the module notes). Legacy uploads: none."""
    kind = getattr(batch_or_kind, 'upload_type', batch_or_kind)
    if day is None:
        return set()
    if kind == RcaImportBatch.UploadType.CIRCLE:
        return {(day.isoformat(), project, circle)}
    if kind == RcaImportBatch.UploadType.CONSOLIDATED:
        return {(r['reporting_date'], r['project'], r['circle']) for r in rows if r['reporting_date'] == day.isoformat()}
    return set()


def _batch_units(batch: RcaImportBatch) -> set[tuple[str, str, str]]:
    return scope_units(batch, batch.rows, day=batch.period_start, project=batch.project_scope, circle=batch.circle)


def preview(path: Path, filename: str, *, user=None, details: dict | None = None) -> RcaImportBatch:
    """Validate a workbook. ``details`` (from the upload form): upload_type, report_name, period_start (the reporting
    date; may be None for a consolidated upload: the latest date in the workbook), project_scope, circle (circle
    uploads), remarks. Without details: the command-line style import (a legacy upload)."""
    from . import cycles  # cycles imports this module
    checksum = parser.sha256(path)
    fields = {}
    expect = {}
    kind = details.get('upload_type', RcaImportBatch.UploadType.LEGACY) if details else RcaImportBatch.UploadType.LEGACY
    if details:
        start = details.get('period_start')
        fields = {'report_name': details['report_name'], 'period_start': start, 'period_end': start,
                  'project_scope': details['project_scope'], 'remarks': details.get('remarks', ''), 'upload_type': kind,
                  'circle': details.get('circle') or None, 'cycle': cycles.containing_cycle(start) if start else None,
                  'file_size': path.stat().st_size}
        expect = {'period': (start, start) if start else None, 'projects': project_scope(details['project_scope']),
                  'known_sites': _known_sites()}
        if kind == RcaImportBatch.UploadType.CIRCLE:
            expect.update(circle=details['circle'], single_date=True)
    try:
        parsed = parser.parse(path, filename, **expect)
    except parser.ParseError as exc:
        batch = RcaImportBatch.objects.create(original_filename=filename, checksum_sha256=checksum, sheet_name=parser.SHEET_NAME,
                                              status=RcaImportBatch.Status.FAILED, imported_by=user, error=str(exc), **fields)
        if details:
            _store(path, batch)
        raise ImportRejected(str(exc)) from exc
    rows, report = parsed['rows'], parsed['report']
    if not rows and not details:
        raise ImportRejected('The workbook has no valid RCA rows to import. Download the issue report for the reasons.')
    if details and fields['period_start'] is None:
        # A consolidated workbook without an entered date: its latest date is the reporting date, earlier dates history.
        latest = max((r['reporting_date'] for r in rows), default=None)
        if latest:
            day = date.fromisoformat(latest)
            fields.update(period_start=day, period_end=day, cycle=cycles.containing_cycle(day))
            expect['period'] = (day, day)
            for r in rows:
                r['earlier_date'] = r['reporting_date'] < latest
    if details and fields['period_start'] and fields['period_start'] > timezone.localdate():
        report['file_error'] = f'The workbook has rows dated {fields["period_start"]:%d %b %Y}, in the future; nothing can be imported.'
    other_dates = report['issue_counts'].get('other_date', 0) + report['issue_counts'].get('after_reporting_period', 0)
    if kind == RcaImportBatch.UploadType.CIRCLE and other_dates:
        report['file_error'] = (f'{other_dates} rows are of another date than the reporting date {fields["period_start"]:%d %b %Y}. '
                                'A circle file holds one reporting date: upload each date separately, or use Upload Consolidated RCA.')
    units = scope_units(kind, rows, day=fields.get('period_start'), project=fields.get('project_scope', ''), circle=fields.get('circle'))
    comparison = _compare(rows, units=units)
    previous = RcaImportBatch.objects.filter(checksum_sha256=checksum, status=RcaImportBatch.Status.COMMITTED).first()
    earlier_uploads = RcaImportBatch.objects.filter(status=RcaImportBatch.Status.COMMITTED, period_start=fields.get('period_start'),
                                                    period_end=fields.get('period_end')).count() if details else 0
    by_date = _by_date(rows, comparison, expect.get('period'))
    coverage = _coverage(rows, fields.get('cycle'), expect.get('period'), expect.get('projects')) if details else None
    from .services import RCA_NOT_APPLICABLE  # services imports this module's models only
    known_buckets = set(RcaRecord.objects.order_by().values_list('final_bucket_key', flat=True).distinct())
    new_buckets: dict[str, int] = {}
    for r in rows:
        if r['final_bucket_key'] and r['final_bucket_key'] not in known_buckets:
            new_buckets[r['final_bucket']] = new_buckets.get(r['final_bucket'], 0) + 1
    report.update({
        'new_rows': len(comparison['new']), 'restored_rows': len(comparison['restored']),
        'unchanged_rows': len(comparison['unchanged']),
        'conflict_rows': len(comparison['conflicts']), 'conflicts': comparison['conflicts'][:MAX_CONFLICT_EXAMPLES],
        'missing_rows': len(comparison['missing']), 'missing': comparison['missing'][:MAX_CONFLICT_EXAMPLES],
        'already_imported': {'batch': previous.pk, 'committed_at': previous.committed_at.isoformat()} if previous else None,
        # A correction: the period already has accepted uploads and this workbook changes or drops some of their records.
        'earlier_uploads_for_period': earlier_uploads,
        # A correction changes or drops stored records (of the reporting date or of earlier dates).
        'is_correction': bool(comparison['conflicts'] or comparison['missing']),
        'by_date': by_date,
        'earlier_date_rows': sum(1 for r in rows if r.get('earlier_date')),
        'coverage': coverage,
        # Final Bucket labels not in any stored record: kept as written and never reinterpreted (e.g. read as Other Media).
        'new_final_buckets': dict(sorted(new_buckets.items(), key=lambda kv: -kv[1])),
        # Other Media is outside RCA recording: kept apart from RCA-applicable rows whose cause fields are blank.
        'rca_not_applicable_rows': sum(1 for r in rows if r['final_bucket_key'] in RCA_NOT_APPLICABLE),
        'missing_rca_rows': sum(1 for r in rows if r['final_bucket_key'] not in RCA_NOT_APPLICABLE
                                and not (r['final_bucket_key'] and r['bucket_2_key'] and r['rca_key'])),
    })
    rejected = bool(details) and (not rows or bool(report.get('file_error')))
    error = report.get('file_error') or ('No row passed validation; nothing can be imported.' if rejected else '')
    batch = RcaImportBatch.objects.create(
        original_filename=filename, checksum_sha256=checksum, sheet_name=report['sheet'], imported_by=user,
        report=report, rows=rows, counts={'total': report['rows_read'], 'valid': len(rows), 'rejected': report['rejected_rows']},
        units=sorted({(r['project'], r['circle']) for r in rows}),
        status=RcaImportBatch.Status.REJECTED if rejected else RcaImportBatch.Status.PREVIEWED,
        error=error, **fields,
    )
    if details and batch.period_start:
        _store(path, batch)
    return batch


def commit(batch: RcaImportBatch, *, user=None, conflict_action: str = '', missing_action: str = '',
           accept_rejected: bool = False) -> RcaImportBatch:
    if batch.status != RcaImportBatch.Status.PREVIEWED:
        raise ImportRejected(f'Import #{batch.pk} is {batch.get_status_display().lower()}; only a previewed import can be committed.', 409)
    if conflict_action and conflict_action not in CONFLICT_ACTIONS:
        raise ImportRejected('Choose "skip" or "overwrite" for conflicting rows.')
    if missing_action and missing_action not in MISSING_ACTIONS:
        raise ImportRejected('Choose "keep" or "withdraw" for stored records the file no longer lists.')
    rejected = batch.report.get('rejected_rows', 0)
    period = _period(batch)
    if period and rejected and not accept_rejected:
        raise ImportRejected(f'{rejected} rows were rejected. Confirm importing the {len(batch.rows)} valid rows without them, '
                             'or correct the workbook and upload it again.', 409)
    from . import cycles
    typed = batch.upload_type in (RcaImportBatch.UploadType.CIRCLE, RcaImportBatch.UploadType.CONSOLIDATED)
    with transaction.atomic():
        if typed:
            # Daily periods: the reporting date's own (or an existing period containing it), never an overlapping one.
            name = batch.report_name if batch.upload_type == RcaImportBatch.UploadType.CONSOLIDATED else ''
            cycle = cycles.cycle_for_date(period[0], user=user, name=name)
        else:
            cycle = cycles.period_cycle(*period, create=True, name=batch.report_name, user=user, lock=True) if period else None
        # Rows of other dates (earlier days of a cumulative workbook) are filed under their own date's period.
        for day in sorted({r['reporting_date'] for r in batch.rows if r.get('earlier_date') or (typed and r['reporting_date'] != period[0].isoformat())}):
            cycles.cycle_for_date(date.fromisoformat(day), user=user)
        # Periods of these dates are locked so a final report is never built from a half-applied import.
        list(RcaReportingCycle.objects.select_for_update().filter(reporting_date__in={r['reporting_date'] for r in batch.rows}))
        # Compared again inside the transaction: the database may have changed since the preview.
        comparison = _compare(batch.rows, units=_batch_units(batch) if typed else _legacy_units(batch, period))
        conflicts, missing = comparison['conflicts'], comparison['missing']
        if conflicts and not conflict_action:
            raise ImportRejected(f'{len(conflicts)} rows differ from RCA records already in the database. '
                                 'Choose whether to keep the stored values or update them.', 409)
        if missing and not missing_action:
            raise ImportRejected(f'{len(missing)} stored records of this period are not in the workbook. '
                                 'Choose whether to keep them or withdraw them.', 409)
        now = timezone.now()
        RcaRecord.objects.bulk_create([
            RcaRecord(**_fields(row), reporting_date=date.fromisoformat(row['reporting_date']), project=row['project'],
                      site_key=row['site_key'], occurrence=row.get('occurrence', 1), source=RcaRecord.Source.IMPORT, batch=batch,
                      source_file=batch.original_filename, source_row=row['source_row'], created_by=user)
            for row in comparison['new']
        ], batch_size=500)
        for row in comparison['restored']:
            record = comparison['existing'][_identity(row)]
            _apply(record, row, batch)
            record.withdrawn_at, record.withdrawn_by_batch = None, None
            record.save()
            RcaEvent.objects.create(record=record, user=user, action='restored', changes={'batch': batch.pk, 'file': batch.original_filename})
        overwritten = 0
        if conflicts and conflict_action == 'overwrite':
            by_row = {r['source_row']: r for r in batch.rows}
            for conflict in conflicts:
                row = by_row[conflict['row']]
                record = comparison['existing'][_identity(row)]
                _apply(record, row, batch)
                record.save()
                RcaEvent.objects.create(record=record, user=user, action='source_overwritten',
                                        changes={**conflict['differences'], 'batch': batch.pk})
                overwritten += 1
        withdrawn = 0
        if missing and missing_action == 'withdraw':
            for item in missing:
                record = RcaRecord.objects.get(pk=item['record_id'])
                record.withdrawn_at, record.withdrawn_by_batch = now, batch
                record.save(update_fields=['withdrawn_at', 'withdrawn_by_batch', 'updated_at'])
                RcaEvent.objects.create(record=record, user=user, action='withdrawn',
                                        changes={'batch': batch.pk, 'file': batch.original_filename,
                                                 'reason': 'Not listed in the corrected workbook.'})
                withdrawn += 1
        batch.status = RcaImportBatch.Status.COMMITTED
        batch.committed_at = now
        batch.cycle = cycle or batch.cycle
        batch.conflict_action = conflict_action if conflicts else ''
        batch.missing_action = missing_action if missing else ''
        batch.counts = {
            'total': batch.report.get('rows_read', len(batch.rows) + rejected), 'valid': len(batch.rows), 'rejected': rejected,
            'inserted': len(comparison['new']) + len(comparison['restored']), 'restored': len(comparison['restored']),
            'updated': overwritten, 'overwritten': overwritten,
            'unchanged': len(comparison['unchanged']), 'conflicts': len(conflicts), 'skipped_conflicts': len(conflicts) - overwritten,
            # Skipped: rows already stored identically, plus differing rows whose stored values were kept.
            'skipped': len(comparison['unchanged']) + len(conflicts) - overwritten,
            'missing': len(missing), 'withdrawn': withdrawn, 'kept_missing': len(missing) - withdrawn,
            'correction': bool(overwritten or withdrawn),
            'earlier_date_rows': sum(1 for r in batch.rows if r.get('earlier_date')),
            # Dates whose stored records this import changed (their periods' coverage and reports refresh).
            'dates_changed': sorted({r['reporting_date'] for r in comparison['new'] + comparison['restored']}
                                    | {r['reporting_date'] for c in (conflicts if conflict_action == 'overwrite' else [])
                                       for r in batch.rows if r['source_row'] == c['row']}
                                    | ({m['reporting_date'] for m in missing} if withdrawn else set())),
        }
        batch.rows = []  # the rows now live in RcaRecord; the report keeps the validation result
        batch.save()
    return batch


def _legacy_units(batch: RcaImportBatch, period: tuple[date, date] | None) -> set[tuple[str, str, str]]:
    """A legacy upload still awaiting commit: the units it holds within its period (never other circles)."""
    if not period:
        return set()
    return {(r['reporting_date'], r['project'], r['circle']) for r in batch.rows
            if period[0].isoformat() <= r['reporting_date'] <= period[1].isoformat()}


def _by_date(rows: list[dict], comparison: dict, period: tuple[date, date] | None) -> list[dict]:
    """Per reporting date: what the workbook holds against the database (new date, repeated rows, corrections)."""
    days: dict[str, dict] = {}

    def day(key: str) -> dict:
        return days.setdefault(key, {'date': key, 'rows': 0, 'new': 0, 'unchanged': 0, 'changed': 0, 'missing': 0,
                                     'earlier_date': bool(period) and date.fromisoformat(key) < period[0]})
    for r in rows:
        day(r['reporting_date'])['rows'] += 1
    for kind, items in (('new', comparison['new'] + comparison['restored']), ('unchanged', comparison['unchanged'])):
        for r in items:
            day(r['reporting_date'])[kind] += 1
    by_row = {r['source_row']: r for r in rows}
    for c in comparison['conflicts']:
        day(by_row[c['row']]['reporting_date'])['changed'] += 1
    for m in comparison['missing']:
        day(m['reporting_date'])['missing'] += 1
    for item in days.values():
        item['kind'] = ('earlier date' if item['earlier_date'] else 'reporting date') + (
            ': new' if item['rows'] and item['new'] == item['rows'] else
            ': repeated' if item['rows'] and item['unchanged'] == item['rows'] and not item['missing'] else
            ': corrected' if item['changed'] or item['missing'] else ': partly new')
    return sorted(days.values(), key=lambda d: d['date'])


def _coverage(rows: list[dict], cycle, period: tuple[date, date] | None, projects: set[str] | None) -> dict:
    """The expected projects / circles of the reporting period against those the workbook has rows for (on those dates)."""
    from . import cycles
    if cycle is not None:
        expected, source = list(cycle.required.values_list('project', 'circle')), 'period'
    else:
        expected, source = cycles.default_units(before=period[0] if period else None), 'previous period'
    expected = [u for u in expected if not projects or u[0] in projects]
    present = sorted({(r['project'], r['circle']) for r in rows if not r.get('earlier_date')})
    return {'source': source if expected else None, 'expected': [list(u) for u in sorted(expected)],
            'present': [list(u) for u in present], 'missing': [list(u) for u in sorted(set(expected) - set(present))]}


def _apply(record: RcaRecord, row: dict, batch: RcaImportBatch) -> None:
    for field, value in _fields(row).items():
        setattr(record, field, value)
    record.batch, record.source_file, record.source_row = batch, batch.original_filename, row['source_row']


def _fields(row: dict) -> dict:
    return {f: row[f] for f in SOURCE_FIELDS}
