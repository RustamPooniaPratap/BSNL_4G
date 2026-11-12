"""Site Portfolio on the new data layer (Phase 4.1). Used only by the Site Portfolio page (/api/site-portfolio/).

- The dashboard Dataset is built from the sitedata tables (dataset.build): sites and attributes from the Consolidation
  Matrix, On-Air / O&M Start from its dates, daily values from the central daily table. It is cached until the data
  changes. It never falls back to the old tables: an empty new layer is an error the page shows.
- On-Air and O&M Start figures use the effective dates (rules.on_air_effective_from / om_effective_from), as the
  validated replay: three variants of the dataset are kept: "all" (every reported day of every site), "on_air" (a
  site's values before its Site On-Air Date in that month are left out) and "om_start" (the same from its O&M Start
  Date). The scope of a request picks the variant; the site populations are the same in all three.
- MTD continuity (rules.mtd_dates): the reporting dates end at the last date of the continuous run from the 1st of
  complete dates, a date being complete when every technology / circle of the site master has values on it (the same
  dates for every user, page and variant). Dates after the first gap or the first incomplete date
  are not offered (listed in the filters response).
- Conversion activity (sites that went On-Air / started O&M in a month) is counted from the matrix dates stored in
  sitedata.Site, in the same shape as dashboard.activity.monthly_activity.
The calculations themselves are the shared dashboard.metrics functions, unchanged.
"""
from __future__ import annotations

import calendar
import dataclasses
import threading
from datetime import date, timedelta

import numpy as np
from django.db.models import Count, Max

from apps.dashboard.workbook import Dataset

from . import dataset as dataset_builder
from . import rules
from .models import DailySitePerformance, MonthlySitePerformance, Site, UploadBatch

_lock = threading.Lock()
_cache: dict = {'key': None, 'dataset': None}
SOURCE_LABEL = 'New data layer (Consolidation Matrix + daily records)'


def _key() -> tuple:
    batches = UploadBatch.objects.filter(processing_status=UploadBatch.Processing.COMMITTED).aggregate(n=Count('id'), last=Max('committed_at'))
    return (batches['n'], batches['last'], Site.objects.count(), DailySitePerformance.objects.count(),
            MonthlySitePerformance.objects.filter(is_current=True).count())


VARIANTS = {'on_air': ('on_air_date', rules.on_air_effective_from), 'om_start': ('om_start_date', rules.om_effective_from)}


def _effective(ds: Dataset, variant: str) -> Dataset:
    """``ds`` with each site's values before its effective date (per month) left out (NaN), for On-Air or O&M Start."""
    column, effective_from = VARIANTS[variant]
    starts = ds.sites[column].tolist()

    def masked(matrix, month_dates):
        out = matrix.copy()
        for i, start in enumerate(starts):
            first = effective_from(start, month_dates[0])
            if first is None:
                out[i, :] = np.nan
            else:
                for j, d in enumerate(month_dates):
                    if d < first:
                        out[i, j] = np.nan
        return out

    history = tuple({**h, 'outage': masked(h['outage'], h['dates'])} for h in ds.daily_history)
    return dataclasses.replace(ds, outage=masked(ds.outage, ds.dates), daily_history=history, _positions={})


def portfolio_dataset(variant: str = 'all') -> Dataset:
    """The cached dataset of the new layer for "all", "on_air" or "om_start" (raises WorkbookError when the new layer
    has no sites or no daily records)."""
    key = _key()
    with _lock:
        if _cache['key'] != key or _cache['dataset'] is None:
            built = dataclasses.replace(dataset_builder.build(), workbook_name=SOURCE_LABEL)
            _cache['dataset'] = {'all': built, **{v: _effective(built, v) for v in VARIANTS}}
            _cache['key'] = key
        return _cache['dataset'][variant]


def clear_cache() -> None:
    with _lock:
        _cache.update(key=None, dataset=None)


def dates_with_data(ds: Dataset) -> list[date]:
    """Dates of the reporting month on which at least one site of ``ds`` has a value."""
    if not len(ds.sites):
        return []
    has = ~np.isnan(ds.outage)
    return [d for i, d in enumerate(ds.dates) if has[:, i].any()]


def complete_dates(ds: Dataset) -> list[date]:
    """Complete reporting dates of the month: from the new layer (dataset.completeness: every technology / circle of
    the whole site master has values, the same for every user and page); a source without that information (a single
    workbook) counts every date with data."""
    if ds.complete_dates is not None:
        return list(ds.complete_dates)
    return dates_with_data(ds)


def continuous(ds: Dataset) -> Dataset:
    """``ds`` with its reporting dates = the dates of the month on which its own sites have data (a restricted dataset
    therefore follows its own units: 4G and LWE are independent), plus the Complete / Provisional status of each date and
    of the month to date over the dataset's own reporting units (apps.sitedata.reporting). Dates are never dropped
    because another unit is missing (approved rule B-7)."""
    from . import reporting
    memo = ds._memo.get('continuous')
    if memo is not None:
        return memo
    have = tuple(dates_with_data(ds))
    result = ds if have == tuple(ds.reported_dates) else dataclasses.replace(ds, reported_dates=have, _positions={})
    units = reporting.units_of(ds)
    latest = have[-1] if have else None
    # Statuses run to the latest reporting date of the whole data layer, so a unit that stopped reporting shows its
    # missing days as Provisional instead of looking complete up to its own last date.
    layer_dates = [d for d in ds.dates if ds.unit_coverage and d in ds.unit_coverage]
    status_end = max([*layer_dates, *([latest] if latest else [])], default=None)
    status_dates = [d for d in ds.dates if status_end and d <= status_end and (d in have or d in layer_dates)]
    statuses = [reporting.date_status(ds.unit_coverage, d, units) for d in status_dates] if ds.unit_coverage is not None else []
    provisional = [s['date'] for s in statuses if s['status'] != reporting.COMPLETE]
    mtd = (reporting.period_status(ds.unit_coverage, [d for d in ds.dates if d <= status_end], status_end, units)
           if ds.unit_coverage is not None and status_end else None)
    result._memo['continuity'] = {'dates_with_data': [d.isoformat() for d in have], 'continuous_until': latest.isoformat() if latest else None,
                                  'excluded_after_gap': [], 'incomplete_dates': provisional,
                                  'date_status': statuses, 'mtd_status': mtd['status'] if mtd else None,
                                  'missing': mtd['missing'] if mtd else []}
    ds._memo['continuous'] = result
    return result


def with_dates_of(ds: Dataset, reference: Dataset) -> Dataset:
    """``ds`` with the reporting dates of ``reference`` (so every variant uses the same continuous dates)."""
    if tuple(ds.reported_dates) == tuple(reference.reported_dates):
        ds._memo['continuity'] = reference._memo.get('continuity')
        return ds
    key = tuple(reference.reported_dates)
    cache = ds._memo.setdefault('with_dates', {})
    if key not in cache:
        cache[key] = dataclasses.replace(ds, reported_dates=key, _positions={})
        cache[key]._memo['continuity'] = reference._memo.get('continuity')
    return cache[key]


def month_dates(ds: Dataset, month_keys: list[str]) -> list[date]:
    """The reporting dates of whole months: the continuous dates of the reporting month, and every date with data of
    earlier months (daily_history). Missing dates are not counted (never treated as zero outage)."""
    out = []
    current = ds.dates[0].strftime('%Y-%m') if ds.dates else None
    for key in month_keys:
        if key == current:
            out += list(ds.reported_dates)
            continue
        for entry in ds.daily_history:
            if entry['key'] == key:
                has = ~np.isnan(entry['outage'])
                out += [d for j, d in enumerate(entry['dates']) if has[:, j].any()]
    return sorted(set(out))


def continuity(ds: Dataset) -> dict:
    return ds._memo.get('continuity') or {'dates_with_data': [], 'continuous_until': None, 'excluded_after_gap': []}


def monthly_activity(month: date, report_type: str | None = None, circle: str | None = None, pairs=None) -> dict:
    """Sites that went On-Air / started O&M in ``month`` and the month before, from the matrix dates in sitedata.Site
    (dashboard scope only). A month later than the latest date of a kind is not covered (None, never 0)."""
    sites = Site.objects.filter(reporting_scope=Site.Scope.DASHBOARD)
    if report_type:
        sites = sites.filter(technology=report_type)
    if circle:
        sites = sites.filter(circle=circle.upper())
    records = [{'report_type': t, 'circle': c, 'on_air': a, 'om_start': o}
               for t, c, a, o in sites.values_list('technology', 'circle', 'on_air_date', 'om_start_date')
               if pairs is None or (t, c) in pairs]
    every = Site.objects.filter(reporting_scope=Site.Scope.DASHBOARD)
    latest = {'on_air': every.aggregate(m=Max('on_air_date'))['m'], 'om_start': every.aggregate(m=Max('om_start_date'))['m']}
    this = month.replace(day=1)
    last = (this - timedelta(days=1)).replace(day=1)

    def period(start: date, kind: str) -> dict:
        end = date(start.year, start.month, calendar.monthrange(start.year, start.month)[1])
        covered = latest[kind] is not None and latest[kind] >= start
        count = sum(1 for r in records if r[kind] and start <= r[kind] <= end) if covered else None
        return {'count': count, 'covered_to': min(latest[kind], end).isoformat() if covered else None, 'complete': bool(covered and latest[kind] >= end)}

    result = {}
    for kind in ('on_air', 'om_start'):
        now, before = period(this, kind), period(last, kind)
        result[kind] = {'this_month': now, 'last_month': before,
                        'change': now['count'] - before['count'] if now['count'] is not None and before['count'] is not None else None,
                        'latest_date': latest[kind].isoformat() if latest[kind] else None}
    matrix = UploadBatch.objects.filter(kind=UploadBatch.Kind.CONSOLIDATION_MATRIX, processing_status=UploadBatch.Processing.COMMITTED).order_by('-committed_at').first()
    return {'source': f'{matrix.original_filename} (upload #{matrix.pk}, new data layer)' if matrix else None, 'sites': len(records),
            'month': {'key': this.strftime('%Y-%m'), 'label': this.strftime('%b-%y')},
            'previous_month': {'key': last.strftime('%Y-%m'), 'label': last.strftime('%b-%y')}, **result}
