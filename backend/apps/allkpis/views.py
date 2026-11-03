"""All KPI's: read-only endpoints (see README.md). Site data needs Dashboard View, RCA data RCA Summary View: the existing
permissions, so the module adds no role or permission of its own. Every figure is limited to the user's circles."""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.permissions import Can
from apps.common.exceptions import ServiceUnavailable
from apps.dashboard.workbook import WorkbookError

from . import services


def _run(fn, request):
    try:
        return Response(fn(request.query_params, request.user))
    except WorkbookError as exc:
        raise ServiceUnavailable(str(exc), error_code=exc.code) from exc


@api_view(['GET'])
@permission_classes([Can('dashboard', 'view')])
def filters(request):
    return _run(services.filters, request)


@api_view(['GET'])
@permission_classes([Can('dashboard', 'view')])
def summary(request):
    return _run(services.summary, request)


@api_view(['GET'])
@permission_classes([Can('dashboard', 'view')])
def trends(request):
    return _run(services.trends, request)


@api_view(['GET'])
@permission_classes([Can('dashboard', 'view')])
def hierarchy(request):
    return _run(services.hierarchy, request)


@api_view(['GET'])
@permission_classes([Can('dashboard', 'view')])
def sites(request):
    return _run(services.sites, request)


@api_view(['GET'])
@permission_classes([Can('rca_summary', 'view')])
def rca(request):
    return _run(services.rca, request)
