"""Which data source powers the dashboard, and the PostgreSQL copy as an Excel-compatible Dataset.

The dashboard calculations (apps.dashboard.metrics) all read an ``apps.dashboard.workbook.Dataset``.
``database_dataset()`` builds the same structure from the imported records, so both sources run the
identical calculations and the frontend needs no second set of charts. One source is used per
response; values are never mixed between Excel and PostgreSQL.
"""
from __future__ import annotations

import calendar
import threading
from datetime import date, timedelta

import numpy as np
import pandas as pd
from django.db.models import Count, Max

from apps.dashboard.workbook import Dataset, WorkbookError, _coverage_warnings, _warning, get_dataset

from .models import AppSetting, DataImportBatch, SiteDailyPerformance, SiteMonthlyPerformance, UptimeSite

SOURCE_KEY = 'dashboard_data_source'
EXCEL, DATABASE = 'excel', 'database'
SOURCES = {EXCEL: 'Excel workbook', DATABASE: 'PostgreSQL database'}

_lock = threading.Lock()
_cache: dict = {'key': None, 'dataset': None}


def active_source() -> str:
    value = AppSetting.objects.filter(key=SOURCE_KEY).values_list('value', flat=True).first()
    return value if value in SOURCES else EXCEL  # Excel stays the default


def set_active_source(source: str, user) -> None:
    AppSetting.objects.update_or_create(key=SOURCE_KEY, defaults={'value': source, 'updated_by': user})


def clear_cache() -> None:
    with _lock:
        _cache.update(key=None, dataset=None)


def current_dataset() -> Dataset:
    """The dataset of the active source (raises WorkbookError when it has no data)."""
    return database_dataset() if active_source() == DATABASE else get_dataset()


def _month_dates(month: date) -> tuple[date, ...]:
    return tuple(month.replace(day=d) for d in range(1, calendar.monthrange(month.year, month.month)[1] + 1))


def completeness() -> dict:
    """What the database holds, and what is missing compared with a full dashboard source."""
    sites = UptimeSite.objects.count()
    last = DataImportBatch.objects.filter(status=DataImportBatch.Status.COMMITTED).order_by('-committed_at').first()
    days = list(SiteDailyPerformance.objects.filter(outage_minutes__isnull=False).values_list('date', flat=True).distinct())
    months_with_daily = sorted({d.replace(day=1) for d in days})
    monthly = sorted(set(SiteMonthlyPerformance.objects.values_list('month', flat=True).distinct()))
    warnings = []
    if not sites:
        warnings.append('The database has no imported sites yet.')
    current = months_with_daily[-1] if months_with_daily else None
    if sites and current is None:
        warnings.append('No daily outage values are imported, so daily and month-to-date figures are unavailable.')
    daily_months = {}
    sites_by_project = dict(UptimeSite.objects.values_list('project').annotate(n=Count('id')))
    for month in months_with_daily:
        reported = sorted(d for d in days if d.replace(day=1) == month)
        gaps = [d.isoformat() for d in _month_dates(month) if d < reported[-1] and d not in reported]
        # Which sites have any value in the month, per project (a 4G-only report leaves LWE empty).
        covered = dict(SiteDailyPerformance.objects.filter(date__gte=month, date__lte=reported[-1], outage_minutes__isnull=False)
                       .values_list('site__project').annotate(n=Count('site', distinct=True)))
        daily_months[month.strftime('%Y-%m')] = {'label': month.strftime('%b-%y'), 'first': reported[0].isoformat(),
                                                 'last': reported[-1].isoformat(), 'days': len(reported), 'gaps': gaps,
                                                 'sites_by_project': {p: covered.get(p, 0) for p in sorted(sites_by_project)}}
        if gaps:
            warnings.append(f"{month:%b-%y} daily data has gaps: {', '.join(gaps[:5])}{'…' if len(gaps) > 5 else ''}.")
        missing = [f'{p} ({covered.get(p, 0):,} of {n:,} sites)' for p, n in sorted(sites_by_project.items()) if covered.get(p, 0) < n]
        if missing:
            warnings.append(f"{month:%b-%y} daily data is incomplete for {'; '.join(missing)}: same-days figures for those sites are unavailable.")
    previous = (current.replace(day=1) - timedelta(days=1)).replace(day=1) if current else None
    if previous and previous.strftime('%Y-%m') not in daily_months:
        warnings.append(f'{previous:%b-%y} daily history is missing (only its monthly totals are imported), so '
                        'same-days comparisons with that month are unavailable. Import the September workbook to add it.')
    return {
        'sites': sites,
        'monthly_records': SiteMonthlyPerformance.objects.count(),
        'daily_records': SiteDailyPerformance.objects.count(),
        'months': [m.strftime('%Y-%m') for m in monthly],
        'daily_months': daily_months,
        'previous_month_daily': bool(previous and previous.strftime('%Y-%m') in daily_months),
        'last_import': None if last is None else {'batch': last.pk, 'file': last.original_filename,
                                                  'committed_at': last.committed_at.isoformat()},
        'empty': sites == 0,
        'warnings': warnings,
    }


def _key() -> tuple:
    return (DataImportBatch.objects.filter(status=DataImportBatch.Status.COMMITTED).aggregate(m=Max('committed_at'))['m'],
            UptimeSite.objects.count())


def database_dataset() -> Dataset:
    key = _key()
    with _lock:
        if _cache['key'] != key or _cache['dataset'] is None:
            _cache['dataset'] = _build()
            _cache['key'] = key
        return _cache['dataset']


def _build() -> Dataset:
    rows = list(UptimeSite.objects.order_by('source_row', 'id').values(
        'id', 'site_id', 'site_name', 'project', 'circle', 'circle_raw', 'source_row', 'oa', 'ba', 'eb', 'ie_name', 'ci_name', 'on_air'))
    if not rows:
        raise WorkbookError('The PostgreSQL database has no imported sites yet. Import the Master workbook on the Database import page.', 'no_workbook')
    position = {r['id']: i for i, r in enumerate(rows)}
    days = {d for d in SiteDailyPerformance.objects.filter(outage_minutes__isnull=False).values_list('date', flat=True).distinct()}
    if not days:
        raise WorkbookError('The PostgreSQL database has no daily outage values yet.', 'no_workbook')
    current = max(days).replace(day=1)
    dates = _month_dates(current)

    def daily_matrix(month_dates):
        matrix = np.full((len(rows), len(month_dates)), np.nan)
        index = {d: i for i, d in enumerate(month_dates)}
        for site, day, outage in SiteDailyPerformance.objects.filter(date__gte=month_dates[0], date__lte=month_dates[-1]).values_list('site_id', 'date', 'outage_minutes'):
            if outage is not None:
                matrix[position[site], index[day]] = outage
        return matrix

    outage = daily_matrix(dates)
    reported_dates = tuple(d for i, d in enumerate(dates) if (~np.isnan(outage[:, i])).any())

    # Monthly history: months before the reporting month (as the Excel loader).
    monthly = SiteMonthlyPerformance.objects.filter(month__lt=current).values_list('site_id', 'month', 'outage_minutes')
    month_list = sorted(set(SiteMonthlyPerformance.objects.filter(month__lt=current).values_list('month', flat=True).distinct()))
    m_index = {m: i for i, m in enumerate(month_list)}
    monthly_outage = np.full((len(rows), len(month_list)), np.nan)
    for site, month, value in monthly:
        if value is not None:
            monthly_outage[position[site], m_index[month]] = value
    months = tuple({'label': m.strftime('%b-%y'), 'start': m, 'days': calendar.monthrange(m.year, m.month)[1]} for m in month_list)

    om = {site: (raw, flag) for site, raw, flag in SiteMonthlyPerformance.objects.filter(month=current).values_list('site_id', 'om_start_raw', 'om_start')}
    has_om_start = any(raw is not None for raw, _ in om.values())
    previous_month = (current - timedelta(days=1)).replace(day=1)
    om_previous = {site: (raw, flag) for site, raw, flag in SiteMonthlyPerformance.objects.filter(month=previous_month).values_list('site_id', 'om_start_raw', 'om_start')}
    has_om_previous = any(raw is not None for raw, _ in om_previous.values())
    sites = pd.DataFrame({
        'site_id': [r['site_id'] for r in rows],
        'site_name': [r['site_name'] for r in rows],
        'report_type': [r['project'] for r in rows],
        'circle': [r['circle'] for r in rows],
        'circle_raw': [r['circle_raw'] for r in rows],
        'source_row': [r['source_row'] for r in rows],
        'oa': [r['oa'] for r in rows], 'ba': [r['ba'] for r in rows], 'eb': [r['eb'] for r in rows],
        'ie_name': [r['ie_name'] for r in rows], 'ci_name': [r['ci_name'] for r in rows],
        'on_air': [bool(r['on_air']) for r in rows],
        'om_start': [bool(om.get(r['id'], (None, False))[1]) for r in rows],
    })
    if has_om_previous:
        sites['om_start_previous'] = [bool(om_previous.get(r['id'], (None, False))[1]) for r in rows]

    warnings = list(_coverage_warnings(sites, dates, outage, reported_dates))
    history = []
    for month in sorted({d.replace(day=1) for d in days if d < current}):
        month_dates = _month_dates(month)
        values = daily_matrix(month_dates)
        reported = int((~np.isnan(values)).any(axis=0).sum())
        history.append({'key': month.strftime('%Y-%m'), 'label': month.strftime('%b-%y'), 'dates': month_dates, 'outage': values})
        warnings.append(_warning('daily_history', 'info', f'{month:%b-%y} daily outage found in the database ({reported} reported days).', reported))
    if not has_om_start:
        warnings.append(_warning('om_start_missing', 'warning', f'No O&M Start values for {current:%b-%y} in the database.', 0))
    last = DataImportBatch.objects.filter(status=DataImportBatch.Status.COMMITTED).order_by('-committed_at').first()
    stamp = last.committed_at.replace(tzinfo=None) if last else pd.Timestamp.now().to_pydatetime()
    return Dataset(
        sites=sites, outage=outage, dates=dates, reported_dates=reported_dates, month_label=current.strftime('%b-%y'),
        has_om_start=has_om_start, previous_om_label=previous_month.strftime('%b-%y') if has_om_previous else None, workbook_name=f'PostgreSQL · {last.original_filename if last else "4G-DB"}',
        modified_at=stamp, loaded_at=pd.Timestamp.now().to_pydatetime(), warnings=tuple(warnings), months=months,
        monthly_outage=monthly_outage, outage_columns=(0, 0), daily_history=tuple(history), sheets=(),
        uploaded_at=stamp,
    )
