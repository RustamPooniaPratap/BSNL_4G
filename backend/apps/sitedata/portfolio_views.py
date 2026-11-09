"""Site Portfolio API on the new data layer (/api/site-portfolio/). The same requests, permissions, validation,
calculations (dashboard.metrics) and responses as the dashboard endpoints the page used before, with the dataset of
the new layer instead of the old tables. Only the Site Portfolio page calls these endpoints."""
from datetime import date

from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.access import pairs_for
from apps.accounts.permissions import Can
from apps.common.exceptions import ServiceUnavailable
from apps.dashboard import metrics
from apps.dashboard.scope import restrict
from apps.dashboard.serializers import PeriodSerializer, SnapshotSerializer
from apps.dashboard.views import _applied, _source, _validated
from apps.dashboard.workbook import WorkbookError

from . import portfolio


def _dataset(request, variant: str = 'all'):
    """The new layer's dataset ("all", "on_air" or "om_start" variant), limited to the user's Dashboard project/circle
    pairs, with the continuous reporting dates of the "all" variant."""
    pairs = pairs_for(request.user, 'dashboard', 'view')
    try:
        base = portfolio.continuous(restrict(portfolio.portfolio_dataset('all'), pairs))
        if variant == 'all':
            return base
        return portfolio.with_dates_of(restrict(portfolio.portfolio_dataset(variant), pairs), base)
    except WorkbookError as exc:
        raise ServiceUnavailable(f'Site Portfolio data (new data layer) is unavailable: {exc}', error_code=exc.code) from exc


def _for_scope(request, params):
    """The dataset variant of the validated scope: On-Air and O&M Start count each site from its effective date."""
    scope = params['selection'].scope
    return _dataset(request, scope if scope in portfolio.VARIANTS else 'all')


def _source_info(ds) -> dict:
    return {**_source(ds), 'data_layer': 'sitedata', 'continuity': portfolio.continuity(ds)}


@api_view(['GET'])
@permission_classes([Can('dashboard', 'view')])
def filters_view(request):
    from apps.organization.services import merge_filter_options
    ds = _dataset(request)
    return Response({**merge_filter_options(metrics.filter_options(ds), pairs_for(request.user, 'dashboard', 'view')), 'source': _source_info(ds)})


@api_view(['GET'])
@permission_classes([Can('dashboard', 'view')])
def summary_view(request):
    params = _validated(SnapshotSerializer, request, _dataset(request))
    ds = _for_scope(request, params)
    return Response({**metrics.summary(ds, params['selection'], params['reporting_date']), 'filters': _applied(params), 'source': _source_info(ds)})


@api_view(['GET'])
@permission_classes([Can('dashboard', 'view')])
def breakdowns_view(request):
    params = _validated(SnapshotSerializer, request, _dataset(request))
    ds = _for_scope(request, params)
    return Response({**metrics.breakdown(ds, params['selection'], params['reporting_date']), 'filters': _applied(params), 'source': _source_info(ds)})


@api_view(['GET'])
@permission_classes([Can('dashboard', 'view')])
def period_view(request):
    params = _validated(PeriodSerializer, request, _dataset(request))
    ds = _for_scope(request, params)
    if params['month_keys']:
        # Whole months from the daily records over the days that have data (reporting days), never calendar days.
        result = metrics.period_summary(ds, params['selection'], dates=portfolio.month_dates(ds, params['month_keys']), label=params['label'])
        result.update(kind='months', months=len(params['month_keys']))
    else:
        result = metrics.period_summary(ds, params['selection'], dates=params['dates'], month_keys=None, label=params['label'])
    return Response({**result, 'filters': _applied(params), 'source': _source_info(ds)})


@api_view(['GET'])
@permission_classes([Can('dashboard', 'view')])
def conversion_activity_view(request):
    raw = request.query_params.get('month')
    try:
        month = date.fromisoformat(f'{raw}-01') if raw else None
    except ValueError:
        return Response({'error': f'"{raw}" is not a month (YYYY-MM).', 'details': {}}, status=400)
    if month is None:
        month = _dataset(request).dates[0]
    return Response(portfolio.monthly_activity(month, request.query_params.get('report_type') or None, request.query_params.get('circle') or None,
                                               pairs=pairs_for(request.user, 'dashboard', 'view')))
