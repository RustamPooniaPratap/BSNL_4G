"""Acceptance of daily values into the central DailySitePerformance table (confirmed rules, 4 Nov 2026).

Explicit source precedence (SOURCE_RANK), the same whatever the upload order:
    authorized correction (3) > Uptime Master (2) > raw CNMC CSV, 4G or LWE (1)
- A new site-day is inserted, from any source (a raw CSV is accepted where the Uptime Master has no value).
- The same value again (from any source) is a matching duplicate: nothing changes.
- A different value from a source of the same or lower precedence is a conflict: the stored value is kept and the
  proposed value is logged (DailyPerformanceEvent, action conflict) with both uploads. Among equal sources the first
  accepted value stays.
- A different value from a source of higher precedence supersedes the stored value: the record takes the new value and
  upload, and the replaced value, its upload and its file stay in the log (action superseded). So an Uptime Master value
  wins over a raw CSV value whether the CSV was imported before or after it, and a raw CSV never replaces an Uptime
  Master value. No other change happens automatically; anything else goes through correct() (Admin, with a reason).
Availability and outage are always consistent, by the shared rules (rules.py).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from apps.accounts.audit import audit

from .models import DailyPerformanceEvent, DailySitePerformance, Technology, UploadBatch
from .rules import MINUTES_PER_DAY, availability_from_outage, outage_from_availability  # noqa: F401 (shared rules)

TOLERANCE = 1e-6  # percentage points: values closer than this are the same value
CHUNK = 5000
SOURCE_RANK = {UploadBatch.Kind.CORRECTION: 3, UploadBatch.Kind.UPTIME_MASTER: 2,
               UploadBatch.Kind.RAW_CSV_4G: 1, UploadBatch.Kind.RAW_CSV_LWE: 1}


def rank(kind: str) -> int:
    if kind not in SOURCE_RANK:
        raise ValueError(f'Upload kind {kind!r} cannot write daily values.')
    return SOURCE_RANK[kind]


@dataclass(frozen=True)
class DailyValue:
    site_id: int
    technology: str
    circle: str
    report_date: date
    availability_pct: float
    outage_minutes: float
    source_row: int | None = None
    source_identifier: str = ''

    @property
    def key(self):
        return (self.site_id, self.report_date, self.technology)


@dataclass
class Classified:
    new: list
    duplicate: list
    conflict: list  # (DailyValue, existing DailySitePerformance): stored value kept
    superseded: list = None  # (DailyValue, existing DailySitePerformance): higher-precedence value replaces the stored one

    def __post_init__(self):
        self.superseded = self.superseded or []

    def counts(self) -> dict:
        return {'accepted': len(self.new), 'duplicate': len(self.duplicate), 'conflict': len(self.conflict), 'superseded': len(self.superseded)}


def classify(values: list[DailyValue], source_kind: str) -> Classified:
    """Compare proposed values (one per site-day) from an upload of ``source_kind`` with the stored records. Reads only."""
    incoming = rank(source_kind)
    by_date = defaultdict(set)
    for v in values:
        by_date[v.report_date].add(v.site_id)
    existing = {}
    for day, sites in by_date.items():
        ids = sorted(sites)
        for i in range(0, len(ids), CHUNK):
            for rec in DailySitePerformance.objects.filter(report_date=day, site_id__in=ids[i:i + CHUNK]).select_related('batch'):
                existing[(rec.site_id, rec.report_date, rec.technology)] = rec
    result = Classified([], [], [])
    for v in values:
        rec = existing.get(v.key)
        if rec is None:
            result.new.append(v)
        elif abs(rec.availability_pct - v.availability_pct) <= TOLERANCE:
            result.duplicate.append(v)
        elif incoming > rank(rec.batch.kind):
            result.superseded.append((v, rec))
        else:
            result.conflict.append((v, rec))
    return result


def write(batch: UploadBatch, classified: Classified) -> None:
    """Insert the new records, log the conflicts, and apply and log the superseded values. Call inside the commit
    transaction."""
    DailySitePerformance.objects.bulk_create([
        DailySitePerformance(site_id=v.site_id, report_date=v.report_date, technology=v.technology, circle=v.circle,
                             availability_pct=v.availability_pct, outage_minutes=v.outage_minutes, batch=batch,
                             source_row=v.source_row, source_identifier=v.source_identifier[:80])
        for v in classified.new], batch_size=CHUNK)
    DailyPerformanceEvent.objects.bulk_create([
        DailyPerformanceEvent(site_id=v.site_id, report_date=v.report_date, technology=v.technology,
                              action=DailyPerformanceEvent.Action.CONFLICT,
                              proposed_availability_pct=v.availability_pct, proposed_outage_minutes=v.outage_minutes,
                              stored_availability_pct=rec.availability_pct, stored_outage_minutes=rec.outage_minutes,
                              batch=batch, stored_batch_id=rec.batch_id, source_row=v.source_row,
                              source_identifier=v.source_identifier[:80], user=batch.uploaded_by)
        for v, rec in classified.conflict], batch_size=CHUNK)
    if classified.superseded:
        DailyPerformanceEvent.objects.bulk_create([
            DailyPerformanceEvent(site_id=v.site_id, report_date=v.report_date, technology=v.technology,
                                  action=DailyPerformanceEvent.Action.SUPERSEDED,
                                  proposed_availability_pct=v.availability_pct, proposed_outage_minutes=v.outage_minutes,
                                  stored_availability_pct=rec.availability_pct, stored_outage_minutes=rec.outage_minutes,
                                  batch=batch, stored_batch_id=rec.batch_id, source_row=v.source_row,
                                  source_identifier=v.source_identifier[:80], user=batch.uploaded_by,
                                  reason=f'{batch.get_kind_display()} takes precedence over {rec.batch.get_kind_display()} '
                                         f'({rec.batch.original_filename}, upload #{rec.batch_id}, row {rec.source_row}).')
            for v, rec in classified.superseded], batch_size=CHUNK)
        changed, now = [], timezone.now()
        for v, rec in classified.superseded:
            rec.availability_pct, rec.outage_minutes, rec.batch = v.availability_pct, v.outage_minutes, batch
            rec.source_row, rec.source_identifier, rec.revision = v.source_row, v.source_identifier[:80], rec.revision + 1
            rec.updated_at = now
            changed.append(rec)
        DailySitePerformance.objects.bulk_update(changed, ['availability_pct', 'outage_minutes', 'batch', 'source_row', 'source_identifier',
                                                           'revision', 'updated_at'], batch_size=CHUNK)


def conflict_examples(classified: Classified, limit: int = 20) -> list[dict]:
    return [{'action': action, 'site_id': rec.site_id, 'date': v.report_date.isoformat(), 'stored': round(rec.availability_pct, 6),
             'stored_upload': rec.batch_id, 'stored_file': rec.batch.original_filename, 'proposed': round(v.availability_pct, 6), 'row': v.source_row}
            for action, pairs in (('conflict', classified.conflict), ('superseded', classified.superseded)) for v, rec in pairs[:limit]]


def exception_items(classified: Classified, source_file: str) -> list[dict]:
    """Exception records of the conflicts (proposed value kept out) and superseded values (stored value replaced)."""
    from . import exceptions
    items = []
    for action, pairs in (('daily_conflict', classified.conflict), ('superseded_lower_precedence', classified.superseded)):
        for v, rec in pairs:
            kept, other = (rec, v) if action == 'daily_conflict' else (v, rec)
            items.append(exceptions.record(
                source_file=source_file, code=action, severity='conflict', row=v.source_row, circle=v.circle, report_date=v.report_date,
                site_id=v.source_identifier, value=v.availability_pct,
                message=(f'Stored {rec.availability_pct:.6f}% ({rec.batch.get_kind_display()}, {rec.batch.original_filename}) kept; '
                         f'this file has {v.availability_pct:.6f}%.') if action == 'daily_conflict' else
                        (f'This file ({v.availability_pct:.6f}%) takes precedence and replaces {rec.availability_pct:.6f}% from '
                         f'{rec.batch.get_kind_display()} {rec.batch.original_filename}.'),
                related=f'upload #{rec.batch_id}'))
    return items


def correct(record: DailySitePerformance, availability_pct: float, *, user, reason: str, request=None) -> DailySitePerformance:
    """Authorized correction of one daily record: logged with the old and new value, the user and the reason."""
    from apps.accounts.roles import ADMIN, role_of
    if not reason or not reason.strip():
        raise ValueError('A correction needs a reason.')
    if role_of(user) != ADMIN:  # data administration is Admin-only (accounts/catalog.ADMIN_ONLY)
        raise PermissionDenied('Only an Admin can correct daily performance.')
    outage = outage_from_availability(availability_pct)
    with transaction.atomic():
        record = DailySitePerformance.objects.select_for_update().get(pk=record.pk)
        batch = UploadBatch.objects.create(
            kind=UploadBatch.Kind.CORRECTION, original_filename='Authorized correction', uploaded_by=user,
            circle=record.circle, reporting_date=record.report_date, technology=record.technology,
            records_received=1, records_accepted=1, validation_status=UploadBatch.Validation.PASSED,
            processing_status=UploadBatch.Processing.COMMITTED, remarks=reason.strip(),
            report={'record': record.pk, 'site': record.site_id, 'date': record.report_date.isoformat()})
        batch.committed_at = batch.uploaded_at
        batch.save(update_fields=['committed_at'])
        DailyPerformanceEvent.objects.create(
            site_id=record.site_id, report_date=record.report_date, technology=record.technology,
            action=DailyPerformanceEvent.Action.CORRECTION, proposed_availability_pct=availability_pct,
            proposed_outage_minutes=outage, stored_availability_pct=record.availability_pct,
            stored_outage_minutes=record.outage_minutes, batch=batch, stored_batch_id=record.batch_id, user=user,
            reason=reason.strip())
        record.availability_pct, record.outage_minutes, record.batch = availability_pct, outage, batch
        record.revision += 1
        record.source_row, record.source_identifier = None, ''
        record.save()
    audit('sitedata.daily_corrected', request, record=record.pk, site=record.site_id, date=record.report_date,
          availability=availability_pct, batch=batch.pk)
    return record


TECHNOLOGIES = tuple(Technology.values)
