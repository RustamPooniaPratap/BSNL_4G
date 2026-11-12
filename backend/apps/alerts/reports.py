"""Attachments: the portal's existing reports, built by their own services (no calculation is repeated here).

Each report is limited to a set of (project, circle) pairs: the automation's scope, intersected with the recipient's
access when every recipient gets their own report. A report that cannot be limited to circles (the RCA Master workbook
covers every circle of the period) is only sent to recipients who may see every circle.
"""
from __future__ import annotations

import csv
import io
from datetime import date, timedelta
from pathlib import Path

from django.utils import timezone

XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
CATALOG = {
    'daily_uptime': {'label': 'Daily Uptime Report', 'formats': ['xlsx'], 'scoped': True,
                     'description': 'Site-wise uptime of one reporting date (Excel), as Data Source › Download.'},
    'consolidated': {'label': 'Full Consolidated Uptime Report', 'formats': ['xlsx'], 'scoped': True,
                     'description': 'The 13-sheet consolidated workbook of the month to the reporting date (Excel).'},
    'csv_arrival': {'label': 'CSV Arrival Status Report', 'formats': ['csv'], 'scoped': True,
                    'description': 'Daily data coverage and CSV upload status per project and circle (CSV), as CSV Arrival Tracking.'},
    'rca_master': {'label': 'RCA Master Report (summary and records)', 'formats': ['xlsx'], 'scoped': False,
                   'description': 'The RCA workbook of the reporting period (Excel). Covers every circle: sent only to recipients who may see all circles.'},
}
MAX_EXTRA_BYTES = 10 * 1024 * 1024
EXTRA_TYPES = {'.pdf', '.xlsx', '.xls', '.csv', '.docx', '.pptx', '.png', '.jpg', '.jpeg', '.txt'}


class ReportError(Exception):
    pass


def reporting_day(choice: str, latest: date | None) -> date:
    today = timezone.localdate()
    if choice == 'today':
        return today
    if choice == 'latest' and latest:
        return latest
    return today - timedelta(days=1)


def scope_pairs(project: str, circles: list[str], recipient: set | None) -> set | None:
    """The (project, circle) pairs a report covers: the automation's choice within the recipient's access; None = all."""
    from apps.organization.services import associations
    base = None
    if project or circles:
        base = {(p, c) for p, c in associations(active_only=False) if (not project or p == project) and (not circles or c in circles)}
    if recipient is None:
        return base
    return recipient if base is None else base & recipient


def build(report: str, day_choice: str, pairs: set | None, population: str | None = None) -> tuple[str, bytes, str, str]:
    """(file name, content, mimetype, period label) of one report. Raises ReportError with a reason to show.

    ``population`` (on_air / om_start; the automation's Automation.population, default the portal's DEFAULT_SCOPE): the
    site population of the uptime reports, exactly as the portal download with that ``scope``. The CSV Arrival report
    measures who must submit data (On-Air eligibility of the reporting units) and the RCA Master workbook covers RCA
    records: neither uses the population."""
    if report not in CATALOG:
        raise ReportError(f'Unknown report {report!r}.')
    if pairs is not None and not pairs:
        raise ReportError('No project or circle in this recipient\'s scope.')
    if report in ('daily_uptime', 'consolidated'):
        from apps.dashboard import report_export
        from apps.dashboard.workbook import WorkbookError
        from apps.sitedata import dashboard_source
        from apps.dashboard.metrics import DEFAULT_SCOPE, SCOPES
        population = population or DEFAULT_SCOPE
        if population not in SCOPES:
            raise ReportError(f'Unknown site population {population!r}.')
        # The same dataset, population variant and export functions as the portal download (apps.dashboard.views),
        # limited to the pairs: the email equals the portal file for the same pairs and population.
        try:
            ds = dashboard_source.dataset(pairs, population)
        except WorkbookError as exc:
            raise ReportError(f'Dashboard data is unavailable: {exc}') from exc
        day = reporting_day(day_choice, ds.latest_date)
        if day not in ds.reported_dates and report == 'daily_uptime':
            day = max((d for d in ds.reported_dates if d <= day), default=ds.latest_date)
        label = dashboard_source.SOURCE_LABEL
        try:
            scope = report_export.resolve_scope(ds, None, None, pairs)
            if report == 'daily_uptime':
                name, data = report_export.daily_report(ds, scope, day, label, population)
            else:
                name, data = report_export.consolidated_report(ds, scope, min(day, ds.latest_date), label, population)
        except report_export.ExportError as exc:
            raise ReportError(str(exc)) from exc
        return name, data, XLSX, f'{day:%d %b %Y}' if report == 'daily_uptime' else f'Month to {min(day, ds.latest_date):%d %b %Y}'
    if report == 'csv_arrival':
        from apps.sitedata import arrivals
        day = reporting_day(day_choice, None)
        items = arrivals.tracker(day, pairs)['items']
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(['Project', 'Circle', 'Expected sites', 'Sites with data', 'Missing', 'Coverage %', 'Data state', 'CSV upload', 'Latest data date'])
        for i in items:
            w.writerow([i['project'], i['circle'], i['sites_expected'], i['sites_with_data'], i['sites_missing'], i['coverage_pct'] if i['coverage_pct'] is not None else '',
                        i['data_state'], i['upload_state'], i['latest_data_date'] or ''])
        return f'CSV_Arrival_Status_{day.isoformat()}.csv', ('﻿' + out.getvalue()).encode(), 'text/csv', f'{day:%d %b %Y}'
    # rca_master
    if pairs is not None:
        raise ReportError('The RCA Master Report covers every circle; it is not sent to recipients limited to some circles.')
    from apps.rca import cycles
    from apps.rca.models import RcaRecord
    latest = RcaRecord.objects.order_by('-reporting_date').values_list('reporting_date', flat=True).first()
    day = reporting_day(day_choice, latest)
    cycle = cycles.containing_cycle(day)
    if cycle is None:
        raise ReportError(f'No RCA reporting period contains {day:%d %b %Y}.')
    data, name = cycles.partial_workbook(cycle)
    return name, data, XLSX, cycles.period_label(cycle.reporting_date, cycle.end)


def extra_file(path: str) -> bytes:
    return Path(path).read_bytes()
