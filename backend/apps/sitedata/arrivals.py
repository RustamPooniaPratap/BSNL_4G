"""CSV arrival tracking from the data layer: what the daily table actually holds per technology, circle and reporting
date, and the raw CNMC CSV uploads of that date.

Two independent facts per technology/circle and date, never derived from each other:

1. Daily data coverage (sitedata.DailySitePerformance), whatever wrote it (Uptime Master, raw CSV or correction):
   - Expected sites: the dashboard-scope sites of the technology and circle that are On-Air on the date, by their
     Consolidation Matrix Site On-Air Date (on or before the date). The matrix dates give a dated history, so older
     dates are measured against the sites On-Air then.
   - Usable record: every stored record (0-100% and 0-1,440 minutes are enforced by the table); a site-day without a
     record is not reported.
   - Complete: the unit is covered on the date, i.e. the share of expected sites with a record reaches the coverage
     threshold effective on the date (apps.sitedata.reporting, the same rule as every dashboard status). Only reporting
     units active on the date are expected (effective-dated ReportingUnit configuration); others show "no_scope".
   - Provenance: the upload kind that set each record.
2. Raw CSV upload history (UploadBatch of kind raw_csv_4g / raw_csv_lwe) for the date, with its real lifecycle.

Rows: every technology/circle with dashboard-scope sites, plus each active Organization association without sites,
shown as "no scope". A technology's uploads and records only count for that technology: MP 4G never satisfies MP LWE.
Nothing here writes to the database. Deadlines are not stored on the server, so nothing is marked late here.
"""
from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from datetime import date, timedelta

from django.db.models import Count, F, Q

from .models import DailySitePerformance, Site, UploadBatch

MAX_RANGE_DAYS = 92
DEFAULT_RANGE_DAYS = 14
RAW_KINDS = (UploadBatch.Kind.RAW_CSV_4G, UploadBatch.Kind.RAW_CSV_LWE)

SCOPE_RULE = 'Dashboard-scope sites On-Air on the date (Consolidation Matrix Site On-Air Date on or before it)'
USABLE_RULE = 'A stored daily record (0-100% availability, 0-1,440 outage minutes); no record = not reported'

_UPLOAD_PRIORITY = ('imported', 'awaiting_confirmation', 'nothing_to_import', 'blocked', 'failed', 'discarded')

Pairs = set[tuple[str, str]]


def data_state(usable: int, expected: int) -> str:
    if expected == 0:
        return 'no_scope'
    if usable >= expected:
        return 'complete'
    return 'partial' if usable else 'none'


def _in_scope(allowed: Pairs | None, technology: str = 'technology', circle: str = 'circle') -> Q:
    if allowed is None:
        return Q()
    q = Q(pk__in=[])
    for p, c in allowed:
        q |= Q(**{technology: p, circle: c})
    return q


def _pairs(allowed: Pairs | None) -> dict[tuple[str, str], dict]:
    """(technology, circle) -> total sites and the sorted On-Air dates of its sites (no date: never On-Air)."""
    from apps.organization.services import associations
    out: dict[tuple[str, str], dict] = {}
    sites = Site.objects.filter(_in_scope(allowed), reporting_scope=Site.Scope.DASHBOARD).values_list('technology', 'circle', 'on_air_date')
    for technology, circle, on_air in sites:
        entry = out.setdefault((technology, circle), {'total': 0, 'on_air_dates': []})
        entry['total'] += 1
        if on_air is not None:
            entry['on_air_dates'].append(on_air)
    for entry in out.values():
        entry['on_air_dates'].sort()
    for p, c in associations(active_only=True):
        if (p, c) not in out and (allowed is None or (p, c) in allowed):
            out[(p, c)] = {'total': 0, 'on_air_dates': []}
    return dict(sorted(out.items()))


def expected_sites(entry: dict, day: date) -> int:
    return bisect_right(entry['on_air_dates'], day)


def _daily_counts(allowed: Pairs | None, since: date | None = None) -> dict[tuple[str, str], dict[date, dict]]:
    """Per technology/circle and date: records of sites On-Air on that date (usable) and records of any site."""
    qs = DailySitePerformance.objects.order_by().filter(_in_scope(allowed))
    if since is not None:
        qs = qs.filter(report_date__gte=since)
    rows = qs.values('technology', 'circle', 'report_date').annotate(
        usable=Count('id', filter=Q(site__on_air_date__isnull=False, site__on_air_date__lte=F('report_date'))),
        observed=Count('id'))
    out: dict[tuple[str, str], dict[date, dict]] = defaultdict(dict)
    for r in rows:
        out[(r['technology'], r['circle'])][r['report_date']] = r
    return out


def _latest_dates(allowed: Pairs | None, pairs: dict) -> dict[tuple[str, str], tuple[date | None, date | None]]:
    """(latest date with a usable record, latest complete date) per pair, over the whole history."""
    from . import reporting
    daily = _daily_counts(allowed)
    days = sorted({d for by_date in daily.values() for d in by_date})
    cov = reporting.coverage(days, pairs=allowed) if days else {}
    out = {}
    for key, by_date in daily.items():
        with_data = [d for d, r in by_date.items() if r['usable']]
        complete = [d for d in by_date if key in cov.get(d, {}) and cov[d][key]['covered'] and cov[d][key]['with_data']]
        out[key] = (max(with_data) if with_data else None, max(complete) if complete else None)
    return out


def unit_state(cov: dict, key, day: date) -> str:
    """complete / partial / none for an active unit-day; no_scope when the unit is not expected on the date."""
    entry = cov.get(day, {}).get(key)
    if entry is None or entry['expected'] == 0:
        return 'no_scope'
    if entry['covered']:
        return 'complete'
    return 'partial' if entry['with_data'] else 'none'


def _provenance(day: date, allowed: Pairs | None) -> dict[tuple[str, str], dict[str, int]]:
    qs = (DailySitePerformance.objects.order_by().filter(_in_scope(allowed), report_date=day, site__on_air_date__lte=day)
          .values('technology', 'circle', 'batch__kind').annotate(n=Count('id')))
    out: dict[tuple[str, str], dict[str, int]] = defaultdict(dict)
    for r in qs:
        out[(r['technology'], r['circle'])][r['batch__kind']] = r['n']
    return out


def upload_state(batch: UploadBatch) -> str:
    if batch.processing_status == UploadBatch.Processing.COMMITTED:
        return 'imported'
    if batch.processing_status == UploadBatch.Processing.DISCARDED:
        return 'discarded'
    if batch.processing_status == UploadBatch.Processing.FAILED:
        return 'failed'
    if batch.validation_status == UploadBatch.Validation.FAILED:
        return 'blocked'
    return 'awaiting_confirmation' if batch.records_accepted else 'nothing_to_import'


def _upload_json(batch: UploadBatch) -> dict:
    committed = batch.processing_status == UploadBatch.Processing.COMMITTED
    return {
        'id': batch.pk, 'state': upload_state(batch), 'status_label': batch.get_processing_status_display(), 'file': batch.original_filename,
        'uploaded_at': batch.uploaded_at.isoformat(), 'committed_at': batch.committed_at.isoformat() if batch.committed_at else None,
        'uploaded_by': batch.uploaded_by.get_username() if batch.uploaded_by else None,
        'ready_to_import': batch.records_accepted, 'rejected_count': batch.records_rejected,
        'imported': batch.records_accepted if committed else None, 'error': batch.error or None,
    }


def _upload_state(uploads: list[dict]) -> str:
    states = {u['state'] for u in uploads}
    for state in _UPLOAD_PRIORITY:
        if state in states:
            return state
    return 'none'


def tracker(day: date, allowed: Pairs | None, start: date | None = None, end: date | None = None) -> dict:
    """Coverage and upload status for ``day``, latest dates per technology/circle, and a daily range for gaps."""
    end = end or day
    start = start or end - timedelta(days=DEFAULT_RANGE_DAYS - 1)
    pairs = _pairs(allowed)
    daily = _daily_counts(allowed, since=min(start, day))
    latest = _latest_dates(allowed, pairs)
    provenance = _provenance(day, allowed)

    batches = (UploadBatch.objects.select_related('uploaded_by').filter(kind__in=RAW_KINDS).filter(_in_scope(allowed))
               .order_by('-uploaded_at'))
    uploads_on_day: dict[tuple[str, str], list[dict]] = defaultdict(list)
    latest_upload: dict[tuple[str, str], date] = {}
    latest_import: dict[tuple[str, str], date] = {}
    for b in batches:
        key = (b.technology, b.circle)
        if b.reporting_date == day:
            uploads_on_day[key].append(_upload_json(b))
        if b.reporting_date and b.processing_status != UploadBatch.Processing.DISCARDED:
            latest_upload[key] = max(latest_upload.get(key, b.reporting_date), b.reporting_date)
        if b.reporting_date and b.processing_status == UploadBatch.Processing.COMMITTED:
            latest_import[key] = max(latest_import.get(key, b.reporting_date), b.reporting_date)

    range_days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    from . import reporting
    cov = reporting.coverage(set(range_days) | {day}, pairs=allowed)
    items = []
    for key, entry in pairs.items():
        technology, circle = key
        expected = expected_sites(entry, day)
        by_date = daily.get(key, {})
        today = by_date.get(day, {})
        usable = today.get('usable', 0)
        uploads = uploads_on_day.get(key, [])
        source = provenance.get(key, {})
        latest_data, latest_complete = latest.get(key, (None, None))
        items.append({
            'project': technology, 'circle': circle,
            'sites_total': entry['total'], 'sites_expected': expected,
            'sites_with_data': usable, 'sites_invalid': 0, 'sites_missing': max(expected - usable, 0),
            'records_observed': today.get('observed', 0),  # records of any dashboard site, On-Air on the date or not
            'coverage_pct': round(100.0 * usable / expected, 2) if expected else None,
            'coverage_threshold_pct': (cov.get(day, {}).get(key) or {}).get('threshold'),
            'active': key in cov.get(day, {}),
            'data_state': unit_state(cov, key, day),
            'data_source': {'master_workbook': source.get(UploadBatch.Kind.UPTIME_MASTER, 0),
                            'raw_daily_csv': sum(source.get(k, 0) for k in RAW_KINDS),
                            'correction': source.get(UploadBatch.Kind.CORRECTION, 0)},
            'latest_data_date': latest_data.isoformat() if latest_data else None,
            'latest_complete_date': latest_complete.isoformat() if latest_complete else None,
            'latest_upload_date': latest_upload[key].isoformat() if key in latest_upload else None,
            'latest_import_date': latest_import[key].isoformat() if key in latest_import else None,
            'upload_state': _upload_state(uploads),
            'uploads': uploads,
            'range': [{'date': d.isoformat(), 'sites_with_data': by_date.get(d, {}).get('usable', 0),
                       'state': unit_state(cov, key, d)} for d in range_days],
        })
    return {
        'reporting_date': day.isoformat(),
        'range': {'start': start.isoformat(), 'end': end.isoformat()},
        'scope_rule': SCOPE_RULE, 'usable_rule': USABLE_RULE,
        'notes': [
            'Expected sites are those On-Air on each date by their Consolidation Matrix Site On-Air Date; only reporting units '
            'active on the date are expected.',
            'A unit-day is complete when the share of expected sites with data reaches the coverage threshold of the date.',
            'Data coverage comes from the stored daily records, whichever upload set them (Uptime Master, raw CSV or correction); '
            'a CSV upload is reported separately.',
            'No deadline is stored on the server, so nothing is marked late here.',
        ],
        'items': items,
    }
