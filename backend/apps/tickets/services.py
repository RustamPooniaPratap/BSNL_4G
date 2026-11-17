from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.accounts.access import can
from apps.alerts import engine, mailer

from . import email_content
from .models import Ticket, TicketEvent, TicketNotification, TicketNotificationAttempt, TicketStatus, TicketUploadBatch


FIELD_NAMES = (
    'source_serial', 'outage_date', 'circle', 'site_id', 'site_name', 'oa', 'ba', 'actual_down_time',
    'reporting_time_to_partner', 'restoration_time', 'outage_minutes', 'mttr_hours', 'vendor_name',
    'outage_bucket', 'detail_rca', 'status', 'email_id',
)


def _plain(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def actor_name(user) -> str:
    return user.get_full_name() or user.get_username() if user and user.is_authenticated else 'system'


def snapshot(ticket: Ticket) -> dict:
    return {field: _plain(getattr(ticket, field)) for field in FIELD_NAMES}


def record_event(ticket: Ticket, *, action: str, source: str, actor=None, batch: TicketUploadBatch | None = None,
                 status_before: str = '', status_after: str = '', remarks: str = '', changes: dict | None = None) -> TicketEvent:
    return TicketEvent.objects.create(ticket=ticket, batch=batch, actor=actor, actor_name=actor_name(actor), action=action, source=source,
                                      status_before=status_before, status_after=status_after, remarks=remarks, changes=changes or {})


def generate_ticket_id(year: int | None = None) -> str:
    from .models import TicketSequence

    year = year or timezone.localdate().year
    with transaction.atomic():
        TicketSequence.objects.get_or_create(year=year)
        sequence = TicketSequence.objects.select_for_update().get(year=year)
        number = sequence.next_number
        sequence.next_number += 1
        sequence.save(update_fields=['next_number'])
    return f'OFC-{year}-{number:05d}'


def notification_content(ticket: Ticket, kind: str) -> tuple[str, str, str]:
    """Subject, plain text and HTML of an informational technician notification (see ``email_content``)."""
    return email_content.render(ticket, kind)


def queue_notification(ticket: Ticket, *, kind: str, batch: TicketUploadBatch | None = None) -> TicketNotification:
    subject, text, html = notification_content(ticket, kind)
    return TicketNotification.objects.create(ticket=ticket, batch=batch, kind=kind, recipient=ticket.email_id,
                                             subject=subject, text_body=text, html_body=html)


def send_notification(notification: TicketNotification, *, by=None) -> TicketNotification:
    """Attempt delivery through the portal's configured account; ticket persistence is independent of mail success."""
    with transaction.atomic():
        notification = TicketNotification.objects.select_for_update().get(pk=notification.pk)
        if notification.status == TicketNotification.Status.PENDING and notification.attempts:
            return notification
        if notification.status not in (TicketNotification.Status.PENDING, TicketNotification.Status.FAILED):
            return notification
        number = notification.attempts + 1
        notification.status = TicketNotification.Status.PENDING
        notification.attempts = number
        notification.save(update_fields=['status', 'attempts'])
    attempted_at = timezone.now()
    try:
        account = engine.active_account()
        response = mailer.send(account, mailer.Outgoing(
            to=[notification.recipient], cc=[], bcc=[], subject=notification.subject,
            text=notification.text_body, html=notification.html_body, files=[],
        ))
        accepted_at = timezone.now()
        notification.status = TicketNotification.Status.ACCEPTED
        notification.sent_at = accepted_at
        notification.error = ''
        notification.smtp_response = response[:500]
        detail = response[:2000]
    except (engine.NotReady, mailer.MailError, OSError) as exc:
        accepted_at = None
        notification.status = TicketNotification.Status.FAILED
        notification.error = str(exc)[:2000]
        notification.smtp_response = ''
        detail = notification.error
    notification.save()
    TicketNotificationAttempt.objects.create(notification=notification, number=number, attempted_by=by,
                                             attempted_at=attempted_at, accepted_at=accepted_at,
                                             accepted=accepted_at is not None, detail=detail)
    record_event(notification.ticket, action='notification_accepted' if accepted_at else 'notification_failed',
                 source=TicketEvent.Source.EXCEL if notification.batch_id else TicketEvent.Source.MANUAL, actor=by, batch=notification.batch,
                 changes={'notification_id': notification.pk, 'kind': notification.kind, 'recipient': notification.recipient,
                          'status': notification.status, 'attempt': number})
    return notification


def apply_excel_row(ticket: Ticket, values: dict, *, site, project: str, circle: str, batch: TicketUploadBatch, user,
                    committed_at: datetime, creating: bool = False) -> dict:
    before = snapshot(ticket) if not creating else None
    fields = {
        'source_serial': values['source_serial'],
        'outage_date': date.fromisoformat(values['outage_date']),
        'project': project,
        'circle': circle,
        'master_site': site,
        'site_id': values['site_id'],
        'site_key': site.site_key,
        'site_name': values['site_name'],
        'oa': values['oa'],
        'ba': values['ba'],
        'actual_down_time': _as_aware(values['actual_down_time']),
        'reporting_time_to_partner': _as_aware(values['reporting_time_to_partner']) if values['reporting_time_to_partner'] else None,
        'restoration_time': _as_aware(values['restoration_time']) if values['restoration_time'] else None,
        'outage_minutes': Decimal(values['outage_minutes']) if values['outage_minutes'] else None,
        'mttr_hours': Decimal(values['mttr_hours']) if values['mttr_hours'] else None,
        'vendor_name': values['vendor_name'],
        'outage_bucket': values['outage_bucket'],
        'detail_rca': values['detail_rca'],
        'status': values['status'],
        'email_id': values['email_id'] or (ticket.email_id if ticket.pk else ''),
        'source_values': values['source_values'],
        'updated_by': user,
        'last_batch': batch,
        'last_uploaded_at': committed_at,
    }
    for field, value in fields.items():
        setattr(ticket, field, value)
    ticket.save()
    after = snapshot(ticket)
    return {'before': before, 'after': after}


def _as_aware(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    return timezone.make_aware(result, timezone.get_current_timezone()) if timezone.is_naive(result) else result


def visible_tickets(user, action: str = 'view'):
    from apps.accounts.access import pairs_for, pairs_q

    pairs = pairs_for(user, 'ticket_management', action)
    return Ticket.objects.filter(pairs_q(pairs, 'project', 'circle'))


def ticket_summary(ticket: Ticket) -> dict:
    return {
        'id': ticket.pk,
        'portal_ticket_id': ticket.portal_ticket_id,
        'source_serial': ticket.source_serial,
        'outage_date': ticket.outage_date.isoformat(),
        'project': ticket.project,
        'circle': ticket.circle,
        'site_id': ticket.site_id,
        'site_name': ticket.site_name,
        'oa': ticket.oa,
        'ba': ticket.ba,
        'actual_down_time': ticket.actual_down_time.isoformat(),
        'reporting_time_to_partner': ticket.reporting_time_to_partner.isoformat() if ticket.reporting_time_to_partner else None,
        'restoration_time': ticket.restoration_time.isoformat() if ticket.restoration_time else None,
        'outage_minutes': str(ticket.outage_minutes) if ticket.outage_minutes is not None else None,
        'mttr_hours': str(ticket.mttr_hours) if ticket.mttr_hours is not None else None,
        'vendor_name': ticket.vendor_name,
        'outage_bucket': ticket.outage_bucket,
        'detail_rca': ticket.detail_rca,
        'status': ticket.status,
        'email_id': ticket.email_id,
        'created_by': actor_name(ticket.created_by) if ticket.created_by_id else '',
        'created_at': ticket.created_at.isoformat(),
        'updated_at': ticket.updated_at.isoformat(),
        'last_uploaded_at': ticket.last_uploaded_at.isoformat(),
        'created_batch': ticket.created_batch_id,
        'last_batch': ticket.last_batch_id,
        'closure_remarks': ticket.closure_remarks,
        'closed_by': actor_name(ticket.closed_by) if ticket.closed_by_id else '',
        'closed_at': ticket.closed_at.isoformat() if ticket.closed_at else None,
        'closure_source': ticket.closure_source,
        'source_values': ticket.source_values,
    }


def ticket_detail(ticket: Ticket) -> dict:
    data = ticket_summary(ticket)
    data['events'] = [{
        'id': event.pk, 'action': event.action, 'source': event.source, 'actor': event.actor_name,
        'status_before': event.status_before, 'status_after': event.status_after, 'remarks': event.remarks,
        'changes': event.changes, 'batch_id': event.batch_id, 'created_at': event.created_at.isoformat(),
    } for event in ticket.events.select_related('actor', 'batch').all()]
    data['notifications'] = [{
        'id': notification.pk, 'kind': notification.kind, 'recipient': notification.recipient,
        'status': notification.status, 'attempts': notification.attempts, 'sent_at': notification.sent_at.isoformat() if notification.sent_at else None,
        'created_at': notification.created_at.isoformat(), 'error': notification.error, 'smtp_response': notification.smtp_response,
        'attempt_log': [{
            'number': attempt.number, 'attempted_by': actor_name(attempt.attempted_by) if attempt.attempted_by_id else 'system',
            'attempted_at': attempt.attempted_at.isoformat(), 'accepted_at': attempt.accepted_at.isoformat() if attempt.accepted_at else None,
            'accepted': attempt.accepted, 'detail': attempt.detail,
        } for attempt in notification.attempt_log.select_related('attempted_by').all()],
    } for notification in ticket.notifications.all()]
    return data


def import_row_json(row) -> dict:
    return {
        'excel_row': row.excel_row,
        'outcome': row.result_outcome or row.preview_outcome,
        'preview_outcome': row.preview_outcome,
        'source_values': row.row_data.get('source_values', {}),
        'errors': row.errors,
        'portal_ticket_id': row.ticket.portal_ticket_id if row.ticket_id else None,
        'notification_id': row.notification_id,
    }
