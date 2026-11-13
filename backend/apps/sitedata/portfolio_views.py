"""Site Portfolio API on the new data layer (/api/site-portfolio/). The same requests, permissions, validation,
calculations (dashboard.metrics) and responses as the dashboard endpoints the page used before, with the dataset of
the new layer instead of the old tables. Only the Site Portfolio page calls these endpoints.

Population (``scope``: on_air | om_start, default on_air; any other value is HTTP 400): summary,
breakdowns and period count exactly the selected population, as every dashboard endpoint, and return the ``population``
block. The summary's ``status_counts`` (total / On-Air / O&M Start sites of the selection) are status counts, not a
population figure. Conversion activity is a status flow (sites that went On-Air / started O&M in a month, from the matrix
dates) and ignores ``scope``."""
from datetime import date

from django.db.models import Q
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.access import pairs_for
from apps.accounts.models import AccessAssignment
from apps.accounts.permissions import Can
from apps.common.exceptions import ServiceUnavailable
from apps.dashboard import metrics
from apps.dashboard.scope import restrict
from apps.dashboard.serializers import PeriodSerializer, SnapshotSerializer, period_status
from apps.dashboard.views import _applied, _population, _source, _validated
from apps.dashboard.workbook import WorkbookError
from apps.organization.models import ProjectCircle

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
    return _dataset(request, scope)


def _source_info(ds) -> dict:
    return {**_source(ds), 'data_layer': 'sitedata', 'continuity': portfolio.continuity(ds)}


def _om_heads_by_pair(pairs: set[tuple[str, str]] | None) -> dict[tuple[str, str], list[str]]:
    """Active O&M Head role assignments for the visible project/circle pairs."""
    today = timezone.localdate()
    assignments = list(
        AccessAssignment.objects.filter(
            role__name__iexact='O&M Head', role__is_active=True, user__is_active=True,
            project__is_active=True, status=AccessAssignment.Status.ACTIVE,
        ).filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today))
        .filter(Q(project_circle__isnull=True) | Q(project_circle__is_active=True, project_circle__circle__is_active=True))
        .select_related('user', 'project', 'project_circle__circle')
    )
    project_ids = {assignment.project_id for assignment in assignments if assignment.project_circle_id is None}
    circles_by_project: dict[int, list[ProjectCircle]] = {}
    if project_ids:
        circles = ProjectCircle.objects.filter(
            project_id__in=project_ids, is_active=True, circle__is_active=True,
        ).select_related('project', 'circle')
        for project_circle in circles:
            circles_by_project.setdefault(project_circle.project_id, []).append(project_circle)

    names: dict[tuple[str, str], dict[int, str]] = {}

    def add(project: str, circle: str, assignment: AccessAssignment) -> None:
        pair = (project, circle)
        if pairs is None or pair in pairs:
            name = assignment.user.get_full_name().strip() or assignment.user.get_username()
            names.setdefault(pair, {})[assignment.user_id] = name

    for assignment in assignments:
        if assignment.project_circle_id is not None:
            add(assignment.project.key, assignment.project_circle.circle.code, assignment)
        else:
            for project_circle in circles_by_project.get(assignment.project_id, []):
                add(project_circle.project.key, project_circle.circle.code, assignment)

    return {pair: sorted(users.values(), key=str.casefold) for pair, users in names.items()}


@api_view(['GET'])
@permission_classes([Can('dashboard', 'view')])
def filters_view(request):
    from apps.organization.services import merge_filter_options
    ds = _dataset(request)
    return Response({**merge_filter_options(metrics.filter_options(ds), pairs_for(request.user, 'dashboard', 'view')),
                     'population': metrics.population(metrics.DEFAULT_SCOPE), 'source': _source_info(ds)})


@api_view(['GET'])
@permission_classes([Can('dashboard', 'view')])
def summary_view(request):
    params = _validated(SnapshotSerializer, request, _dataset(request))
    ds = _for_scope(request, params)
    return Response({**metrics.summary(ds, params['selection'], params['reporting_date']), 'filters': _applied(params),
                     'population': _population(params), 'source': _source_info(ds)})


@api_view(['GET'])
@permission_classes([Can('dashboard', 'view')])
def breakdowns_view(request):
    params = _validated(SnapshotSerializer, request, _dataset(request))
    ds = _for_scope(request, params)
    result = metrics.breakdown(ds, params['selection'], params['reporting_date'], include_inventory=True)
    heads = _om_heads_by_pair(pairs_for(request.user, 'dashboard', 'view'))
    for circle in result['circles']:
        circle['om_heads'] = heads.get((circle['report_type'], circle['circle']), [])
    return Response({**result, 'filters': _applied(params),
                     'population': _population(params), 'source': _source_info(ds)})


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
    # Complete / Provisional for the requested dates over the selection's reporting units (reporting.period_status, up
    # to the data layer's latest date in the month); None without coverage information.
    status = period_status(ds, params)
    result.update(status=status['status'] if status else None, missing=status['missing'] if status else [])
    return Response({**result, 'filters': _applied(params), 'population': _population(params), 'source': _source_info(ds)})


@api_view(['GET'])
@permission_classes([Can('dashboard', 'view')])
def conversion_activity_view(request):
    """A status flow (On-Air / O&M Start conversions per month from the matrix dates): ``scope`` is not used."""
    raw = request.query_params.get('month')
    try:
        month = date.fromisoformat(f'{raw}-01') if raw else None
    except ValueError:
        return Response({'error': f'"{raw}" is not a month (YYYY-MM).', 'details': {}}, status=400)
    if month is None:
        month = _dataset(request).dates[0]
    return Response(portfolio.monthly_activity(month, request.query_params.get('report_type') or None, request.query_params.get('circle') or None,
                                               pairs=pairs_for(request.user, 'dashboard', 'view')))
