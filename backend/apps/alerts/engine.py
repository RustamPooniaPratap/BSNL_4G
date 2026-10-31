"""Runs automations: decides the emails of a run (plan), sends them (send_message) and drives schedules (tick).

- Reminders go out only for genuinely pending work, from the trackers' own calculations: the CSV Arrival Tracker
  (stored daily data of the On-Air sites, uploads.arrivals) and the RCA Submissions Tracker's circle submissions
  (committed *circle* uploads only, rca.cycles). One email per pending project and circle, to the users granted that
  project and circle (Organization › User Access) when ``include_responsible``, plus the configured recipients.
- Reports go to the recipients either as one email (same report) or one per portal user with the report limited to the
  circles that user may see; external addresses get the automation's own scope.
- Duplicates: one run per schedule slot and per event (Execution.dedupe_key); a message is sent once, retried only when
  it failed (up to MAX_ATTEMPTS automatically, and on an Admin's Retry), and a run interrupted while sending is not
  resent automatically.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.roles import ADMIN, NOC_LEAD, role_of
from apps.accounts.access import can, pairs_for

from . import mailer, reports
from .models import AlertFile, Attempt, Automation, EmailAccount, Execution, Message
from .schedule import next_run

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 3
RETRY_AFTER = (timedelta(minutes=5), timedelta(minutes=15))
STALE = timedelta(minutes=20)
User = get_user_model()


class NotReady(Exception):
    pass


def clean_emails(values) -> list[str]:
    """Valid, lower-cased, de-duplicated addresses (raises ValidationError naming the first invalid one)."""
    out = []
    for v in values or []:
        e = str(v).strip().lower()
        if not e:
            continue
        validate_email(e)
        if e not in out:
            out.append(e)
    return out


def active_account() -> EmailAccount:
    account = EmailAccount.objects.filter(is_active=True).first()
    if account is None:
        raise NotReady('No email account is active. Configure, test and activate it on Alert › Email Setup.')
    return account


def responsible_users(project: str, circle: str, module: str = 'csv_upload') -> list:
    """Active users assigned this project and circle with the upload permission of ``module`` (CSV Upload or RCA Upload),
    with an email address. Admins and NOC Leads (every circle) are not counted as responsible for one circle."""
    return [u for u in User.objects.filter(is_active=True, access_assignments__isnull=False).exclude(email='').distinct()
            if role_of(u) not in (ADMIN, NOC_LEAD) and can(u, module, 'upload', project, circle)]


def _recipients(a: Automation):
    users = [u for u in a.to_users.filter(is_active=True).exclude(email='')]
    return users, clean_emails(a.to_emails), clean_emails(a.cc), clean_emails(a.bcc)


def _message(execution: Execution, a: Automation, *, to: list[str], cc: list[str], bcc: list[str], names: list[str], values: dict,
             spec: dict) -> Message | None:
    to = [e for e in dict.fromkeys(to) if e]
    cc = [e for e in dict.fromkeys(cc) if e and e not in to]
    bcc = [e for e in dict.fromkeys(bcc) if e and e not in to and e not in cc]
    if not (to or cc or bcc):
        return None
    planned = [{'name': reports.CATALOG[r['report']]['label'], 'report': r['report'], 'format': r.get('format', ''), 'period': values.get('report_period', '')}
               for r in spec.get('reports', [])]
    if spec.get('extra_file'):
        f = AlertFile.objects.filter(pk=spec['extra_file']).first()
        if f:
            planned.append({'name': f.name, 'report': 'file', 'format': f.name.rsplit('.', 1)[-1], 'period': '—'})
    subject, text, html = mailer.render(a.template, a.subject, a.message, {'recipient_name': ', '.join(names) or 'Colleague', **values}, planned)
    return Message.objects.create(execution=execution, to=to, cc=cc, bcc=bcc, recipient_names=names, subject=subject, text=text, html=html,
                                  attachments=planned, attachment_spec=spec)


def plan(execution: Execution) -> list[Message]:
    """The emails of one run (stored as queued messages); none when nothing is pending."""
    a = execution.automation
    users, emails, cc, bcc = _recipients(a)
    base = {'reports': a.attachments, 'day': a.report_day, 'extra_file': a.extra_file_id}
    project_name = a.project or 'All projects'
    circle_name = ', '.join(a.circles) or 'All circles'
    msgs = []
    if a.kind in (Automation.Kind.CSV_REMINDER, Automation.Kind.RCA_REMINDER):
        for p, c, day, status in pending(a):
            responsible = responsible_users(p, c, 'rca_upload' if a.kind == Automation.Kind.RCA_REMINDER else 'csv_upload') if a.include_responsible else []
            spec = {**base, 'pairs': [[p, c]]}
            title = 'CSV Submission Pending' if a.kind == Automation.Kind.CSV_REMINDER else 'RCA Submission Pending'
            note = (f'The daily CSV of {c} ({p}) for {day:%d %b %Y} has not been fully received. Please upload it.'
                    if a.kind == Automation.Kind.CSV_REMINDER else
                    f'The circle RCA file of {c} ({p}) for {day:%d %b %Y} has not been submitted. Please upload it through Upload Circle RCA.')
            msgs.append(_message(execution, a, to=[u.email.lower() for u in [*users, *responsible]] + emails, cc=cc, bcc=bcc,
                                 names=[u.get_full_name() or u.get_username() for u in responsible] or [u.get_full_name() or u.get_username() for u in users],
                                 values={'notification_title': title, 'notification_message': note, 'project_name': p, 'circle_name': c,
                                         'report_date': f'{day:%d %b %Y}', 'status': status}, spec=spec))
    elif a.kind == Automation.Kind.UPLOAD_FAILURE:
        ev = execution.event
        uploader = User.objects.filter(pk=ev.get('uploader_id'), is_active=True).exclude(email='').first() if a.include_responsible else None
        msgs.append(_message(execution, a, to=[u.email.lower() for u in [*users, *([uploader] if uploader else [])]] + emails, cc=cc, bcc=bcc,
                             names=[uploader.get_full_name() or uploader.get_username()] if uploader else [],
                             values={'notification_title': f"{ev.get('label', 'Upload')} failed", 'notification_message':
                                     f"The upload of {ev.get('file', 'a file')} could not be imported: {ev.get('reason', 'see the upload page')}",
                                     'project_name': ev.get('project', ''), 'circle_name': ev.get('circle', ''), 'report_date': ev.get('date', ''),
                                     'status': ev.get('status', 'Failed')}, spec={**base, 'reports': []}))
    else:  # uptime report, custom email
        values = {'project_name': project_name, 'circle_name': circle_name, 'report_name': a.name, 'report_period': _period_text(a),
                  'notification_title': a.name, 'notification_message': '', 'report_date': _period_text(a), 'status': ''}
        scope = reports.scope_pairs(a.project, a.circles, None)
        if a.distribution == Automation.Distribution.PER_RECIPIENT:
            for u in users:
                pairs = reports.scope_pairs(a.project, a.circles, pairs_for(u, 'dashboard', 'export'))
                msgs.append(_message(execution, a, to=[u.email.lower()], cc=[], bcc=[], names=[u.get_full_name() or u.get_username()], values=values,
                                     spec={**base, 'pairs': None if pairs is None else sorted(map(list, pairs))}))
            if emails or cc or bcc:
                msgs.append(_message(execution, a, to=emails, cc=cc, bcc=bcc, names=[], values=values,
                                     spec={**base, 'pairs': None if scope is None else sorted(map(list, scope))}))
        else:
            msgs.append(_message(execution, a, to=[u.email.lower() for u in users] + emails, cc=cc, bcc=bcc,
                                 names=[u.get_full_name() or u.get_username() for u in users], values=values,
                                 spec={**base, 'pairs': None if scope is None else sorted(map(list, scope))}))
    return [m for m in msgs if m]


def _period_text(a: Automation) -> str:
    return {'today': 'Today', 'yesterday': 'Previous day', 'latest': 'Latest reporting date'}.get(a.report_day, a.report_day)


def pending(a: Automation) -> list[tuple[str, str, object, str]]:
    """(project, circle, reporting date, status) still pending in the automation's scope, from the trackers."""
    pairs = reports.scope_pairs(a.project, a.circles, None)
    out = []
    if a.kind == Automation.Kind.CSV_REMINDER:
        from apps.uptimedb import arrivals
        day = reports.reporting_day(a.report_day, None)
        for i in arrivals.tracker(day, pairs)['items']:
            if i['sites_expected'] and i['data_state'] in ('none', 'partial') and i['upload_state'] != 'imported':
                out.append((i['project'], i['circle'], day, f"{i['sites_with_data']} of {i['sites_expected']} sites with data"))
    else:
        from apps.rca import cycles
        day = reports.reporting_day(a.report_day, None)
        cycle = cycles.containing_cycle(day)
        if cycle is not None:
            for u in cycles.unit_states(cycle):
                if u['submission_status'] != 'received' and (pairs is None or (u['project'], u['circle']) in pairs):
                    out.append((u['project'], u['circle'], day, 'Circle RCA file not received'))
    return out


def attachments_for(msg: Message) -> list[tuple[str, bytes, str]]:
    """Build the message's files now (same scope as planned); records the actual names and periods."""
    spec = msg.attachment_spec or {}
    pairs = None if spec.get('pairs') is None else {tuple(p) for p in spec['pairs']}
    files, meta = [], []
    for r in spec.get('reports', []):
        name, data, mime, period = reports.build(r['report'], spec.get('day', 'yesterday'), pairs)
        files.append((name, data, mime))
        meta.append({'name': name, 'report': r['report'], 'format': r.get('format', ''), 'period': period, 'size': len(data)})
    if spec.get('extra_file'):
        f = AlertFile.objects.filter(pk=spec['extra_file']).first()
        if f:
            data = reports.extra_file(f.stored_path)
            files.append((f.name, data, 'application/octet-stream'))
            meta.append({'name': f.name, 'report': 'file', 'format': f.name.rsplit('.', 1)[-1], 'period': '—', 'size': len(data)})
    msg.attachments = meta
    return files


def send_message(msg: Message, *, by=None) -> Message:
    """One attempt: build the files, send, record the attempt. Never raises for a mail or report failure."""
    msg.status, msg.attempts = Message.Status.PROCESSING, msg.attempts + 1
    msg.save(update_fields=['status', 'attempts'])
    try:
        account = active_account()
        files = attachments_for(msg)
        note = mailer.send(account, mailer.Outgoing(msg.to, msg.cc, msg.bcc, msg.subject, msg.text, msg.html, files))
        msg.status, msg.smtp_response, msg.error, msg.sent_at, msg.next_retry_at = Message.Status.ACCEPTED, note, '', timezone.now(), None
        Attempt.objects.create(message=msg, ok=True, detail=note, by=by)
    except (mailer.MailError, reports.ReportError, NotReady, OSError) as exc:
        msg.status, msg.error = Message.Status.FAILED, str(exc)[:2000]
        retry = msg.attempts < MAX_ATTEMPTS and not isinstance(exc, (reports.ReportError, NotReady))
        msg.next_retry_at = timezone.now() + RETRY_AFTER[min(msg.attempts - 1, len(RETRY_AFTER) - 1)] if retry else None
        Attempt.objects.create(message=msg, ok=False, detail=str(exc)[:500], by=by)
    msg.save()
    return msg


def finish(execution: Execution) -> None:
    states = list(execution.messages.values_list('status', flat=True))
    if not states:
        execution.status = Execution.Status.SKIPPED
        execution.detail = execution.detail or 'Nothing to send: no pending item or no recipient.'
    elif all(s == Message.Status.ACCEPTED for s in states):
        execution.status = Execution.Status.DONE
    elif any(s == Message.Status.ACCEPTED for s in states):
        execution.status = Execution.Status.PARTIAL
    elif any(s in (Message.Status.QUEUED, Message.Status.PROCESSING) for s in states):
        return
    else:
        execution.status = Execution.Status.FAILED
    execution.finished_at = timezone.now()
    execution.save(update_fields=['status', 'detail', 'finished_at'])


def process(execution: Execution) -> Execution:
    execution.status, execution.started_at = Execution.Status.PROCESSING, timezone.now()
    execution.save(update_fields=['status', 'started_at'])
    if execution.automation is None:
        execution.status, execution.detail = Execution.Status.FAILED, 'The automation was deleted.'
        execution.save(update_fields=['status', 'detail'])
        return execution
    try:
        msgs = plan(execution)
    except Exception as exc:  # a tracker or scope error: recorded, never retried in a loop
        logger.exception('Alert run %s could not be planned', execution.pk)
        execution.status, execution.detail, execution.finished_at = Execution.Status.FAILED, f'Could not prepare the emails: {exc}'[:2000], timezone.now()
        execution.save(update_fields=['status', 'detail', 'finished_at'])
        return execution
    for m in msgs:
        send_message(m)
    finish(execution)
    return execution


def queue(a: Automation, *, trigger: str, dedupe_key: str | None = None, event: dict | None = None, by=None,
          scheduled_for=None) -> Execution | None:
    """A new run, unless one with the same dedupe key exists (a second scheduler tick or a repeated event)."""
    try:
        with transaction.atomic():
            return Execution.objects.create(automation=a, automation_name=a.name, trigger=trigger, dedupe_key=dedupe_key, event=event or {},
                                            requested_by=by, scheduled_for=scheduled_for)
    except IntegrityError:
        return None


def tick(now=None) -> dict:
    """One scheduler and worker pass: queue due runs, recover interrupted work, send queued runs and due retries."""
    now = now or timezone.now()
    counts = {'queued': 0, 'processed': 0, 'retried': 0}
    with transaction.atomic():
        due = list(Automation.objects.select_for_update(skip_locked=True)
                   .filter(enabled=True, next_run_at__isnull=False, next_run_at__lte=now).exclude(frequency=Automation.Frequency.EVENT))
        for a in due:
            slot = a.next_run_at
            if queue(a, trigger='schedule', dedupe_key=f'{a.pk}:{slot.isoformat()}', scheduled_for=slot):
                counts['queued'] += 1
            a.last_run_at, a.next_run_at = now, next_run(a, max(slot, now))
            if a.next_run_at is None:
                a.enabled = False  # one-time or ended schedule
            a.save(update_fields=['last_run_at', 'next_run_at', 'enabled'])
    # Interrupted work (worker stopped): a message stuck while sending is failed (not resent blindly); a run is re-queued.
    Message.objects.filter(status=Message.Status.PROCESSING, execution__started_at__lt=now - STALE).update(
        status=Message.Status.FAILED, error='The worker stopped while sending; not resent automatically to avoid a duplicate. Use Retry.')
    Execution.objects.filter(status=Execution.Status.PROCESSING, started_at__lt=now - STALE, messages__isnull=True).update(status=Execution.Status.QUEUED)
    while True:
        with transaction.atomic():
            ex = Execution.objects.select_for_update(skip_locked=True).filter(status=Execution.Status.QUEUED).order_by('created_at').first()
            if ex is None:
                break
            ex.status, ex.started_at = Execution.Status.PROCESSING, timezone.now()
            ex.save(update_fields=['status', 'started_at'])
        process(ex)
        counts['processed'] += 1
    for msg in Message.objects.filter(status=Message.Status.FAILED, next_retry_at__lte=now, attempts__lt=MAX_ATTEMPTS):
        send_message(msg)
        finish(msg.execution)
        counts['retried'] += 1
    from apps.uptimedb.models import AppSetting
    AppSetting.objects.update_or_create(key='alerts_worker_heartbeat', defaults={'value': now.isoformat()})
    return counts

