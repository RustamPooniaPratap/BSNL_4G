"""CSV arrival tracking: what PostgreSQL actually holds per project, circle and reporting date.

Two independent facts per project/circle and date, never derived from each other:

1. **Daily data coverage** (``SiteDailyPerformance``), whatever wrote it (Master workbook import or raw CSV upload):
   - Expected sites: the site master's On-Air sites of the project and circle (``UptimeSite.on_air``), the
     dashboard's default scope (docs/business-rules.md, "Scopes"). All master sites are reported alongside.
   - Usable record: outage minutes present and within 0 to 1,440. NULL is "not reported"; values outside the
     range are counted separately as invalid and never as usable.
   - Complete: every expected site has a usable record on the date. On-Air is the master's current flag, not a
     dated history, so completeness of older dates is measured against today's On-Air sites (stated in ``notes``).
   - Provenance: the import batch that last wrote each record (``batch.kind``).
2. **Raw CSV upload history** (``DataImportBatch`` of kind ``raw_daily_csv``) for the date, with its real lifecycle:
   validated and awaiting confirmation, imported, blocked, failed or discarded.

Nothing here writes to the database. Deadlines are not known to the server, so nothing is marked late here.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from django.db.models import Count, Q

from .models import DataImportBatch, SiteDailyPerformance, UptimeSite

MINUTES_PER_DAY = 1440
MAX_RANGE_DAYS = 92
DEFAULT_RANGE_DAYS = 14

SCOPE_RULE = 'On-Air = Yes in the site master (the dashboard default scope)'
USABLE_RULE = 'Outage minutes recorded and between 0 and 1,440'

# The raw-upload lifecycle as shown on the tracker, from DataImportBatch.status.
UPLOAD_STATES = {
    DataImportBatch.Status.COMMITTED: 'imported',
    DataImportBatch.Status.PREVIEWED: 'awaiting_confirmation',
    DataImportBatch.Status.REJECTED: 'blocked',
    DataImportBatch.Status.FAILED: 'failed',
    DataImportBatch.Status.DISCARDED: 'discarded',
}
# Which upload represents the date when several exist: an import first, then the most advanced open state.
_UPLOAD_PRIORITY = ('imported', 'awaiting_confirmation', 'nothing_to_import', 'blocked', 'failed', 'discarded')

_USABLE = Q(outage_minutes__isnull=False, outage_minutes__gte=0, outage_minutes__lte=MINUTES_PER_DAY)
_INVALID = Q(outage_minutes__isnull=False) & (Q(outage_minutes__lt=0) | Q(outage_minutes__gt=MINUTES_PER_DAY))


def data_state(usable: int, expected: int) -> str:
    if expected == 0:
        return 'no_scope'
    if usable >= expected:
        return 'complete'
    return 'partial' if usable else 'none'


def _pairs(allowed: set[str] | None) -> list[dict]:
    qs = UptimeSite.objects.order_by()
    if allowed is not None:
        qs = qs.filter(circle__in=allowed)
    rows = qs.values('project', 'circle').annotate(total=Count('id'), on_air=Count('id', filter=Q(on_air=True)))
    return sorted(rows, key=lambda r: (r['project'], r['circle']))


def _daily_counts(allowed: set[str] | None) -> dict[tuple[str, str], dict[date, dict]]:
    """Per project/circle and date: usable and invalid records of On-Air sites, and usable records of any master site."""
    qs = SiteDailyPerformance.objects.order_by()
    if allowed is not None:
        qs = qs.filter(site__circle__in=allowed)
    rows = qs.values('site__project', 'site__circle', 'date').annotate(
        usable=Count('id', filter=_USABLE & Q(site__on_air=True)),
        invalid=Count('id', filter=_INVALID & Q(site__on_air=True)),
        observed=Count('id', filter=_USABLE),
    )
    out: dict[tuple[str, str], dict[date, dict]] = defaultdict(dict)
    for r in rows:
        out[(r['site__project'], r['site__circle'])][r['date']] = r
    return out


def _provenance(day: date, allowed: set[str] | None) -> dict[tuple[str, str], dict[str, int]]:
    qs = SiteDailyPerformance.objects.order_by().filter(_USABLE, date=day, site__on_air=True)
    if allowed is not None:
        qs = qs.filter(site__circle__in=allowed)
    out: dict[tuple[str, str], dict[str, int]] = defaultdict(dict)
    for r in qs.values('site__project', 'site__circle', 'batch__kind').annotate(n=Count('id')):
        out[(r['site__project'], r['site__circle'])][r['batch__kind']] = r['n']
    return out


def _upload_json(batch: DataImportBatch) -> dict:
    counts = batch.counts or {}
    summary = counts.get('summary') or (batch.report or {}).get('summary') or {}
    written = counts.get('daily') or {}
    state = UPLOAD_STATES.get(batch.status, batch.status)
    if state == 'awaiting_confirmation' and counts.get('nothing_to_import'):
        state = 'nothing_to_import'
    return {
        'id': batch.pk, 'state': state, 'status_label': batch.get_status_display(), 'file': batch.original_filename,
        'uploaded_at': batch.uploaded_at.isoformat(), 'committed_at': batch.committed_at.isoformat() if batch.committed_at else None,
        'uploaded_by': batch.imported_by.get_username() if batch.imported_by else None,
        'ready_to_import': summary.get('ready_to_import'), 'rejected_count': batch.rejected_count,
        'imported': written.get('inserted', 0) + written.get('filled', 0) if batch.status == DataImportBatch.Status.COMMITTED else None,
        'error': batch.error or None,
    }


def _upload_state(uploads: list[dict]) -> str:
    states = {u['state'] for u in uploads}
    for state in _UPLOAD_PRIORITY:
        if state in states:
            return state
    return 'none'


def tracker(day: date, allowed: set[str] | None, start: date | None = None, end: date | None = None) -> dict:
    """Coverage and upload status for ``day``, latest dates per project/circle, and a daily range for gaps."""
    end = end or day
    start = start or end - timedelta(days=DEFAULT_RANGE_DAYS - 1)
    daily = _daily_counts(allowed)
    provenance = _provenance(day, allowed)

    batches = DataImportBatch.objects.select_related('imported_by').filter(kind=DataImportBatch.Kind.RAW_DAILY_CSV).order_by('-uploaded_at')
    if allowed is not None:
        batches = batches.filter(circle__in=allowed)
    uploads_on_day: dict[tuple[str, str], list[dict]] = defaultdict(list)
    latest_upload: dict[tuple[str, str], date] = {}
    latest_import: dict[tuple[str, str], date] = {}
    for b in batches:
        key = (b.project, b.circle)
        if b.reporting_date == day:
            uploads_on_day[key].append(_upload_json(b))
        if b.reporting_date and b.status != DataImportBatch.Status.DISCARDED:
            latest_upload[key] = max(latest_upload.get(key, b.reporting_date), b.reporting_date)
        if b.reporting_date and b.status == DataImportBatch.Status.COMMITTED:
            latest_import[key] = max(latest_import.get(key, b.reporting_date), b.reporting_date)

    range_days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    items = []
    for pair in _pairs(allowed):
        key = (pair['project'], pair['circle'])
        expected = pair['on_air']
        by_date = daily.get(key, {})
        today = by_date.get(day, {})
        usable, invalid = today.get('usable', 0), today.get('invalid', 0)
        with_data = [d for d, r in by_date.items() if r['usable']]
        complete = [d for d, r in by_date.items() if expected and r['usable'] >= expected]
        uploads = uploads_on_day.get(key, [])
        source = provenance.get(key, {})
        items.append({
            'project': pair['project'], 'circle': pair['circle'],
            'sites_total': pair['total'], 'sites_expected': expected,
            'sites_with_data': usable, 'sites_invalid': invalid, 'sites_missing': max(expected - usable - invalid, 0),
            'records_observed': today.get('observed', 0),  # usable records of any master site, On-Air or not
            'coverage_pct': round(100.0 * usable / expected, 2) if expected else None,
            'data_state': data_state(usable, expected),
            'data_source': {'master_workbook': source.get(DataImportBatch.Kind.MASTER_WORKBOOK, 0),
                            'raw_daily_csv': source.get(DataImportBatch.Kind.RAW_DAILY_CSV, 0)},
            'latest_data_date': max(with_data).isoformat() if with_data else None,
            'latest_complete_date': max(complete).isoformat() if complete else None,
            'latest_upload_date': latest_upload[key].isoformat() if key in latest_upload else None,
            'latest_import_date': latest_import[key].isoformat() if key in latest_import else None,
            'upload_state': _upload_state(uploads),
            'uploads': uploads,
            'range': [{'date': d.isoformat(), 'sites_with_data': by_date.get(d, {}).get('usable', 0),
                       'state': data_state(by_date.get(d, {}).get('usable', 0), expected)} for d in range_days],
        })
    return {
        'reporting_date': day.isoformat(),
        'range': {'start': start.isoformat(), 'end': end.isoformat()},
        'scope_rule': SCOPE_RULE, 'usable_rule': USABLE_RULE,
        'notes': [
            'Completeness compares each date with the site master\'s current On-Air sites; the master holds no dated On-Air history.',
            'Data coverage comes from the stored daily records, whichever import wrote them; a CSV upload is reported separately.',
            'No deadline is stored on the server, so nothing is marked late here.',
        ],
        'items': items,
    }
