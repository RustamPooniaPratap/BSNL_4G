"""API Master administration API (Admins only). Phase 1: the API Registry."""
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.accounts.audit import audit
from apps.accounts.permissions import IsAdminRole

from . import discovery, services
from .models import ApiEndpoint


def endpoint_json(e: ApiEndpoint, full: bool = False) -> dict:
    data = {
        'id': e.id, 'key': e.key, 'name': e.name, 'path': e.path, 'method': e.method, 'module': e.module,
        'description': e.description, 'status': e.status, 'status_label': e.get_status_display(), 'blocked': e.blocked,
        'block_reason': e.block_reason, 'field_review': e.field_review, 'present': e.present,
        'access_type': 'Internal only' if e.blocked else ('Approved for external use' if e.status == ApiEndpoint.Status.APPROVED
                                                        else 'Internal (reviewable)'),
    }
    if full:
        data.update({
            'url_name': e.url_name, 'view': e.view, 'permission_classes': e.permission_classes,
            'authentication_classes': e.authentication_classes, 'path_params': e.path_params,
            'review_note': e.review_note, 'reviewed_by': e.reviewed_by.get_username() if e.reviewed_by else None,
            'reviewed_at': e.reviewed_at.isoformat() if e.reviewed_at else None,
            'first_seen': e.first_seen.isoformat(), 'last_seen': e.last_seen.isoformat(),
            # Not discoverable from these views (they read query parameters and build JSON in code): documented per
            # endpoint, from the code and with contract tests, when it is wrapped for external use (later phase).
            'external_route': None,
            'allowed_transitions': sorted(services.TRANSITIONS[ApiEndpoint.Status(e.status)]),
        })
    return data


@api_view(['GET'])
@permission_classes([IsAdminRole])
def overview(request):
    return Response(services.overview())


@api_view(['GET'])
@permission_classes([IsAdminRole])
def endpoints(request):
    p = request.query_params
    qs = ApiEndpoint.objects.select_related('reviewed_by')
    if p.get('present', '1') != 'all':
        qs = qs.filter(present=True)
    if q := (p.get('q') or '').strip():
        qs = qs.filter(Q(name__icontains=q) | Q(path__icontains=q) | Q(url_name__icontains=q) | Q(description__icontains=q))
    for field in ('module', 'method', 'status'):
        if value := p.get(field):
            qs = qs.filter(**{field: value})
    if p.get('access') == 'blocked':
        qs = qs.filter(blocked=True)
    elif p.get('access') == 'reviewable':
        qs = qs.filter(blocked=False)
    rows = [endpoint_json(e) for e in qs]
    return Response({'count': len(rows), 'results': rows})


@api_view(['GET'])
@permission_classes([IsAdminRole])
def endpoint_detail(request, pk: int):
    return Response(endpoint_json(get_object_or_404(ApiEndpoint.objects.select_related('reviewed_by'), pk=pk), full=True))


class ReviewSerializer(serializers.Serializer):
    status = serializers.CharField(max_length=12)
    note = serializers.CharField(max_length=2000, allow_blank=True, trim_whitespace=True)
    fields_reviewed = serializers.BooleanField(required=False, default=False)


@api_view(['POST'])
@permission_classes([IsAdminRole])
def endpoint_review(request, pk: int):
    endpoint = get_object_or_404(ApiEndpoint, pk=pk)
    data = ReviewSerializer(data=request.data)
    data.is_valid(raise_exception=True)
    before = endpoint.status
    try:
        services.review(endpoint, user=request.user, **data.validated_data)
    except services.ReviewError as exc:
        raise ValidationError({exc.field: str(exc)}) from exc
    audit('api_endpoint_reviewed', request, endpoint=endpoint.key, before=before, after=endpoint.status)
    return Response(endpoint_json(endpoint, full=True))


@api_view(['POST'])
@permission_classes([IsAdminRole])
def sync(request):
    result = discovery.sync()
    audit('api_registry_synced', request, **{k: v for k, v in result.items() if k != 'total'})
    return Response(result, status=status.HTTP_200_OK)
