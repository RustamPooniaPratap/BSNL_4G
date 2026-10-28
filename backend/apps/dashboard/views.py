"""HTTP layer for the dashboard: validate parameters, call metrics, shape responses."""
import math

from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from apps.accounts.permissions import AdminForWrites, IsAdminRole
from apps.common.exceptions import ServiceUnavailable

from . import metrics, store
from .crosscheck import calculation_check
from .serializers import MonthlySerializer, PeriodSerializer, RecordsSerializer, SnapshotSerializer, TeamMonthlySerializer, TeamSerializer, TrendSerializer
from .upload import UploadRejected, accept_upload
from .workbook import SHEET_NAME, SHEET_ROLES, WorkbookError, get_dataset


def _dataset():
    """The dataset of the active source (Excel workbook or PostgreSQL), the same for every endpoint."""
    from apps.uptimedb.datasource import current_dataset
    try:
        return current_dataset()
    except WorkbookError as exc:
        raise ServiceUnavailable(str(exc), error_code=exc.code) from exc


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
def filters_view(request):
    dataset = _dataset()
    return Response({**metrics.filter_options(dataset), 'source': _source(dataset)})


@api_view(['GET'])
def summary_view(request):
    dataset = _dataset()
    params = _validated(SnapshotSerializer, request, dataset)
    result = metrics.summary(dataset, params['selection'], params['reporting_date'])
    return Response({**result, 'filters': _applied(params), 'source': _source(dataset)})


@api_view(['GET'])
def trends_view(request):
    dataset = _dataset()
    params = _validated(TrendSerializer, request, dataset)
    result = metrics.trend(dataset, params['selection'], params['start_date'], params['end_date'])
    return Response({
        **result,
        'filters': {**_applied(params), 'start_date': params['start_date'].isoformat(),
                    'end_date': params['end_date'].isoformat()},
        'source': _source(dataset),
    })


@api_view(['GET'])
def breakdowns_view(request):
    dataset = _dataset()
    params = _validated(SnapshotSerializer, request, dataset)
    result = metrics.breakdown(dataset, params['selection'], params['reporting_date'])
    return Response({**result, 'filters': _applied(params), 'source': _source(dataset)})


@api_view(['GET'])
def records_view(request):
    dataset = _dataset()
    params = _validated(RecordsSerializer, request, dataset)
    table = metrics.site_table(dataset, params['selection'], params['reporting_date'])
    table = metrics.search_sites(table, params['search'], params['bucket'] or None, params['bucket_basis'])
    table = metrics.filter_team(table, params['ci_name'], params['ie_name'])
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
                    'bucket_basis': params['bucket_basis'],
                    'sort': params['sort'], 'direction': params['direction']},
        'source': _source(dataset),
    })


@api_view(['GET'])
def record_detail_view(request, site_id):
    dataset = _dataset()
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
def source_view(request):
    dataset = _dataset()
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
def alerts_view(request):
    dataset = _dataset()
    items = metrics.alerts(dataset, timezone.localdate())
    counts = {level: sum(1 for a in items if a['severity'] == level) for level in metrics.SEVERITY_RANK}
    return Response({'alerts': items, 'counts': counts, 'source': _source(dataset)})


@api_view(['GET'])
def period_view(request):
    """KPI for the trend period selected in the filter bar."""
    dataset = _dataset()
    params = _validated(PeriodSerializer, request, dataset)
    result = metrics.period_summary(dataset, params['selection'], dates=params['dates'],
                                    month_keys=params['month_keys'], label=params['label'])
    return Response({**result, 'filters': _applied(params), 'source': _source(dataset)})


@api_view(['GET'])
def thresholds_view(request):
    dataset = _dataset()
    params = _validated(SnapshotSerializer, request, dataset)
    result = metrics.threshold_analysis(dataset, params['selection'], params['reporting_date'],
                                        period=request.query_params.get('period') or None,
                                        compare=request.query_params.get('vs') or None)
    return Response({**result, 'filters': _applied(params), 'source': _source(dataset)})


@api_view(['GET'])
def monthly_view(request):
    dataset = _dataset()
    params = _validated(MonthlySerializer, request, dataset)
    result = metrics.monthly(dataset, params['selection'], params['reporting_date'], params['months'])
    return Response({**result, 'filters': _applied(params), 'source': _source(dataset)})


@api_view(['GET'])
@permission_classes([IsAdminRole])  # Team performance: Admins only
def teams_view(request):
    dataset = _dataset()
    params = _validated(TeamSerializer, request, dataset)
    result = metrics.team_performance(dataset, params['selection'], params['reporting_date'], params['group'])
    return Response({**result, 'filters': _applied(params), 'source': _source(dataset)})



@api_view(['GET'])
@permission_classes([IsAdminRole])  # CI & IE Performance is part of Team performance: Admins only
def team_monthly_view(request):
    dataset = _dataset()
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
    dataset = _dataset()
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
        return Response(_workbook_status())

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
    return Response({'status': 'accepted', **_workbook_status(dataset if active_source() == EXCEL else None)},
                    status=status.HTTP_201_CREATED)


def _workbook_status(dataset=None) -> dict:
    """The data behind the dashboard: the active source's dataset (Excel workbook or PostgreSQL)."""
    from apps.uptimedb.datasource import active_source
    source = active_source()
    if dataset is None:
        try:
            dataset = _dataset()
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
            from apps.uptimedb.datasource import current_dataset
            month = current_dataset().dates[0]
        except Exception:  # no Master data: fall back to today's month
            month = _date.today()
    try:
        return Response(monthly_activity(month, request.query_params.get('report_type') or None, request.query_params.get('circle') or None))
    except ActivityUnavailable as exc:
        return Response({'error': str(exc), 'details': {}}, status=404)


@api_view(['GET'])
def om_heads_view(request):
    """O&M Head per circle from the reference sheet in Data/reference (not part of the Master workbook)."""
    from .reference import om_heads
    return Response(om_heads())
