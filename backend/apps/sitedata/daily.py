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
- The same value from a source of higher precedence takes over the record's provenance (logged as superseded with an
  unchanged value), so a later different value from an equal source is judged against the higher source whatever the
  upload order: raw A, Uptime A, Uptime B gives the same result as Uptime A, Uptime B (a conflict, A kept).
- Writes into a finalized month are refused (FinalizedPeriod); an Admin correction may force one, with a reason.
- A value for a date after today (timezone.localdate()) is refused, from every source including corrections
  (FutureDate); the importers also reject such rows or cells individually (code future_date).
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

from .models import DailyPerformanceEvent, DailySitePerformance, MonthlySitePerformance, Technology, UploadBatch
from .uploads import UploadRejected
from .rules import MINUTES_PER_DAY, availability_from_outage, outage_from_availability  # noqa: F401 (shared rules)

TOLERANCE = 1e-6  # percentage points: values closer than this are the same value
CHUNK = 5000
SOURCE_RANK = {UploadBatch.Kind.CORRECTION: 3, UploadBatch.Kind.UPTIME_MASTER: 2,
               UploadBatch.Kind.RAW_CSV_4G: 1, UploadBatch.Kind.RAW_CSV_LWE: 1}


class FinalizedPeriod(UploadRejected):
    """A write into a month whose monthly results are finalized."""


class FutureDate(UploadRejected, ValueError):
    """A daily value for a date after today (a ValueError too, so the correction API answers 400)."""


def check_not_future(dates) -> None:
    """Refuse dates after today (the central guard of every write into the daily table)."""
    today = timezone.localdate()
    future = sorted({d for d in dates if d > today})
    if future:
        shown = ', '.join(f'{d:%d %b %Y}' for d in future[:5]) + (f' and {len(future) - 5} more' if len(future) > 5 else '')
        raise FutureDate(f'Daily values cannot be stored for a date after today ({today:%d %b %Y}): {shown}.')


def finalized_months(dates) -> list:
    months = {d.replace(day=1) for d in dates}
    if not months:
        return []
    return sorted(set(MonthlySitePerformance.objects.filter(month__in=months, is_current=True, finalized_at__isnull=False)
                      .values_list('month', flat=True)))


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
    upgraded: list = None  # (DailyValue, existing DailySitePerformance): same value from a higher source takes the provenance

    def __post_init__(self):
        self.superseded = self.superseded or []
        self.upgraded = self.upgraded or []

    def counts(self) -> dict:
        return {'accepted': len(self.new), 'duplicate': len(self.duplicate) + len(self.upgraded), 'conflict': len(self.conflict),
                'superseded': len(self.superseded)}

    def written_dates(self) -> set:
        """Dates whose stored daily values (or their provenance) this result changes."""
        return {v.report_date for v in self.new} | {v.report_date for v, _ in self.superseded + self.upgraded}


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
            if incoming > rank(rec.batch.kind):
                result.upgraded.append((v, rec))
            else:
                result.duplicate.append(v)
        elif incoming > rank(rec.batch.kind):
            result.superseded.append((v, rec))
        else:
            result.conflict.append((v, rec))
    return result


def write(batch: UploadBatch, classified: Classified) -> None:
    """Insert the new records, log the conflicts, and apply and log the superseded values. Call inside the commit
    transaction. Refused when a value is dated after today or a written value falls in a finalized month."""
    check_not_future([v.report_date for v in classified.new + classified.duplicate]
                     + [v.report_date for v, _ in classified.conflict + classified.superseded + classified.upgraded])
    closed = finalized_months(classified.written_dates())
    if closed:
        raise FinalizedPeriod('Finalized month(s) ' + ', '.join(f'{m:%b %Y}' for m in closed) + ' cannot be changed by an upload; '
                              'an Admin correction with a reason is needed.')
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
    if classified.upgraded:
        DailyPerformanceEvent.objects.bulk_create([
            DailyPerformanceEvent(site_id=v.site_id, report_date=v.report_date, technology=v.technology,
                                  action=DailyPerformanceEvent.Action.SUPERSEDED,
                                  proposed_availability_pct=v.availability_pct, proposed_outage_minutes=v.outage_minutes,
                                  stored_availability_pct=rec.availability_pct, stored_outage_minutes=rec.outage_minutes,
                                  batch=batch, stored_batch_id=rec.batch_id, source_row=v.source_row,
                                  source_identifier=v.source_identifier[:80], user=batch.uploaded_by,
                                  reason=f'Same value; {batch.get_kind_display()} becomes the source of record instead of '
                                         f'{rec.batch.get_kind_display()} (upload #{rec.batch_id}).')
            for v, rec in classified.upgraded], batch_size=CHUNK)
        now = timezone.now()
        for v, rec in classified.upgraded:
            rec.batch, rec.source_row, rec.source_identifier, rec.updated_at = batch, v.source_row, v.source_identifier[:80], now
        DailySitePerformance.objects.bulk_update([rec for _, rec in classified.upgraded],
                                                 ['batch', 'source_row', 'source_identifier', 'updated_at'], batch_size=CHUNK)


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


def _check_correction(user, reason: str, day: date, *, authorized: bool, force: bool) -> None:
    from apps.accounts.roles import ADMIN, role_of
    if not reason or not reason.strip():
        raise ValueError('A correction needs a reason.')
    check_not_future([day])
    # Admins always; other users only when the caller has checked their Edit permission on the site's project and
    # circle (the Data Panel, accounts.access).
    if not authorized and role_of(user) != ADMIN:
        raise PermissionDenied('Only an Admin can correct daily performance.')
    if finalized_months([day]) and not (force and role_of(user) == ADMIN):
        raise FinalizedPeriod(f'{day:%b %Y} is finalized; only an Admin can correct it, explicitly.')


def correct(record: DailySitePerformance, availability_pct: float, *, user, reason: str, request=None,
            authorized: bool = False, force: bool = False, refresh: bool = True) -> DailySitePerformance:
    """Authorized correction of one daily record (precedence 3, never overridden by an upload): logged with the old and
    new value, the user and the reason."""
    from .uploads import write_lock
    _check_correction(user, reason, record.report_date, authorized=authorized, force=force)
    outage = outage_from_availability(availability_pct)
    with transaction.atomic():
        write_lock()
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
    if refresh:
        from .uploads import refresh_after_daily_write
        refresh_after_daily_write([record.report_date], request)
    return record


def add_correction(site, report_date: date, availability_pct: float, *, user, reason: str, request=None,
                   authorized: bool = False, force: bool = False, refresh: bool = True) -> DailySitePerformance:
    """Authorized value for a site-day that has no record (not reported): the record is created at precedence 3 by a
    correction upload. A site-day that already has a record is corrected with correct()."""
    from .models import Site
    from .uploads import refresh_after_daily_write, write_lock
    if site.reporting_scope != Site.Scope.DASHBOARD:
        raise ValueError(f'{site.bsnl_site_id} is outside the dashboard reporting scope.')
    _check_correction(user, reason, report_date, authorized=authorized, force=force)
    outage = outage_from_availability(availability_pct)
    with transaction.atomic():
        write_lock()
        if DailySitePerformance.objects.filter(site=site, report_date=report_date, technology=site.technology).exists():
            raise ValueError(f'{site.bsnl_site_id} already has a value for {report_date:%d %b %Y}; correct that record instead.')
        batch = UploadBatch.objects.create(
            kind=UploadBatch.Kind.CORRECTION, original_filename='Authorized correction', uploaded_by=user,
            circle=site.circle, reporting_date=report_date, technology=site.technology,
            records_received=1, records_accepted=1, validation_status=UploadBatch.Validation.PASSED,
            processing_status=UploadBatch.Processing.COMMITTED, remarks=reason.strip(),
            report={'site': site.pk, 'date': report_date.isoformat(), 'created': True, 'availability_pct': availability_pct})
        batch.committed_at = batch.uploaded_at
        batch.save(update_fields=['committed_at'])
        record = DailySitePerformance.objects.create(site=site, report_date=report_date, technology=site.technology, circle=site.circle,
                                                     availability_pct=availability_pct, outage_minutes=outage, batch=batch)
    audit('sitedata.daily_added', request, record=record.pk, site=site.pk, date=report_date, availability=availability_pct, batch=batch.pk)
    if refresh:
        refresh_after_daily_write([report_date], request)
    return record


TECHNOLOGIES = tuple(Technology.values)
