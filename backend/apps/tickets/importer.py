from __future__ import annotations

from datetime import date, datetime
from hashlib import sha256

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.access import can
from apps.accounts.roles import ADMIN, role_of
from apps.organization import services as organization
from apps.organization.models import Circle, CircleAlias
from apps.sitedata.identifiers import IdentifierIndex, key_of
from apps.sitedata.models import Site, SiteIdentifier

from . import parser, services
from .models import Ticket, TicketEvent, TicketImportRow, TicketNotification, TicketStatus, TicketUploadBatch


class ImportConflict(Exception):
    status_code = 409


def _match_key(site_key: str, values: dict) -> tuple[str, str, str]:
    when = datetime.fromisoformat(values['actual_down_time'])
    if timezone.is_aware(when):
        when = timezone.localtime(when).replace(tzinfo=None)
    when = when.isoformat(sep=' ')
    return site_key, values['outage_date'], when


def _ticket_key(ticket: Ticket) -> tuple[str, str, str]:
    local = timezone.localtime(ticket.actual_down_time).replace(tzinfo=None)
    return ticket.site_key, ticket.outage_date.isoformat(), local.isoformat(sep=' ')


def _circle(raw: str, resolver: organization.AliasResolver, project: str | None = None) -> str | None:
    code = resolver.resolve(raw, project)
    if code:
        return code
    circle = Circle.objects.filter(name__iexact=raw.strip()).only('code').first()
    return circle.code if circle else None


def _prepare(rows: list[dict], user) -> list[dict]:
    candidates = [row for row in rows if row.get('outcome') == 'valid']
    if not candidates:
        return []

    index = IdentifierIndex()
    resolver = organization.AliasResolver(CircleAlias.Source.TICKET_UPLOAD)
    prepared = []
    for row in candidates:
        values = row['values']
        errors = []
        site_id = values['site_id']
        if index.is_blocked(SiteIdentifier.Kind.BSNL_SITE_ID, site_id):
            errors.append({'field': 'Site ID', 'message': 'This Site ID is blocked by a master-data identifier conflict.'})
            site = None
        else:
            site = index.get(SiteIdentifier.Kind.BSNL_SITE_ID, site_id)
            if site is None:
                site = Site.objects.filter(site_key=key_of(site_id)).first()
            if site is None:
                errors.append({'field': 'Site ID', 'message': 'This Site ID is not present in the existing site master.'})

        project = ''
        if site is not None:
            if site.reporting_scope != Site.Scope.DASHBOARD or not site.technology:
                errors.append({'field': 'Site ID', 'message': 'This site is outside the configured project reporting scope.'})
            else:
                project = site.technology
        circle = _circle(values['circle_raw'], resolver, project or None)
        if circle is None:
            errors.append({'field': 'Circle', 'message': 'This Circle is not configured in Organization. Ask an Admin to configure the circle or its ticket-upload alias.'})

        if site is not None:
            if circle and site.circle != circle:
                errors.append({'field': 'Circle', 'message': f'The Site Master assigns this Site ID to {site.circle}, not {circle}.'})
            if project and circle and not organization.is_associated(project, circle):
                errors.append({'field': 'Circle', 'message': f'{circle} is not an active Organization circle for {project}.'})
            if project and circle and not can(user, 'ticket_management', 'upload', project, circle):
                errors.append({'field': 'Circle', 'message': 'You do not have ticket upload access for this project and circle.'})

        item = {'row': row, 'site': site, 'project': project, 'circle': circle or '', 'errors': errors}
        prepared.append(item)

    by_key: dict[tuple[str, str, str], list[dict]] = {}
    for item in prepared:
        if not item['errors'] and item['site'] is not None:
            by_key.setdefault(_match_key(item['site'].site_key, item['row']['values']), []).append(item)
    for matches in by_key.values():
        if len(matches) > 1:
            excel_rows = ', '.join(str(item['row']['excel_row']) for item in matches)
            for item in matches:
                item['errors'].append({
                    'field': 'Site ID / Date / Actual Down Time',
                    'message': f'The outage key is ambiguous within this workbook (Excel rows {excel_rows}). Resolve the duplicate rows before importing.',
                })

    site_keys = sorted({item['site'].site_key for item in prepared if item['site'] is not None and not item['errors']})
    existing: dict[tuple[str, str, str], Ticket] = {}
    for offset in range(0, len(site_keys), 500):
        chunk = site_keys[offset:offset + 500]
        for ticket in Ticket.objects.filter(site_key__in=chunk).select_related('master_site', 'created_by', 'updated_by'):
            existing[_ticket_key(ticket)] = ticket

    for item in prepared:
        if item['errors']:
            continue
        key = _match_key(item['site'].site_key, item['row']['values'])
        ticket = existing.get(key)
        item['existing'] = ticket
        if ticket is not None and not can(user, 'ticket_management', 'upload', ticket.project, ticket.circle):
            item['errors'].append({'field': 'Site ID / Date / Actual Down Time', 'message': 'You do not have access to update the matching ticket.'})
            continue
        status_value = item['row']['values']['status']
        if ticket is None:
            item['outcome'] = 'create' if status_value == TicketStatus.OPEN else 'closed_skipped'
        elif ticket.status == TicketStatus.OPEN and status_value == TicketStatus.OPEN:
            item['outcome'] = 'update'
        elif ticket.status == TicketStatus.OPEN and status_value == TicketStatus.CLOSED:
            item['outcome'] = 'auto_close'
        elif ticket.status == TicketStatus.CLOSED and status_value == TicketStatus.OPEN:
            item['outcome'] = 'reopen'
        else:
            item['outcome'] = 'closed_update'
    return prepared


def _counts(rows: list[dict], prepared: list[dict], blank_rows: int = 0, sample_rows: int = 0) -> dict:
    outcomes = [item.get('outcome') for item in prepared if not item['errors']]
    invalid_rows = sum(1 for row in rows if row.get('outcome') == 'invalid')
    return {
        'total_rows': sum(1 for row in rows if row.get('outcome') != 'sample_skipped'),
        'blank_rows': blank_rows,
        'sample_rows_skipped': sample_rows,
        'invalid_rows': invalid_rows,
        'valid_rows': len(outcomes),
        'new_tickets': outcomes.count('create'),
        'existing_tickets_updated': outcomes.count('update') + outcomes.count('closed_update'),
        'tickets_closed': outcomes.count('auto_close'),
        'tickets_reopened': outcomes.count('reopen'),
        'closed_rows_skipped': outcomes.count('closed_skipped'),
        'notifications_attempted': 0,
        'notifications_failed': 0,
    }


def preview(contents: bytes, filename: str, user) -> TicketUploadBatch:
    checksum = sha256(contents).hexdigest()
    batch = TicketUploadBatch.objects.create(
        original_filename=filename[:255], checksum_sha256=checksum, file_size=len(contents),
        uploaded_by=user, status=TicketUploadBatch.Status.FAILED,
    )
    try:
        parsed = parser.parse_workbook(contents)
    except parser.WorkbookError as exc:
        batch.error = str(exc)
        batch.save(update_fields=['error'])
        return batch

    rows = parsed['rows']
    prepared = _prepare(rows, user)
    by_excel_row = {item['row']['excel_row']: item for item in prepared}
    for row in rows:
        item = by_excel_row.get(row['excel_row'])
        if item is not None:
            row['errors'].extend(item['errors'])
            if item['errors']:
                row['outcome'] = 'invalid'
            else:
                row['outcome'] = item['outcome']

    prepared_rows = [{**row, 'outcome': row.get('outcome', 'invalid')} for row in rows]
    counts = _counts(prepared_rows, prepared, parsed['counts']['blank_rows'], parsed['counts']['sample_rows_skipped'])
    duplicate = TicketUploadBatch.objects.filter(checksum_sha256=checksum, status=TicketUploadBatch.Status.COMMITTED).order_by('-committed_at').first()
    batch.duplicate_of = duplicate
    batch.counts = counts
    batch.status = TicketUploadBatch.Status.PREVIEWED
    batch.save()
    for row in rows:
        TicketImportRow.objects.create(batch=batch, excel_row=row['excel_row'], preview_outcome=row['outcome'],
                                       row_data={'values': row.get('values', {}), 'source_values': row.get('source_values', {})},
                                       errors=row.get('errors', []))
    return batch


def _raw_rows(batch: TicketUploadBatch) -> list[dict]:
    rows = []
    for row in batch.rows.all():
        outcome = row.preview_outcome
        parse_outcome = 'sample_skipped' if outcome == 'sample_skipped' else 'invalid' if outcome == 'invalid' else 'valid'
        values = dict(row.row_data.get('values', {}))
        values['source_values'] = row.row_data.get('source_values', {})
        rows.append({
            'excel_row': row.excel_row,
            'source_values': row.row_data.get('source_values', {}),
            'values': values,
            'errors': row.errors,
            'outcome': parse_outcome,
        })
    return rows


def commit(batch_id: int, user, *, accept_invalid: bool = False, confirm_duplicate: bool = False) -> TicketUploadBatch:
    pending_notifications: list[TicketNotification] = []
    try:
        identity = TicketUploadBatch.objects.filter(pk=batch_id).values('checksum_sha256').first()
        if identity is None:
            raise TicketUploadBatch.DoesNotExist
        with transaction.atomic():
            locked_batches = list(TicketUploadBatch.objects.select_for_update().filter(
                checksum_sha256=identity['checksum_sha256']).order_by('pk'))
            batch = next((item for item in locked_batches if item.pk == batch_id), None)
            if batch is None:
                raise TicketUploadBatch.DoesNotExist
            if batch.uploaded_by_id != user.pk and role_of(user) != ADMIN:
                raise ImportConflict('You may only confirm your own ticket upload.')
            if batch.status == TicketUploadBatch.Status.COMMITTED:
                return batch
            if batch.status != TicketUploadBatch.Status.PREVIEWED:
                raise ImportConflict('This ticket upload is not ready to commit.')
            duplicate = next((item for item in locked_batches
                              if item.pk != batch.pk and item.status == TicketUploadBatch.Status.COMMITTED), None)
            if (batch.duplicate_of_id or duplicate) and not confirm_duplicate:
                raise ImportConflict('This exact workbook was already imported. Confirm the duplicate upload to process it again.')

            rows = _raw_rows(batch)
            work_rows = [row for row in rows if row['outcome'] != 'sample_skipped' and row['outcome'] != 'invalid']
            prepared = _prepare(work_rows, user)
            by_excel_row = {item['row']['excel_row']: item for item in prepared}
            newly_invalid = sum(1 for item in prepared if item['errors'])
            existing_invalid = sum(1 for row in rows if row['outcome'] == 'invalid')
            if (newly_invalid or existing_invalid) and not accept_invalid:
                raise ImportConflict('The preview contains invalid rows. Review them and explicitly continue with valid rows only, or discard the batch.')
            committed_at = timezone.now()
            counts = {
                'total_rows': batch.counts.get('total_rows', len(rows)),
                'blank_rows': batch.counts.get('blank_rows', 0),
                'sample_rows_skipped': batch.counts.get('sample_rows_skipped', 0),
                'invalid_rows': existing_invalid + newly_invalid,
                'valid_rows': 0,
                'new_tickets': 0,
                'existing_tickets_updated': 0,
                'tickets_closed': 0,
                'tickets_reopened': 0,
                'closed_rows_skipped': 0,
                'notifications_attempted': 0,
                'notifications_failed': 0,
            }

            for import_row in batch.rows.select_for_update().order_by('excel_row'):
                if import_row.preview_outcome == 'sample_skipped':
                    import_row.result_outcome = 'sample_skipped'
                    import_row.save(update_fields=['result_outcome'])
                    continue
                item = by_excel_row.get(import_row.excel_row)
                if import_row.preview_outcome == 'invalid' or item is None or item['errors']:
                    import_row.result_outcome = 'invalid'
                    if item and item['errors']:
                        import_row.errors = item['errors']
                    import_row.save(update_fields=['result_outcome', 'errors'])
                    continue

                values = item['row']['values']
                key = _match_key(item['site'].site_key, values)
                ticket = Ticket.objects.select_for_update().filter(
                    site_key=key[0], outage_date=date.fromisoformat(key[1]),
                    actual_down_time=services._as_aware(values['actual_down_time']),
                ).first()
                if ticket is not None and not can(user, 'ticket_management', 'upload', ticket.project, ticket.circle):
                    raise ImportConflict('The matching ticket scope changed during import. Refresh the preview and try again.')
                old_status = ticket.status if ticket else ''
                if ticket is None and values['status'] == TicketStatus.CLOSED:
                    import_row.result_outcome = 'closed_skipped'
                    counts['closed_rows_skipped'] += 1
                    counts['valid_rows'] += 1
                    import_row.save(update_fields=['result_outcome'])
                    continue

                creating = ticket is None
                old = services.snapshot(ticket) if ticket else None
                if creating:
                    ticket = Ticket(
                        portal_ticket_id=services.generate_ticket_id(),
                        created_by=user,
                        created_batch=batch,
                    )
                changes = services.apply_excel_row(ticket, values, site=item['site'], project=item['project'], circle=item['circle'],
                                                   batch=batch, user=user, committed_at=committed_at, creating=creating)
                notification_kind = None
                action = 'created' if creating else 'updated_by_import'
                outcome = item['outcome']

                if creating:
                    counts['new_tickets'] += 1
                    notification_kind = TicketNotification.Kind.CREATED
                elif old_status == TicketStatus.OPEN and values['status'] == TicketStatus.CLOSED:
                    ticket.status = TicketStatus.CLOSED
                    ticket.closed_at = committed_at
                    ticket.closed_by = None
                    ticket.closure_source = 'excel_import'
                    ticket.closure_remarks = ''
                    ticket.save()
                    action = 'closed_by_import'
                    outcome = 'auto_close'
                    counts['tickets_closed'] += 1
                elif old_status == TicketStatus.CLOSED and values['status'] == TicketStatus.OPEN:
                    ticket.status = TicketStatus.OPEN
                    ticket.save()
                    action = 'reopened_by_import'
                    outcome = 'reopen'
                    counts['tickets_reopened'] += 1
                    notification_kind = TicketNotification.Kind.REOPENED
                else:
                    counts['existing_tickets_updated'] += 1
                    if old_status == TicketStatus.OPEN:
                        notification_kind = TicketNotification.Kind.UPDATED
                    elif old_status == TicketStatus.CLOSED:
                        outcome = 'closed_update'

                services.record_event(
                    ticket, action=action, source=TicketEvent.Source.EXCEL, actor=user, batch=batch,
                    status_before=old_status, status_after=ticket.status,
                    changes={'before': old, 'after': services.snapshot(ticket), 'source_values': values['source_values']},
                )
                notification = services.queue_notification(ticket, kind=notification_kind, batch=batch) if notification_kind else None
                import_row.ticket = ticket
                import_row.notification = notification
                import_row.result_outcome = outcome
                import_row.save(update_fields=['ticket', 'notification', 'result_outcome'])
                if notification is not None:
                    pending_notifications.append(notification)
                    counts['notifications_attempted'] += 1
                counts['valid_rows'] += 1

            batch.status = TicketUploadBatch.Status.COMMITTED
            batch.committed_at = committed_at
            batch.counts = counts
            batch.error = ''
            batch.save(update_fields=['status', 'committed_at', 'counts', 'error'])
    except TicketUploadBatch.DoesNotExist as exc:
        raise ImportConflict('No such ticket upload batch.') from exc
    except IntegrityError as exc:
        raise ImportConflict('A matching outage or ticket ID was created concurrently. Refresh the upload preview and try again.') from exc

    for notification in pending_notifications:
        services.send_notification(notification, by=user)
    batch.refresh_from_db()
    counts = dict(batch.counts)
    counts['notifications_failed'] = TicketNotification.objects.filter(batch=batch, status=TicketNotification.Status.FAILED).count()
    batch.counts = counts
    batch.save(update_fields=['counts'])
    return batch
