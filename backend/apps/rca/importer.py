"""Preview and commit an RCA workbook.

Preview parses and validates the file and compares every valid row with the database by its identity
(reporting date, project, site). It writes only an RcaImportBatch. Commit runs in one transaction:
new rows are inserted, identical rows are left alone (so a repeat import changes nothing), and rows
whose source facts differ (conflicts) are never overwritten silently: the Admin must choose to skip
them or to overwrite them, and an overwrite is recorded in each record's history.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from django.db import transaction
from django.utils import timezone

from . import parser
from .models import RcaEvent, RcaImportBatch, RcaRecord

SOURCE_FIELDS = ('project_raw', 'circle', 'circle_raw', 'site_id', 'site_name', 'oa', 'ba', 'om_start_raw', 'om_start',
                 'outage_minutes', 'final_bucket', 'final_bucket_key', 'bucket_2', 'bucket_2_key', 'rca_text', 'rca_key')
CONFLICT_ACTIONS = ('skip', 'overwrite')
MAX_CONFLICT_EXAMPLES = 50


class ImportRejected(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _identity(row: dict) -> tuple:
    return (row['reporting_date'], row['project'], row['site_key'])


def _compare(rows: list[dict]) -> dict:
    """Split the rows into new / unchanged / conflicting against the imported records in the database."""
    dates = {date.fromisoformat(r['reporting_date']) for r in rows}
    existing = {
        (rec.reporting_date.isoformat(), rec.project, rec.site_key): rec
        for rec in RcaRecord.objects.filter(source=RcaRecord.Source.IMPORT, reporting_date__in=dates)
    }
    new, unchanged, conflicts = [], [], []
    for row in rows:
        record = existing.get(_identity(row))
        if record is None:
            new.append(row)
            continue
        differences = {f: {'database': getattr(record, f), 'file': row[f]} for f in SOURCE_FIELDS
                       if not _same(getattr(record, f), row[f])}
        if differences:
            conflicts.append({'row': row['source_row'], 'site_id': row['site_id'], 'record_id': record.pk, 'differences': differences})
        else:
            unchanged.append(row)
    return {'new': new, 'unchanged': unchanged, 'conflicts': conflicts, 'existing': existing}


def _same(a, b) -> bool:
    numeric = (int, float)
    if isinstance(a, numeric) and isinstance(b, numeric) and not isinstance(a, bool) and not isinstance(b, bool):
        return abs(float(a) - float(b)) < 1e-6
    if isinstance(a, str) or isinstance(b, str):
        return (a or '') == (b or '')
    return a == b


def preview(path: Path, filename: str, *, user=None) -> RcaImportBatch:
    checksum = parser.sha256(path)
    try:
        parsed = parser.parse(path, filename)
    except parser.ParseError as exc:
        RcaImportBatch.objects.create(original_filename=filename, checksum_sha256=checksum, sheet_name=parser.SHEET_NAME,
                                      status=RcaImportBatch.Status.FAILED, imported_by=user, error=str(exc))
        raise ImportRejected(str(exc)) from exc
    rows, report = parsed['rows'], parsed['report']
    if not rows:
        raise ImportRejected('The workbook has no valid RCA rows to import. Download the issue report for the reasons.')
    comparison = _compare(rows)
    previous = RcaImportBatch.objects.filter(checksum_sha256=checksum, status=RcaImportBatch.Status.COMMITTED).first()
    report.update({
        'new_rows': len(comparison['new']), 'unchanged_rows': len(comparison['unchanged']),
        'conflict_rows': len(comparison['conflicts']), 'conflicts': comparison['conflicts'][:MAX_CONFLICT_EXAMPLES],
        'already_imported': {'batch': previous.pk, 'committed_at': previous.committed_at.isoformat()} if previous else None,
    })
    return RcaImportBatch.objects.create(
        original_filename=filename, checksum_sha256=checksum, sheet_name=parser.SHEET_NAME, imported_by=user,
        report=report, rows=rows, counts={'valid': len(rows), 'rejected': report['rejected_rows']},
    )


def commit(batch: RcaImportBatch, *, user=None, conflict_action: str = '') -> RcaImportBatch:
    if batch.status != RcaImportBatch.Status.PREVIEWED:
        raise ImportRejected(f'Import #{batch.pk} is {batch.get_status_display().lower()}; only a previewed import can be committed.', 409)
    if conflict_action and conflict_action not in CONFLICT_ACTIONS:
        raise ImportRejected('Choose "skip" or "overwrite" for conflicting rows.')
    with transaction.atomic():
        # Compared again inside the transaction: the database may have changed since the preview.
        comparison = _compare(batch.rows)
        conflicts = comparison['conflicts']
        if conflicts and not conflict_action:
            raise ImportRejected(f'{len(conflicts)} rows differ from RCA records already in the database. '
                                 'Choose whether to skip them or overwrite them.', 409)
        now = timezone.now()
        RcaRecord.objects.bulk_create([
            RcaRecord(**_fields(row), reporting_date=date.fromisoformat(row['reporting_date']), project=row['project'],
                      site_key=row['site_key'], source=RcaRecord.Source.IMPORT, batch=batch,
                      source_file=batch.original_filename, source_row=row['source_row'], created_by=user)
            for row in comparison['new']
        ], batch_size=500)
        overwritten = 0
        if conflicts and conflict_action == 'overwrite':
            by_row = {r['source_row']: r for r in batch.rows}
            for conflict in conflicts:
                row = by_row[conflict['row']]
                record = comparison['existing'][_identity(row)]
                for field, value in _fields(row).items():
                    setattr(record, field, value)
                record.batch, record.source_file, record.source_row = batch, batch.original_filename, row['source_row']
                record.save()
                RcaEvent.objects.create(record=record, user=user, action='source_overwritten',
                                        changes={**conflict['differences'], 'batch': batch.pk})
                overwritten += 1
        batch.status = RcaImportBatch.Status.COMMITTED
        batch.committed_at = now
        batch.conflict_action = conflict_action if conflicts else ''
        batch.counts = {
            'inserted': len(comparison['new']), 'unchanged': len(comparison['unchanged']), 'conflicts': len(conflicts),
            'overwritten': overwritten, 'skipped_conflicts': len(conflicts) - overwritten,
            'rejected': batch.report.get('rejected_rows', 0),
        }
        batch.rows = []  # the rows now live in RcaRecord; the report keeps the validation result
        batch.save()
    return batch


def _fields(row: dict) -> dict:
    return {f: row[f] for f in SOURCE_FIELDS}
