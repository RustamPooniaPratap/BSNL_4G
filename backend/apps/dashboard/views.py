"""HTTP layer for the dashboard: validate parameters, call metrics, shape responses."""
import math

from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from apps.accounts.access import pairs_for
from apps.accounts.permissions import AdminForWrites, Can, IsAdminRole
from apps.common.exceptions import ServiceUnavailable

from . import metrics, report_export, store
from .crosscheck import calculation_check
from .serializers import (DailyExportSerializer, MonthlySerializer, PeriodSerializer, RecordsSerializer, SnapshotSerializer,
                          TeamMonthlySerializer, TeamSerializer, TrendSerializer)
from .upload import UploadRejected, accept_upload
from .workbook import SHEET_NAME, SHEET_ROLES, WorkbookError, get_dataset


def _dataset(request, action: str = 'view'):
    """The dataset of the active source (Excel workbook or PostgreSQL), the same for every endpoint, limited to the
    project/circle pairs on which the user has the Dashboard permission (accounts.access): KPIs, charts, tables,
    searches, filter options and exports never include other circles."""
    from apps.uptimedb.datasource import current_dataset

    from .scope import restrict
    try:
        dataset = current_dataset()
    except WorkbookError as exc:
        raise ServiceUnavailable(str(exc), error_code=exc.code) from exc
    dataset = restrict(dataset, pairs_for(request.user, 'dashboard', action))
    return _team(request, dataset)


def _team(request, dataset):
    """CI / IE Performance > Site Details: with team_group, team, team_project and team_circle, only that person's sites
    (inside what the user may see). Applied on the server, so the URL cannot widen it; absent: unchanged."""
    p = request.query_params
    if not any(p.get(k) for k in ('team_group', 'team', 'team_project', 'team_circle')):
        return dataset
    group, name = p.get('team_group', ''), p.get('team', '').strip()
    project, circle = p.get('team_project', ''), p.get('team_circle', '').strip().upper()
    if group not in ('ci', 'ie') or not name or not project or not circle:
        raise ValidationError({'team': 'A CI / IE filter needs team_group (ci or ie), team, team_project and team_circle.'})
    from .scope import restrict_team
    return restrict_team(dataset, group, name, project, circle)


def _validated(serializer_class, request, dataset) -> dict:
    serializer = serializer_class(data=request.query_params, context={'dataset': dataset})
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def _source(dataset) -> dict:
    return {
        'workbook': dataset.workbook_name,
        'sheet': SHEET_NAME,
        'modified_at': dataset.modified_at.isoformat(timespec='seconds'),
        'loaded_at': dataset.loaded_at.isoformat(timespec='seconds'),
        'uploaded_at': dataset.uploaded_at.isoformat(timespec='seconds') if dataset.uploaded_at else None,
        'latest_reporting_date': dataset.latest_date.isoformat() if dataset.latest_date else None,
    }


def _applied(params: dict) -> dict:
    selection = params['selection']
    return {'report_type': selection.report_type, 'circle': selection.circle, 'scope': selection.scope}


@api_view(['GET'])
@permission_classes([Can('dashboard', 'view')])
def filters_view(request):
    from apps.organization.services import merge_filter_options
    dataset = _dataset(request)
    return Response({**merge_filter_options(metrics.filter_options(dataset), pairs_for(request.user, 'dashboard', 'view')),
                     'source': _source(dataset)})


@api_view(['GET'])
@permission_classes([Can('dashboard', 'view')])
def summary_view(request):
    dataset = _dataset(request)
    params = _validated(SnapshotSerializer, request, dataset)
    result = metrics.summary(dataset, params['selection'], params['reporting_date'])
    return Response({**result, 'filters': _applied(params), 'source': _source(dataset)})


@api_view(['GET'])
@permission_classes([Can('dashboard', 'view')])
def trends_view(request):
    dataset = _dataset(request)
    params = _validated(TrendSerializer, request, dataset)
    result = metrics.trend(dataset, params['selection'], params['start_date'], params['end_date'])
    return Response({
        **result,
        'filters': {**_applied(params), 'start_date': params['start_date'].isoformat(),
                    'end_date': params['end_date'].isoformat()},
        'source': _source(dataset),
    })


@api_view(['GET'])
@permission_classes([Can('dashboard', 'view')])
def breakdowns_view(request):
    dataset = _dataset(request)
    params = _validated(SnapshotSerializer, request, dataset)
    result = metrics.breakdown(dataset, params['selection'], params['reporting_date'])
    return Response({**result, 'filters': _applied(params), 'source': _source(dataset)})


@api_view(['GET'])
@permission_classes([Can('dashboard', 'view')])
def records_view(request):
    dataset = _dataset(request)
    params = _validated(RecordsSerializer, request, dataset)
    table = metrics.site_table(dataset, params['selection'], params['reporting_date'])
    table = metrics.search_sites(table, params['search'], params['bucket'] or None, params['bucket_basis'])
    table = metrics.filter_team(table, params['ci_name'], params['ie_name'])
    if params['below_sla']:  # NSLA: MTD uptime below 98.5% (the penalty buckets, as on CI & IE Performance)
        table = table[table['bucket'].isin(metrics.PENALTY_BUCKETS)]
    table = metrics.sort_sites(table, params['sort'], params['direction'] == 'desc')

    page, page_size, count = params['page'], params['page_size'], len(table)
    pages = max(math.ceil(count / page_size), 1)
    start = (page - 1) * page_size
    rows = table.iloc[start:start + page_size]
    return Response({
        'reporting_date': params['reporting_date'].isoformat(),
        'count': count,
        'page': page,
        'page_size': page_size,
        'pages': pages,
        'records': [_record(row) for row in rows.to_dict('records')],
        'filters': {**_applied(params), 'search': params['search'], 'bucket': params['bucket'] or None,
                    'ci_name': params['ci_name'] or None, 'ie_name': params['ie_name'] or None,
                    'bucket_basis': params['bucket_basis'], 'below_sla': params['below_sla'],
                    'sort': params['sort'], 'direction': params['direction']},
        'source': _source(dataset),
    })


@api_view(['GET'])
@permission_classes([Can('dashboard', 'view')])
def record_detail_view(request, site_id):
    dataset = _dataset(request)
    report_type = request.query_params.get('report_type') or None
    matches = (dataset.sites['site_id'] == site_id).to_numpy()
    if report_type:
        matches &= (dataset.sites['report_type'] == report_type).to_numpy()
    indexes = matches.nonzero()[0]
    if len(indexes) == 0:
        raise NotFound('No site with this btsIpId exists in the Master workbook.')
    if len(indexes) > 1:
        raise ValidationError({'report_type': 'This btsIpId exists in more than one report type; specify report_type.'})
    day = dataset.latest_date
    if day is None:
        raise ServiceUnavailable('The workbook has no reported dates yet.')
    return Response({**metrics.site_detail(dataset, int(indexes[0]), day), 'source': _source(dataset)})


@api_view(['GET'])
@permission_classes([Can('dashboard', 'view')])
def source_view(request):
    dataset = _dataset(request)
    sites = dataset.sites
    latest = dataset.latest_date
    expected = [d for d in dataset.dates if latest and d <= latest]
    return Response({
        'status': 'warning' if any(w['severity'] == 'warning' for w in dataset.warnings) else 'ok',
        'source': _source(dataset),
        'month': dataset.month_label,
        'site_counts': {
            'total': len(sites),
            'by_report_type': {k: int(v) for k, v in sites['report_type'].value_counts().sort_index().items()},
            'on_air': int(sites['on_air'].sum()),
            'om_start': int(sites['om_start'].sum()) if dataset.has_om_start else None,
        },
        'reporting_dates': [d.isoformat() for d in dataset.reported_dates],
        'missing_dates': [d.isoformat() for d in expected if d not in dataset.reported_dates],
        'unreported_dates_in_month': [d.isoformat() for d in dataset.dates if latest is None or d > latest],
        'warnings': list(dataset.warnings),
        'sheets': _sheets(dataset),
        'calculation_check': calculation_check(dataset),
    })


@api_view(['GET'])
@permission_classes([Can('dashboard', 'view')])
def alerts_view(request):
    dataset = _dataset(request)
    items = metrics.alerts(dataset, timezone.localdate())
    counts = {level: sum(1 for a in items if a['severity'] == level) for level in metrics.SEVERITY_RANK}
    return Response({'alerts': items, 'counts': counts, 'source': _source(dataset)})


@api_view(['GET'])
@permission_classes([Can('dashboard', 'view')])
def period_view(request):
    """KPI for the trend period selected in the filter bar."""
    dataset = _dataset(request)
    params = _validated(PeriodSerializer, request, dataset)
    result = metrics.period_summary(dataset, params['selection'], dates=params['dates'],
                                    month_keys=params['month_keys'], label=params['label'])
    return Response({**result, 'filters': _applied(params), 'source': _source(dataset)})


@api_view(['GET'])
@permission_classes([Can('dashboard', 'view')])
def thresholds_view(request):
    dataset = _dataset(request)
    params = _validated(SnapshotSerializer, request, dataset)
    result = metrics.threshold_analysis(dataset, params['selection'], params['reporting_date'],
                                        period=request.query_params.get('period') or None,
                                        compare=request.query_params.get('vs') or None)
    return Response({**result, 'filters': _applied(params), 'source': _source(dataset)})


@api_view(['GET'])
@permission_classes([Can('dashboard', 'view')])
def monthly_view(request):
    dataset = _dataset(request)
    params = _validated(MonthlySerializer, request, dataset)
    result = metrics.monthly(dataset, params['selection'], params['reporting_date'], params['months'])
    return Response({**result, 'filters': _applied(params), 'source': _source(dataset)})


@api_view(['GET'])
@permission_classes([IsAdminRole])  # Team performance: Admins only
def teams_view(request):
    dataset = _dataset(request)
    params = _validated(TeamSerializer, request, dataset)
    result = metrics.team_performance(dataset, params['selection'], params['reporting_date'], params['group'])
    return Response({**result, 'filters': _applied(params), 'source': _source(dataset)})



@api_view(['GET'])
@permission_classes([IsAdminRole])  # CI & IE Performance is part of Team performance: Admins only
def team_monthly_view(request):
    dataset = _dataset(request)
    params = _validated(TeamMonthlySerializer, request, dataset)
    try:
        result = metrics.team_monthly_nsla(dataset, params['selection'], params['reporting_date'], params['group'],
                                           month=params['month'] or None)
    except ValueError as exc:
        raise ValidationError({'month': str(exc)})
    return Response({**result, 'filters': _applied(params), 'source': _source(dataset)})


@api_view(['GET'])
@permission_classes([IsAdminRole])  # Circle-wise Top Performers is part of Team performance: Admins only
def team_top_view(request):
    dataset = _dataset(request)
    params = _validated(TeamMonthlySerializer, request, dataset)
    try:
        result = metrics.circle_top_performers(dataset, params['selection'], params['reporting_date'],
                                               month=params['month'] or None)
    except ValueError as exc:
        raise ValidationError({'month': str(exc)})
    return Response({**result, 'filters': _applied(params), 'source': _source(dataset)})

@api_view(['GET', 'POST'])
@parser_classes([MultiPartParser, FormParser])
@permission_classes([AdminForWrites])  # everyone may see the active workbook; only Admins replace it
def workbook_view(request):
    """GET: the active Master workbook. POST: upload a new one (form field "file")."""
    if request.method == 'GET':
        return Response(_workbook_status(request=request))

    uploaded = request.FILES.get('file')
    if not uploaded:
        raise ValidationError({'file': 'Choose the consolidated Master workbook (.xlsx) to upload.'})
    previous = store.active_record()
    try:
        dataset, _ = accept_upload(uploaded)
    except UploadRejected as exc:
        kept = (f" The previously loaded workbook '{previous['original_name']}' is still in use."
                if previous else ' No workbook is loaded yet.')
        return Response(
            {'error': f'{exc}{kept}', 'details': {'problems': exc.problems, 'previous_workbook_kept': bool(previous)}},
            status=exc.status,
        )
    # The workbook is replaced either way; the status describes whichever source the dashboard uses.
    from apps.uptimedb.datasource import EXCEL, active_source
    return Response({'status': 'accepted', **_workbook_status(dataset if active_source() == EXCEL else None, request=request)},
                    status=status.HTTP_201_CREATED)


def _workbook_status(dataset=None, request=None) -> dict:
    """The data behind the dashboard: the active source's dataset (Excel workbook or PostgreSQL)."""
    from apps.uptimedb.datasource import active_source
    source = active_source()
    if dataset is None:
        try:
            dataset = _dataset(request)  # a restricted user's counts cover their circles only
        except ServiceUnavailable as exc:
            return {'active': None, 'message': str(exc.detail), 'code': exc.error_code, 'data_source': source}
    sites = dataset.sites
    return {
        'data_source': source,
        'active': {
            **_source(dataset),
            'data_source': source,
            'month': dataset.month_label,
            'sites': len(sites),
            'by_report_type': {k: int(v) for k, v in sites['report_type'].value_counts().sort_index().items()},
            'circles': sorted(sites['circle'].unique()),
            'reporting_dates': [d.isoformat() for d in dataset.reported_dates],
            'warning_count': sum(1 for w in dataset.warnings if w['severity'] == 'warning'),
            'warnings': list(dataset.warnings),
            'sheets': _sheets(dataset),
        },
    }


def _sheets(dataset) -> list[dict]:
    return [{'name': name, 'role': SHEET_ROLES.get(name, 'Not used by the dashboard')} for name in dataset.sheets]


def _record(row: dict) -> dict:
    def number(value, digits):
        return None if value is None or (isinstance(value, float) and math.isnan(value)) else round(float(value), digits)

    return {
        'site_id': row['site_id'],
        'site_name': row['site_name'],
        'report_type': row['report_type'],
        'circle': row['circle'],
        'oa': row['oa'],
        'ba': row['ba'],
        'eb': row['eb'],
        'on_air': bool(row['on_air']),
        'om_start': bool(row['om_start']),
        'outage_minutes': number(row['outage_minutes'], 2),
        'daily_uptime_pct': number(row['daily_uptime_pct'], 4),
        'mtd_uptime_pct': number(row['mtd_uptime_pct'], 4),
        'bucket': row['bucket'],
        'ie_name': row['ie_name'],
        'ci_name': row['ci_name'],
    }


@api_view(['GET'])
@permission_classes([Can('dashboard', 'view')])
def conversion_activity_view(request):
    """Sites that went On-Air / started O&M this month and last month, from the escalation matrix's dates.

    ``month`` (YYYY-MM, default: the current reporting month), ``report_type`` and ``circle`` filter it.
    """
    from datetime import date as _date

    from .activity import ActivityUnavailable, monthly_activity
    raw = request.query_params.get('month')
    try:
        month = _date.fromisoformat(f'{raw}-01') if raw else None
    except ValueError:
        return Response({'error': f'"{raw}" is not a month (YYYY-MM).', 'details': {}}, status=400)
    if month is None:
        try:
            month = _dataset(request).dates[0]
        except Exception:  # no Master data: fall back to today's month
            month = _date.today()
    try:
        return Response(monthly_activity(month, request.query_params.get('report_type') or None, request.query_params.get('circle') or None,
                                         pairs=pairs_for(request.user, 'dashboard', 'view')))
    except ActivityUnavailable as exc:
        return Response({'error': str(exc), 'details': {}}, status=404)


@api_view(['GET'])
@permission_classes([Can('dashboard', 'view')])
def om_heads_view(request):
    """O&M Head per circle from the reference sheet in Data/reference (not part of the Master workbook)."""
    from .reference import om_heads
    data, pairs = om_heads(), pairs_for(request.user, 'dashboard', 'view')
    if pairs is not None:  # the heads of the user's circles only
        data = {**data, 'heads': [h for h in data['heads'] if (h.get('report_type'), str(h.get('circle', '')).upper()) in pairs]}
    return Response(data)


# --- Excel downloads (Daily Uptime Report, Full Consolidated Report) ---------------------------------------------

def _export_scope(request, dataset, selection):
    """The selected project/circle, limited on the server to the project/circle pairs the user may use (accounts.scope)."""
    return report_export.resolve_scope(dataset, selection.report_type, selection.circle, pairs_for(request.user, 'dashboard', 'export'))


def _source_label(dataset) -> str:
    from apps.uptimedb.datasource import SOURCES, active_source
    return f'{SOURCES[active_source()]} ({dataset.workbook_name})'


def _xlsx(name: str, data: bytes):
    from django.http import HttpResponse
    response = HttpResponse(data, content_type=report_export.XLSX)
    response['Content-Disposition'] = f'attachment; filename="{name}"'
    response['Access-Control-Expose-Headers'] = 'Content-Disposition'
    return response


def _export_error(exc: report_export.ExportError):
    return Response({'error': str(exc), 'details': {}}, status=exc.status)


@api_view(['GET'])
@permission_classes([Can('dashboard', 'export')])
def export_daily_view(request):
    """Daily Uptime Report (.xlsx) for one date, project and circle, from the active source."""
    from apps.accounts.audit import audit
    dataset = _dataset(request, 'export')
    params = _validated(DailyExportSerializer, request, dataset)
    try:
        scope = _export_scope(request, dataset, params['selection'])
        name, data = report_export.daily_report(dataset, scope, params['date'], _source_label(dataset))
    except report_export.ExportError as exc:
        return _export_error(exc)
    audit('report_exported', request, report='daily', project=scope.project_label, circle=scope.circle_label, date=params['date'].isoformat())
    return _xlsx(name, data)


@api_view(['GET'])
@permission_classes([Can('dashboard', 'export')])
def export_consolidated_view(request):
    """Full Consolidated Report (.xlsx, 13 sheets): the month to the reporting date, for the project and circle."""
    from apps.accounts.audit import audit
    dataset = _dataset(request, 'export')
    params = _validated(SnapshotSerializer, request, dataset)
    try:
        scope = _export_scope(request, dataset, params['selection'])
        name, data = report_export.consolidated_report(dataset, scope, params['reporting_date'], _source_label(dataset))
    except report_export.ExportError as exc:
        return _export_error(exc)
    audit('report_exported', request, report='consolidated', project=scope.project_label, circle=scope.circle_label,
          date=params['reporting_date'].isoformat())
    return _xlsx(name, data)
