"""The dashboard Dataset (apps.dashboard.workbook.Dataset) built from the new data layer.

Used to verify that the new tables can populate every existing dashboard page (Team Performance, All KPI's, ...)
before the cutover. It is not connected to any page: uptimedb.datasource still serves the dashboard.

Differences from uptimedb.datasource._build, all from the approved rules:
- sites: only the dashboard reporting scope (outside-scope sites are excluded); attributes from the matrix;
- O&M Start: from the matrix O&M Start Date (rules.om_effective_from): a site is O&M Start in a month when its date
  falls on or before the month's last day; no date = not O&M Start (the site is flagged for review). The dashboard's
  existing metrics apply the flag to the whole month; the om_start monthly results (calculations.py) count only the days
  from the date. Columns om_start_date / om_effective_from are included for that reason.
- On-Air: the same rule with the matrix Site On-Air Date (on_air_effective_from); the on_air column is True when the
  site is On-Air in the reporting month.
- monthly history: the months calculated from daily records (MonthlySitePerformance, all reported days).
- reporting month (``reporting_month``): the latest month whose 1st is a complete reporting date, i.e. a date on which
  every technology / circle of the site master has daily records. A later month that has only some files (for example
  a November CSV of one circle) does not replace a complete month; its dates are listed as pending until complete.
"""
from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, timedelta

import numpy as np
import pandas as pd

from apps.dashboard.workbook import Dataset, WorkbookError, _coverage_warnings, _warning

from .models import DailySitePerformance, MonthlySitePerformance, Site, UploadBatch
from .rules import om_effective_from, on_air_effective_from


def _month_dates(month: date) -> tuple[date, ...]:
    return tuple(month.replace(day=d) for d in range(1, calendar.monthrange(month.year, month.month)[1] + 1))


def completeness() -> dict:
    """Dates with daily records, the expected technology / circle units, and the complete dates (every expected unit
    has records on the date). Expected units: those of the dashboard site master that report at all (have any daily
    record), so a unit that has never reported (e.g. a circle not yet in operation) does not block every date, while a
    unit that reports but is missing on a date makes that date incomplete."""
    by_date: dict[date, set] = defaultdict(set)
    for day, technology, circle in (DailySitePerformance.objects.filter(site__reporting_scope=Site.Scope.DASHBOARD)
                                    .values_list('report_date', 'site__technology', 'site__circle').distinct()):
        by_date[day].add((technology, circle))
    expected = set().union(*by_date.values()) if by_date else set()
    complete = sorted(d for d, units in by_date.items() if expected and units >= expected)
    return {'expected_units': sorted(expected), 'dates': sorted(by_date), 'complete': complete,
            'missing_units': {d: sorted(expected - units) for d, units in by_date.items() if not units >= expected}}


def reporting_month(info: dict) -> date | None:
    """The latest month whose 1st is a complete reporting date; without any, the month of the latest date with data."""
    firsts = [d for d in info['complete'] if d.day == 1]
    if firsts:
        return max(firsts)
    return max(info['dates']).replace(day=1) if info['dates'] else None


def build() -> Dataset:
    rows = list(Site.objects.filter(reporting_scope=Site.Scope.DASHBOARD).order_by('technology', 'circle', 'bsnl_site_id').values(
        'id', 'bsnl_site_id', 'site_name', 'technology', 'circle', 'circle_raw', 'source_row', 'oa', 'ba', 'ie_name', 'ci_name', 'on_air',
        'uptime_master_fields', 'om_start_date', 'on_air_date'))
    if not rows:
        raise WorkbookError('The new site master has no sites yet. Import the Consolidation Matrix.', 'no_workbook')
    position = {r['id']: i for i, r in enumerate(rows)}
    info = completeness()
    days = set(info['dates'])
    if not days:
        raise WorkbookError('The new data layer has no daily records yet.', 'no_workbook')
    current = reporting_month(info)
    dates = _month_dates(current)
    pending = sorted(d for d in days if d > dates[-1])  # a later month that is not complete yet: not used

    def daily_matrix(month_dates):
        matrix = np.full((len(rows), len(month_dates)), np.nan)
        index = {d: i for i, d in enumerate(month_dates)}
        for site, day, outage in (DailySitePerformance.objects.filter(report_date__gte=month_dates[0], report_date__lte=month_dates[-1])
                                  .values_list('site_id', 'report_date', 'outage_minutes')):
            if site in position:
                matrix[position[site], index[day]] = outage
        return matrix

    outage = daily_matrix(dates)
    reported_dates = tuple(d for i, d in enumerate(dates) if (~np.isnan(outage[:, i])).any())

    history_records = MonthlySitePerformance.objects.filter(month__lt=current, is_current=True, calculation_category=MonthlySitePerformance.Category.DAILY_DERIVED)
    # History months: those with monthly results and those with daily records (the figures come from the daily records,
    # metrics.month_values; the monthly results are their stored companions, reconciled with them).
    month_list = sorted(set(history_records.values_list('month', flat=True)) | {d.replace(day=1) for d in days if d < current})
    m_index = {m: i for i, m in enumerate(month_list)}
    monthly_outage = np.full((len(rows), len(month_list)), np.nan)
    for site, month, value in history_records.values_list('site_id', 'month', 'total_outage_minutes'):
        if site in position:
            monthly_outage[position[site], m_index[month]] = value
    months = tuple({'label': m.strftime('%b-%y'), 'start': m, 'days': calendar.monthrange(m.year, m.month)[1]} for m in month_list)

    previous_month = (current - timedelta(days=1)).replace(day=1)
    effective = [om_effective_from(r['om_start_date'], current) for r in rows]
    effective_previous = [om_effective_from(r['om_start_date'], previous_month) for r in rows]
    has_dates = any(r['om_start_date'] for r in rows)
    sites = pd.DataFrame({
        'site_id': [r['bsnl_site_id'] for r in rows],
        'site_name': [r['site_name'] for r in rows],
        'report_type': [r['technology'] for r in rows],
        'circle': [r['circle'] for r in rows],
        'circle_raw': [r['circle_raw'] for r in rows],
        'source_row': [r['source_row'] for r in rows],
        'oa': [r['oa'] for r in rows], 'ba': [r['ba'] for r in rows],
        'eb': [(r['uptime_master_fields'] or {}).get('EB', '') for r in rows],
        'ie_name': [r['ie_name'] for r in rows], 'ci_name': [r['ci_name'] for r in rows],
        'on_air': [on_air_effective_from(r['on_air_date'], current) is not None for r in rows],
        'on_air_date': [r['on_air_date'] for r in rows],
        'om_start': [e is not None for e in effective],
        'om_start_date': [r['om_start_date'] for r in rows],
        'om_effective_from': effective,
    })
    if has_dates:
        sites['om_start_previous'] = [e is not None for e in effective_previous]

    warnings = list(_coverage_warnings(sites, dates, outage, reported_dates))
    if pending:
        missing = info['missing_units'].get(pending[0], [])
        warnings.append(_warning('pending_month', 'info',
                                 f"{pending[0]:%b-%y} has records for {len(pending)} date(s) ({pending[0]:%d %b}–{pending[-1]:%d %b}) but is not "
                                 f"complete yet ({len(missing)} technology / circle unit(s) without data on {pending[0]:%d %b}): "
                                 f"{current:%b-%y} stays the reporting month.", len(pending)))
    history = []
    for month in sorted({d.replace(day=1) for d in days if d < current}):
        month_dates = _month_dates(month)
        values = daily_matrix(month_dates)
        history.append({'key': month.strftime('%Y-%m'), 'label': month.strftime('%b-%y'), 'dates': month_dates, 'outage': values})
    if not has_dates:
        warnings.append(_warning('om_start_missing', 'warning', 'No site has an O&M Start Date in the Consolidation Matrix.', 0))
    last = UploadBatch.objects.filter(processing_status=UploadBatch.Processing.COMMITTED).order_by('-committed_at').first()
    stamp = last.committed_at.replace(tzinfo=None) if last else pd.Timestamp.now().to_pydatetime()
    return Dataset(
        sites=sites, outage=outage, dates=dates, reported_dates=reported_dates, month_label=current.strftime('%b-%y'),
        has_om_start=has_dates, previous_om_label=previous_month.strftime('%b-%y') if has_dates else None,
        workbook_name='New data layer', modified_at=stamp, loaded_at=pd.Timestamp.now().to_pydatetime(), warnings=tuple(warnings),
        months=months, monthly_outage=monthly_outage, outage_columns=(0, 0), daily_history=tuple(history), sheets=(), uploaded_at=stamp,
        complete_dates=tuple(d for d in info['complete'] if dates[0] <= d <= dates[-1]),
    )
