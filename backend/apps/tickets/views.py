from __future__ import annotations

from datetime import date
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q
from django.db.models.functions import TruncMonth
from django.http import FileResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.accounts.audit import audit
from apps.accounts.access import can, pairs_for
from apps.accounts.permissions import IsPortalUser
from apps.accounts.roles import ADMIN, role_of

from . import importer, services
from .models import Ticket, TicketEvent, TicketNotification, TicketStatus, TicketUploadBatch


PAGE_SIZES = (25, 50, 100)
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
TEMPLATE_PATH = Path(settings.BASE_DIR).parent / 'Data' / 'reference' / 'BSNL_Ticket_Upload_Template (1).xlsx'


def _ticket(request, ticket_id: int, action: str | None = None) -> Ticket:
    ticket = services.visible_tickets(request.user, 'view').filter(pk=ticket_id).first()
    if ticket is None:
        raise NotFound('No such ticket.')
    if action and not can(request.user, 'ticket_management', action, ticket.project, ticket.circle):
        raise PermissionDenied(f'You do not have permission to {action} this ticket.')
    return ticket


def _date(value: str, field: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError({field: 'Enter a date as YYYY-MM-DD.'}) from exc


ALL_STATUSES = 'All'


def _status(params, default: str) -> str:
    """'Open', 'Closed' or 'All'. A missing or blank value uses ``default``; anything else is rejected."""
    value = (params.get('status') or '').strip() or default
    if value != ALL_STATUSES and value not in TicketStatus.values:
        raise ValidationError({'status': f'Choose one of {", ".join([*TicketStatus.values, ALL_STATUSES])}.'})
    return value


def _filtered(request, *, default_status: str = ALL_STATUSES):
    """Tickets in the user's view scope matching every given filter (search, circle, vendor, status and dates)."""
    params = request.query_params
    qs = services.visible_tickets(request.user, 'view')
    if params.get('q'):
        q = params['q'].strip()
        qs = qs.filter(Q(portal_ticket_id__icontains=q) | Q(site_id__icontains=q) | Q(site_name__icontains=q))
    for key in ('circle', 'vendor_name'):
        value = params.get(key)
        if value:
            qs = qs.filter(**{key: value})
    selected = _status(params, default_status)
    if selected != ALL_STATUSES:
        qs = qs.filter(status=selected)
    start, end = _date(params.get('date_from', ''), 'date_from'), _date(params.get('date_to', ''), 'date_to')
    if start and end and end < start:
        raise ValidationError({'date_to': 'The end date must not be before the start date.'})
    if start:
        qs = qs.filter(outage_date__gte=start)
    if end:
        qs = qs.filter(outage_date__lte=end)
    return qs


def _batch_json(batch: TicketUploadBatch) -> dict:
    rows = [{
        'excel_row': row.excel_row,
        'outcome': row.result_outcome or row.preview_outcome,
        'preview_outcome': row.preview_outcome,
        'values': row.row_data.get('values', {}),
        'source_values': row.row_data.get('source_values', {}),
        'errors': row.errors,
        'portal_ticket_id': row.ticket.portal_ticket_id if row.ticket_id else None,
        'notification_id': row.notification_id,
    } for row in batch.rows.select_related('ticket').all()]
    return {
        'id': batch.pk,
        'filename': batch.original_filename,
        'checksum_sha256': batch.checksum_sha256,
        'status': batch.status,
        'uploaded_at': batch.uploaded_at.isoformat(),
        'committed_at': batch.committed_at.isoformat() if batch.committed_at else None,
        'uploaded_by': batch.uploaded_by.get_username() if batch.uploaded_by_id else '',
        'counts': batch.counts,
        'duplicate_of': batch.duplicate_of_id,
        'error': batch.error,
        'rows': rows,
    }


def _batch_for_user(request, batch_id: int) -> TicketUploadBatch:
    batch = TicketUploadBatch.objects.filter(pk=batch_id).first()
    if batch is None or (batch.uploaded_by_id != request.user.pk and role_of(request.user) != ADMIN):
        raise NotFound('No such ticket upload batch.')
    return batch


@api_view(['GET'])
@permission_classes([IsPortalUser])
def template(request):
    if not can(request.user, 'ticket_management', 'view') and not can(request.user, 'ticket_management', 'upload'):
        raise PermissionDenied('You do not have access to the Ticket Management template.')
    if not TEMPLATE_PATH.is_file():
        return Response({'error': 'The official ticket template is not available on the server.'}, status=500)
    return FileResponse(TEMPLATE_PATH.open('rb'), as_attachment=True, filename=TEMPLATE_PATH.name,
                        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@api_view(['GET'])
@permission_classes([IsPortalUser])
def options(request):
    if not can(request.user, 'ticket_management', 'view'):
        raise PermissionDenied('You do not have access to Ticket Management.')
    qs = services.visible_tickets(request.user, 'view').order_by()
    return Response({
        'circles': list(qs.values_list('circle', flat=True).distinct().order_by('circle')),
        'vendors': list(qs.exclude(vendor_name='').values_list('vendor_name', flat=True).distinct().order_by('vendor_name')),
        'statuses': list(TicketStatus.values),
        'can_upload': can(request.user, 'ticket_management', 'upload'),
        'max_upload_bytes': MAX_UPLOAD_BYTES,
    })


@api_view(['GET'])
@permission_classes([IsPortalUser])
def dashboard(request):
    if not can(request.user, 'ticket_management', 'view'):
        raise PermissionDenied('You do not have Ticket Management view permission.')
    qs = _filtered(request)
    today = timezone.localdate()
    notifications = TicketNotification.objects.filter(ticket__in=qs)
    grouped = lambda field: list(qs.order_by().values(field).annotate(count=Count('id')).order_by('-count', field)[:12])
    monthly = list(qs.order_by().annotate(month=TruncMonth('outage_date')).values('month').annotate(count=Count('id')).order_by('month'))
    return Response({
        'kpis': {
            'total': qs.count(),
            'open': qs.filter(status=TicketStatus.OPEN).count(),
            'closed': qs.filter(status=TicketStatus.CLOSED).count(),
            'created_today': qs.filter(created_at__date=today).count(),
            'notifications_accepted': notifications.filter(status=TicketNotification.Status.ACCEPTED).count(),
            'notifications_failed': notifications.filter(status=TicketNotification.Status.FAILED).count(),
        },
        'status': list(qs.order_by().values('status').annotate(count=Count('id')).order_by('status')),
        'circles': grouped('circle'),
        'vendors': grouped('vendor_name'),
        'buckets': grouped('outage_bucket'),
        'monthly': [{'month': row['month'].isoformat(), 'count': row['count']} for row in monthly],
    })


@api_view(['GET'])
@permission_classes([IsPortalUser])
def records(request):
    if not can(request.user, 'ticket_management', 'view'):
        raise PermissionDenied('You do not have Ticket Management view permission.')
    # The ticket table opens on pending outages: without a status the list holds Open tickets only ("All" for both).
    qs = _filtered(request, default_status=TicketStatus.OPEN)
    sort = request.query_params.get('sort', '-created_at')
    descending = sort.startswith('-')
    field = sort.lstrip('-')
    allowed = {'created_at', 'updated_at', 'outage_date', 'portal_ticket_id', 'circle', 'site_id', 'site_name',
               'vendor_name', 'outage_minutes', 'status'}
    if field not in allowed:
        raise ValidationError({'sort': 'Choose a supported sort column.'})
    qs = qs.order_by(f'-{field}' if descending else field, 'id')
    try:
        page = max(1, int(request.query_params.get('page', '1')))
        page_size = int(request.query_params.get('page_size', '25'))
    except ValueError as exc:
        raise ValidationError({'page': 'Page and page size must be integers.'}) from exc
    if page_size not in PAGE_SIZES:
        raise ValidationError({'page_size': f'Choose one of {", ".join(map(str, PAGE_SIZES))}.'})
    total = qs.count()
    rows = qs[(page - 1) * page_size:page * page_size]
    # The same project/circle rule close_ticket enforces; used only to show or hide the Close action.
    close_pairs = pairs_for(request.user, 'ticket_management', 'close')
    can_close = lambda t: close_pairs is None or (t.project, str(t.circle).upper()) in close_pairs  # noqa: E731
    return Response({
        'total': total, 'page': page, 'page_size': page_size, 'pages': max(1, -(-total // page_size)),
        'status': _status(request.query_params, TicketStatus.OPEN),
        'tickets': [{
            'id': t.pk, 'portal_ticket_id': t.portal_ticket_id, 'outage_date': t.outage_date.isoformat(),
            'circle': t.circle, 'site_id': t.site_id, 'site_name': t.site_name, 'vendor_name': t.vendor_name,
            'outage_minutes': str(t.outage_minutes) if t.outage_minutes is not None else None, 'status': t.status,
            'email_id': t.email_id, 'created_at': t.created_at.isoformat(), 'updated_at': t.updated_at.isoformat(),
            'can_close': t.status == TicketStatus.OPEN and can_close(t),
        } for t in rows],
    })


@api_view(['GET'])
@permission_classes([IsPortalUser])
def record_detail(request, ticket_id: int):
    ticket = _ticket(request, ticket_id)
    return Response({
        'ticket': services.ticket_detail(ticket),
        'permissions': {
            'close': can(request.user, 'ticket_management', 'close', ticket.project, ticket.circle),
            'reopen': can(request.user, 'ticket_management', 'reopen', ticket.project, ticket.circle),
            'retry': can(request.user, 'ticket_management', 'retry', ticket.project, ticket.circle),
        },
    })


@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser])
@permission_classes([IsPortalUser])
def import_preview(request):
    if not can(request.user, 'ticket_management', 'upload'):
        raise PermissionDenied('You do not have Ticket Management upload permission.')
    upload = request.FILES.get('file')
    if upload is None:
        return Response({'error': 'Choose an Excel workbook.'}, status=status.HTTP_400_BAD_REQUEST)
    if not upload.name.lower().endswith(('.xlsx', '.xlsm')):
        return Response({'error': 'Choose an .xlsx or .xlsm Excel workbook.'}, status=status.HTTP_400_BAD_REQUEST)
    if upload.size == 0:
        return Response({'error': 'The workbook is empty.'}, status=status.HTTP_400_BAD_REQUEST)
    if upload.size > MAX_UPLOAD_BYTES:
        return Response({'error': f'The workbook exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload limit.'},
                        status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
    batch = importer.preview(upload.read(), upload.name, request.user)
    if batch.status == TicketUploadBatch.Status.FAILED:
        return Response({'error': batch.error, 'details': {'batch_id': batch.pk}}, status=status.HTTP_400_BAD_REQUEST)
    return Response(_batch_json(batch), status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([IsPortalUser])
def import_detail(request, batch_id: int):
    if not can(request.user, 'ticket_management', 'upload') and role_of(request.user) != ADMIN:
        raise NotFound('No such ticket upload batch.')
    batch = _batch_for_user(request, batch_id)
    return Response(_batch_json(batch))


@api_view(['POST'])
@parser_classes([JSONParser])
@permission_classes([IsPortalUser])
def import_commit(request, batch_id: int):
    if not can(request.user, 'ticket_management', 'upload'):
        raise PermissionDenied('You do not have Ticket Management upload permission.')
    accept_invalid = request.data.get('accept_invalid', False)
    confirm_duplicate = request.data.get('confirm_duplicate', False)
    if not isinstance(accept_invalid, bool) or not isinstance(confirm_duplicate, bool):
        raise ValidationError({'confirmation': 'Confirmation values must be true or false.'})
    try:
        batch = importer.commit(batch_id, request.user, accept_invalid=accept_invalid, confirm_duplicate=confirm_duplicate)
    except importer.ImportConflict as exc:
        return Response({'error': str(exc)}, status=exc.status_code)
    audit('ticket_import_committed', request, batch=batch.pk, counts=batch.counts)
    return Response(_batch_json(batch))


@api_view(['POST'])
@parser_classes([JSONParser])
@permission_classes([IsPortalUser])
def close_ticket(request, ticket_id: int):
    ticket = _ticket(request, ticket_id, 'close')
    remarks = request.data.get('remarks')
    if not isinstance(remarks, str) or not remarks.strip():
        raise ValidationError({'remarks': 'Enter closure remarks.'})
    if len(remarks.strip()) > 5000:
        raise ValidationError({'remarks': 'Closure remarks must be 5,000 characters or fewer.'})
    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().get(pk=ticket.pk)
        if ticket.status != TicketStatus.OPEN:
            return Response({'error': 'Only an Open ticket can be closed.'}, status=status.HTTP_409_CONFLICT)
        before = services.snapshot(ticket)
        ticket.status = TicketStatus.CLOSED
        ticket.closure_remarks = remarks.strip()
        ticket.closed_by = request.user
        ticket.closed_at = timezone.now()
        ticket.closure_source = 'manual'
        ticket.updated_by = request.user
        ticket.save()
        services.record_event(ticket, action='closed_manually', source=TicketEvent.Source.MANUAL, actor=request.user,
                              status_before=TicketStatus.OPEN, status_after=TicketStatus.CLOSED, remarks=remarks.strip(),
                              changes={'before': before, 'after': services.snapshot(ticket)})
    audit('ticket_closed', request, ticket=ticket.portal_ticket_id)
    return Response({'ticket': services.ticket_detail(ticket)})


@api_view(['POST'])
@parser_classes([JSONParser])
@permission_classes([IsPortalUser])
def reopen_ticket(request, ticket_id: int):
    ticket = _ticket(request, ticket_id, 'reopen')
    reason = request.data.get('reason')
    if not isinstance(reason, str) or not reason.strip():
        raise ValidationError({'reason': 'Enter a reopening reason.'})
    if len(reason.strip()) > 5000:
        raise ValidationError({'reason': 'The reopening reason must be 5,000 characters or fewer.'})
    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().get(pk=ticket.pk)
        if ticket.status != TicketStatus.CLOSED:
            return Response({'error': 'Only a Closed ticket can be reopened.'}, status=status.HTTP_409_CONFLICT)
        before = services.snapshot(ticket)
        ticket.status = TicketStatus.OPEN
        ticket.updated_by = request.user
        ticket.save()
        services.record_event(ticket, action='reopened_manually', source=TicketEvent.Source.MANUAL, actor=request.user,
                              status_before=TicketStatus.CLOSED, status_after=TicketStatus.OPEN, remarks=reason.strip(),
                              changes={'before': before, 'after': services.snapshot(ticket)})
        notification = services.queue_notification(ticket, kind=TicketNotification.Kind.REOPENED)
    services.send_notification(notification, by=request.user)
    audit('ticket_reopened', request, ticket=ticket.portal_ticket_id)
    return Response({'ticket': services.ticket_detail(ticket)})


@api_view(['POST'])
@permission_classes([IsPortalUser])
def retry_notification(request, notification_id: int):
    notification = TicketNotification.objects.select_related('ticket').filter(pk=notification_id).first()
    if notification is None:
        raise NotFound('No such ticket notification.')
    ticket = _ticket(request, notification.ticket_id, 'retry')
    if notification.status != TicketNotification.Status.FAILED:
        return Response({'error': 'Only a failed notification can be retried.'}, status=status.HTTP_409_CONFLICT)
    notification = services.send_notification(notification, by=request.user)
    audit('ticket_notification_retried', request, ticket=ticket.portal_ticket_id, notification=notification.pk,
          status=notification.status)
    return Response({'ticket': services.ticket_detail(ticket)})
