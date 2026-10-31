"""Alert API (Administration › Alert). Admin only: email account, automations, preview, history, retry and resend.

The stored SMTP password is never returned; saving a changed connection deactivates the account until a new test email
succeeds. Automations can be enabled only while the account is active.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.accounts.audit import audit
from apps.accounts.permissions import IsAdminRole
from apps.accounts.roles import ROLES, role_of
from apps.organization.services import circle_codes, project_keys

from . import engine, mailer, reports
from .models import AlertFile, Automation, EmailAccount, Execution, Message
from .schedule import next_run

User = get_user_model()
CONNECTION_FIELDS = ('host', 'port', 'security', 'auth', 'username', 'from_email')
KIND_DEFAULTS = {
    Automation.Kind.CSV_REMINDER: {'template': 'reminder', 'frequency': 'daily', 'report_day': 'yesterday',
                                   'description': 'Reminds the responsible users of each circle whose daily CSV data is not complete (CSV Arrival Tracker).'},
    Automation.Kind.RCA_REMINDER: {'template': 'reminder', 'frequency': 'daily', 'report_day': 'yesterday',
                                   'description': 'Reminds circles that have not uploaded their own circle RCA file (RCA Submissions; consolidated uploads never count).'},
    Automation.Kind.UPTIME_REPORT: {'template': 'report', 'frequency': 'daily', 'report_day': 'latest',
                                    'description': 'Generates the selected uptime reports and emails them on a daily, weekly or monthly schedule.'},
    Automation.Kind.UPLOAD_FAILURE: {'template': 'reminder', 'frequency': 'event', 'report_day': 'today',
                                     'description': 'Emails the uploader and/or chosen recipients when a raw CSV or RCA upload fails or is rejected.'},
    Automation.Kind.CUSTOM: {'template': 'report', 'frequency': 'once', 'report_day': 'latest',
                             'description': 'Your own email with optional report attachments, once or on a schedule.'},
}


# --- Email account -------------------------------------------------------------------------------

def _account_json(a: EmailAccount | None) -> dict | None:
    if a is None:
        return None
    return {'id': a.id, 'name': a.name, 'host': a.host, 'port': a.port, 'security': a.security, 'auth': a.auth, 'username': a.username,
            'password_set': bool(a.password_encrypted), 'from_email': a.from_email, 'from_name': a.from_name, 'reply_to': a.reply_to,
            'timeout': a.timeout, 'is_active': a.is_active, 'tested_ok_at': a.tested_ok_at.isoformat() if a.tested_ok_at else None,
            'last_test': a.last_test, 'updated_at': a.updated_at.isoformat()}


class AccountSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    host = serializers.CharField(max_length=200)
    port = serializers.IntegerField(min_value=1, max_value=65535)
    security = serializers.ChoiceField(choices=EmailAccount.Security.values)
    auth = serializers.ChoiceField(choices=EmailAccount.Auth.values)
    username = serializers.CharField(max_length=200, required=False, allow_blank=True)
    password = serializers.CharField(max_length=500, required=False, allow_blank=True, write_only=True)  # blank: keep the stored one
    from_email = serializers.EmailField()
    from_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    reply_to = serializers.EmailField(required=False, allow_blank=True)
    timeout = serializers.IntegerField(min_value=3, max_value=120)

    def validate(self, attrs):
        if attrs['auth'] == EmailAccount.Auth.PASSWORD and not attrs.get('username'):
            raise serializers.ValidationError({'username': 'Enter the username for SMTP authentication.'})
        return attrs


@api_view(['GET', 'PUT'])
@permission_classes([IsAdminRole])
def account(request):
    a = EmailAccount.objects.order_by('-updated_at').first()
    if request.method == 'GET':
        return Response({'account': _account_json(a), 'worker': _worker()})
    data = AccountSerializer(data=request.data)
    data.is_valid(raise_exception=True)
    v = data.validated_data
    a = a or EmailAccount()
    changed = any(getattr(a, f, None) != v.get(f, getattr(a, f, '')) for f in CONNECTION_FIELDS) or bool(v.get('password'))
    for f in ('name', 'host', 'port', 'security', 'auth', 'username', 'from_email', 'from_name', 'reply_to', 'timeout'):
        setattr(a, f, v.get(f, ''))
    if v.get('password'):
        a.password_encrypted = mailer.encrypt(v['password'])
    if a.auth == EmailAccount.Auth.PASSWORD and not a.password_encrypted:
        raise ValidationError({'password': 'Enter the password.'})
    if changed:  # a new connection must be tested again before automated emails use it
        a.is_active, a.tested_ok_at = False, None
    a.updated_by = request.user
    a.save()
    audit('alert_account_saved', request, host=a.host, deactivated=changed)
    return Response({'account': _account_json(a), 'worker': _worker()})


def _current_account() -> EmailAccount:
    a = EmailAccount.objects.order_by('-updated_at').first()
    if a is None:
        raise ValidationError({'form': 'Save the email configuration first.'})
    return a


@api_view(['POST'])
@permission_classes([IsAdminRole])
def account_test(request):
    """Test Connection (``to`` empty) or Send Test Email (``to``: one address). The real result is returned and kept."""
    a = _current_account()
    to = str(request.data.get('to') or '').strip()
    try:
        if to:
            engine.clean_emails([to])
            subject, text, html = mailer.render('reminder', 'Test email from the BSNL Reporting Portal', 'This is a test of the configured outgoing email account.',
                                                {'recipient_name': request.user.get_full_name() or request.user.get_username(),
                                                 'notification_title': 'Test email', 'status': 'Email setup test'}, [])
            note = mailer.send(a, mailer.Outgoing([to], [], [], subject, text, html, []))
            a.tested_ok_at, a.last_test = timezone.now(), f'Test email to {to}: {note}'
        else:
            note = mailer.test_connection(a)
            a.last_test = note
        ok = True
    except DjangoValidationError:
        raise ValidationError({'to': 'Enter a valid email address.'}) from None
    except mailer.MailError as exc:
        a.last_test, ok = str(exc)[:500], False
    a.save(update_fields=['tested_ok_at', 'last_test'])
    audit('alert_account_tested', request, ok=ok, kind='email' if to else 'connection')
    return Response({'ok': ok, 'message': a.last_test, 'account': _account_json(a)}, status=200 if ok else 502)


@api_view(['POST'])
@permission_classes([IsAdminRole])
def account_activate(request):
    a = _current_account()
    active = request.data.get('active') is True
    if active and not a.tested_ok_at:
        raise ValidationError({'form': 'Send a test email successfully before activating the account.'})
    a.is_active = active
    a.save(update_fields=['is_active'])
    if not active:  # nothing is sent while the account is off
        Automation.objects.filter(enabled=True).update(enabled=False)
    audit('alert_account_activated' if active else 'alert_account_deactivated', request)
    return Response({'account': _account_json(a)})


def _worker() -> dict:
    from apps.uptimedb.models import AppSetting
    seen = AppSetting.objects.filter(key='alerts_worker_heartbeat').values_list('value', flat=True).first()
    when = datetime.fromisoformat(seen) if seen else None
    return {'last_seen': seen, 'running': bool(when and timezone.now() - when < timedelta(minutes=3))}


# --- Automations ---------------------------------------------------------------------------------

def _automation_json(a: Automation) -> dict:
    return {'id': a.id, 'name': a.name, 'kind': a.kind, 'kind_label': a.get_kind_display(), 'enabled': a.enabled, 'frequency': a.frequency,
            'run_time': a.run_time.strftime('%H:%M') if hasattr(a.run_time, 'strftime') else str(a.run_time)[:5], 'timezone': a.timezone,
            'weekday': a.weekday, 'month_day': a.month_day, 'start_date': a.start_date.isoformat() if a.start_date else None,
            'end_date': a.end_date.isoformat() if a.end_date else None, 'next_run_at': a.next_run_at.isoformat() if a.next_run_at else None,
            'last_run_at': a.last_run_at.isoformat() if a.last_run_at else None, 'project': a.project, 'circles': a.circles, 'report_day': a.report_day,
            'to_users': list(a.to_users.values_list('id', flat=True)), 'to_emails': a.to_emails, 'cc': a.cc, 'bcc': a.bcc,
            'include_responsible': a.include_responsible, 'attachments': a.attachments, 'extra_file': a.extra_file_id,
            'extra_file_name': a.extra_file.name if a.extra_file else None, 'distribution': a.distribution, 'template': a.template,
            'subject': a.subject, 'message': a.message, 'updated_at': a.updated_at.isoformat()}


class AutomationSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150)
    kind = serializers.ChoiceField(choices=Automation.Kind.values)
    frequency = serializers.ChoiceField(choices=Automation.Frequency.values)
    run_time = serializers.TimeField()
    timezone = serializers.CharField(max_length=50)
    weekday = serializers.IntegerField(min_value=0, max_value=6, default=0)
    month_day = serializers.IntegerField(min_value=1, max_value=28, default=1)
    start_date = serializers.DateField(required=False, allow_null=True)
    end_date = serializers.DateField(required=False, allow_null=True)
    project = serializers.CharField(max_length=20, required=False, allow_blank=True, default='')
    circles = serializers.ListField(child=serializers.CharField(max_length=20), required=False, default=list)
    report_day = serializers.ChoiceField(choices=['today', 'yesterday', 'latest'], default='yesterday')
    to_users = serializers.ListField(child=serializers.IntegerField(), required=False, default=list)
    to_emails = serializers.ListField(child=serializers.CharField(max_length=254), required=False, default=list)
    cc = serializers.ListField(child=serializers.CharField(max_length=254), required=False, default=list)
    bcc = serializers.ListField(child=serializers.CharField(max_length=254), required=False, default=list)
    include_responsible = serializers.BooleanField(default=True)
    attachments = serializers.ListField(child=serializers.DictField(), required=False, default=list)
    extra_file = serializers.IntegerField(required=False, allow_null=True)
    distribution = serializers.ChoiceField(choices=Automation.Distribution.values, default='same')
    template = serializers.ChoiceField(choices=list(mailer.TEMPLATES))
    subject = serializers.CharField(max_length=200, required=False, allow_blank=True, default='')
    message = serializers.CharField(max_length=5000, required=False, allow_blank=True, default='')

    def validate(self, v):
        errors = {}
        try:
            ZoneInfo(v['timezone'])
        except (ZoneInfoNotFoundError, ValueError):
            errors['timezone'] = 'Unknown timezone.'
        event = v['kind'] == Automation.Kind.UPLOAD_FAILURE
        if event != (v['frequency'] == Automation.Frequency.EVENT):
            errors['frequency'] = 'Upload Failure Alerts run when an upload fails; every other automation needs a schedule.'
        if v['frequency'] == Automation.Frequency.ONCE and not v.get('start_date'):
            errors['start_date'] = 'Choose the date of the one-time email.'
        if v.get('start_date') and v.get('end_date') and v['end_date'] < v['start_date']:
            errors['end_date'] = 'The end date is before the start date.'
        if v['project'] and v['project'] not in project_keys():
            errors['project'] = 'Unknown project.'
        unknown = sorted({c.upper() for c in v['circles']} - circle_codes())
        if unknown:
            errors['circles'] = f'Unknown circle: {", ".join(unknown)}.'
        v['circles'] = sorted({c.upper() for c in v['circles']})
        for f in ('to_emails', 'cc', 'bcc'):
            try:
                v[f] = engine.clean_emails(v[f])
            except DjangoValidationError:
                errors[f] = 'Enter valid email addresses.'
        known_users = set(User.objects.filter(pk__in=v['to_users'], is_active=True).values_list('pk', flat=True))
        if set(v['to_users']) - known_users:
            errors['to_users'] = 'Choose active portal users.'
        atts = []
        for item in v['attachments']:
            report, fmt = item.get('report'), item.get('format')
            if report not in reports.CATALOG or fmt not in reports.CATALOG[report]['formats']:
                errors['attachments'] = f'Unsupported report or format: {report} {fmt}.'
                break
            atts.append({'report': report, 'format': fmt})
        v['attachments'] = list({(a['report'], a['format']): a for a in atts}.values())
        if v.get('extra_file') and not AlertFile.objects.filter(pk=v['extra_file']).exists():
            errors['extra_file'] = 'The uploaded file is no longer available.'
        bad = mailer.unknown_placeholders(v['subject'], v['message'])
        if bad:
            errors['message'] = f'Unknown placeholder: {", ".join("{{" + b + "}}" for b in bad)}.'
        if not (v['to_users'] or v['to_emails'] or v['cc'] or v['bcc'] or v['include_responsible']):
            errors['to_users'] = 'Choose at least one recipient.'
        if errors:
            raise serializers.ValidationError(errors)
        return v


def _save(a: Automation, v: dict) -> Automation:
    users = v.pop('to_users')
    v['extra_file_id'] = v.pop('extra_file', None)
    for k, val in v.items():
        setattr(a, k, val)
    a.next_run_at = next_run(a, timezone.now()) if a.enabled else None
    a.save()
    a.to_users.set(users)
    return a


@api_view(['GET', 'POST'])
@permission_classes([IsAdminRole])
def automations(request):
    if request.method == 'POST':
        data = AutomationSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        a = _save(Automation(created_by=request.user), dict(data.validated_data))
        audit('alert_automation_created', request, automation=a.pk, kind=a.kind)
        return Response({'automation': _automation_json(a)}, status=status.HTTP_201_CREATED)
    return Response({'automations': [_automation_json(a) for a in Automation.objects.prefetch_related('to_users').select_related('extra_file')]})


def _get(pk: int) -> Automation:
    a = Automation.objects.filter(pk=pk).first()
    if a is None:
        raise NotFound('No such automation.')
    return a


@api_view(['PUT', 'DELETE'])
@permission_classes([IsAdminRole])
def automation_detail(request, pk: int):
    a = _get(pk)
    if request.method == 'DELETE':
        audit('alert_automation_deleted', request, automation=a.pk)
        a.delete()  # its history stays (Execution.automation_name)
        return Response(status=status.HTTP_204_NO_CONTENT)
    data = AutomationSerializer(data=request.data)
    data.is_valid(raise_exception=True)
    a = _save(a, dict(data.validated_data))
    audit('alert_automation_updated', request, automation=a.pk)
    return Response({'automation': _automation_json(a)})


@api_view(['POST'])
@permission_classes([IsAdminRole])
def automation_enable(request, pk: int):
    a = _get(pk)
    enable = request.data.get('enabled') is True
    if enable and not EmailAccount.objects.filter(is_active=True).exists():
        raise ValidationError({'form': 'Activate the email account on Alert › Email Setup before enabling automations.'})
    a.enabled = enable
    a.next_run_at = next_run(a, timezone.now()) if enable else None
    if enable and a.frequency != Automation.Frequency.EVENT and a.next_run_at is None:
        raise ValidationError({'form': 'The schedule has no future run (check the date and end date).'})
    a.save(update_fields=['enabled', 'next_run_at'])
    audit('alert_automation_enabled' if enable else 'alert_automation_paused', request, automation=a.pk)
    return Response({'automation': _automation_json(a)})


@api_view(['POST'])
@permission_classes([IsAdminRole])
def automation_run(request, pk: int):
    """Run Now: queued for the worker (the same path as a schedule)."""
    a = _get(pk)
    if a.kind == Automation.Kind.UPLOAD_FAILURE:
        raise ValidationError({'form': 'Upload Failure Alerts run when an upload fails.'})
    if not EmailAccount.objects.filter(is_active=True).exists():
        raise ValidationError({'form': 'Activate the email account on Alert › Email Setup first.'})
    ex = engine.queue(a, trigger='manual', dedupe_key=f'{a.pk}:manual:{uuid.uuid4().hex}', by=request.user)
    audit('alert_automation_run', request, automation=a.pk)
    return Response({'execution': ex.pk, 'worker': _worker()}, status=status.HTTP_202_ACCEPTED)


@api_view(['POST'])
@permission_classes([IsAdminRole])
def automation_preview(request):
    """What a recipient will receive (sample values from the form) and the next run, without saving or sending."""
    data = AutomationSerializer(data=request.data)
    data.is_valid(raise_exception=True)
    v = data.validated_data
    a = Automation(**{k: val for k, val in v.items() if k not in ('to_users', 'extra_file')}, enabled=True)
    report = v['template'] == 'report'
    values = {'recipient_name': request.user.get_full_name() or request.user.get_username(), 'project_name': v['project'] or 'All projects',
              'circle_name': ', '.join(v['circles']) or 'All circles', 'report_date': 'the reporting date', 'status': 'Pending',
              'notification_title': a.get_kind_display(), 'notification_message': 'The circle\'s submission for the reporting date is pending.',
              'report_name': v['name'], 'report_period': {'today': 'Today', 'yesterday': 'Previous day', 'latest': 'Latest reporting date'}[v['report_day']]}
    if report:
        values['notification_title'] = v['name']
    files = [{'name': reports.CATALOG[x['report']]['label'], 'format': x['format'], 'period': values['report_period']} for x in v['attachments']]
    if v.get('extra_file'):
        f = AlertFile.objects.get(pk=v['extra_file'])
        files.append({'name': f.name, 'format': f.name.rsplit('.', 1)[-1], 'period': '—'})
    subject, text, html = mailer.render(v['template'], v['subject'], v['message'], values, files)
    nxt = next_run(a, timezone.now())
    return Response({'subject': subject, 'text': text, 'html': html, 'attachments': files, 'next_run_at': nxt.isoformat() if nxt else None})


@api_view(['GET'])
@permission_classes([IsAdminRole])
def options(request):
    users = User.objects.filter(is_active=True).exclude(email='').prefetch_related('groups').order_by('username')
    return Response({
        'kinds': [{'value': k, 'label': label, **{x: str(y) for x, y in KIND_DEFAULTS[k].items()}} for k, label in Automation.Kind.choices],
        'reports': [{'value': k, **v} for k, v in reports.CATALOG.items()],
        'templates': [{'value': k, 'label': t['label'], 'subject': t['subject'], 'message': mailer.DEFAULT_MESSAGES[k]} for k, t in mailer.TEMPLATES.items()],
        'placeholders': list(mailer.PLACEHOLDERS),
        'users': [{'id': u.pk, 'username': u.get_username(), 'name': u.get_full_name(), 'email': u.email, 'role': ROLES.get(role_of(u) or '', '')}
                  for u in users if role_of(u)],
        'timezone': settings.TIME_ZONE, 'max_file_bytes': reports.MAX_EXTRA_BYTES, 'file_types': sorted(reports.EXTRA_TYPES),
        'account_active': EmailAccount.objects.filter(is_active=True).exists(), 'worker': _worker(),
    })


@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser])
@permission_classes([IsAdminRole])
def upload_file(request):
    f = request.FILES.get('file')
    if f is None:
        raise ValidationError({'file': 'Choose a file.'})
    name = Path(f.name).name[:200]
    if Path(name).suffix.lower() not in reports.EXTRA_TYPES:
        raise ValidationError({'file': f'Allowed types: {", ".join(sorted(reports.EXTRA_TYPES))}.'})
    if f.size > reports.MAX_EXTRA_BYTES or not f.size:
        raise ValidationError({'file': f'The file must be between 1 byte and {reports.MAX_EXTRA_BYTES // (1024 * 1024)} MB.'})
    folder = Path(settings.DATA_DIR) / 'processed' / 'alert_files'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f'{uuid.uuid4().hex}{Path(name).suffix.lower()}'  # a generated name: the upload's name is never a path
    with path.open('wb') as out:
        for chunk in f.chunks():
            out.write(chunk)
    item = AlertFile.objects.create(name=name, stored_path=str(path), size=f.size, uploaded_by=request.user)
    audit('alert_file_uploaded', request, file=name)
    return Response({'id': item.pk, 'name': item.name, 'size': item.size}, status=status.HTTP_201_CREATED)


# --- History -------------------------------------------------------------------------------------

def _message_json(m: Message, *, full: bool = False) -> dict:
    ex = m.execution
    data = {'id': m.id, 'created_at': m.created_at.isoformat(), 'sent_at': m.sent_at.isoformat() if m.sent_at else None,
            'automation': ex.automation_name, 'automation_id': ex.automation_id, 'trigger': ex.trigger, 'execution': ex.pk,
            'to': m.to, 'cc': m.cc, 'bcc': m.bcc, 'subject': m.subject, 'attachments': m.attachments, 'status': m.status,
            'status_label': m.get_status_display(), 'attempts': m.attempts, 'error': m.error, 'smtp_response': m.smtp_response,
            'resend_of': m.resend_of_id}
    if full:
        data.update({'html': m.html, 'text': m.text, 'execution_status': ex.get_status_display(), 'execution_detail': ex.detail,
                     'attempt_log': [{'at': t.at.isoformat(), 'ok': t.ok, 'detail': t.detail, 'by': t.by.get_username() if t.by else 'worker'}
                                     for t in m.attempt_log.select_related('by')],
                     'resends': list(m.resends.values_list('id', flat=True))})
    return data


@api_view(['GET'])
@permission_classes([IsAdminRole])
def history(request):
    p = request.query_params
    qs = Message.objects.select_related('execution')
    if p.get('date_from'):
        qs = qs.filter(created_at__date__gte=p['date_from'])
    if p.get('date_to'):
        qs = qs.filter(created_at__date__lte=p['date_to'])
    if p.get('automation'):
        qs = qs.filter(execution__automation_id=p['automation'])
    if p.get('status'):
        qs = qs.filter(status=p['status'])
    if p.get('recipient'):
        r = p['recipient'].strip().lower()
        qs = qs.filter(Q(to__icontains=r) | Q(cc__icontains=r) | Q(bcc__icontains=r))
    runs = Execution.objects.filter(messages__isnull=True).exclude(status=Execution.Status.QUEUED).order_by('-created_at')[:20]
    page = max(1, int(p.get('page') or 1))
    total = qs.count()
    return Response({'total': total, 'page': page, 'pages': max(1, -(-total // 50)), 'messages': [_message_json(m) for m in qs[(page - 1) * 50: page * 50]],
                     # Runs that produced no email (nothing pending, no recipient, or could not be prepared).
                     'runs_without_email': [{'id': e.pk, 'automation': e.automation_name, 'status': e.get_status_display(), 'detail': e.detail,
                                             'created_at': e.created_at.isoformat()} for e in runs],
                     'queued_runs': Execution.objects.filter(status__in=[Execution.Status.QUEUED, Execution.Status.PROCESSING]).count(),
                     'worker': _worker()})


def _msg(pk: int) -> Message:
    m = Message.objects.select_related('execution').filter(pk=pk).first()
    if m is None:
        raise NotFound('No such email.')
    return m


@api_view(['GET'])
@permission_classes([IsAdminRole])
def history_detail(request, pk: int):
    return Response({'message': _message_json(_msg(pk), full=True)})


@api_view(['POST'])
@permission_classes([IsAdminRole])
def history_retry(request, pk: int):
    """Retry a failed email now (a new attempt on the same record; earlier attempts are kept)."""
    m = _msg(pk)
    if m.status != Message.Status.FAILED:
        raise ValidationError({'form': 'Only a failed email can be retried; use Resend for a sent one.'})
    m = engine.send_message(m, by=request.user)
    engine.finish(m.execution)
    audit('alert_retry', request, message=m.pk, ok=m.status == Message.Status.ACCEPTED)
    return Response({'message': _message_json(m, full=True)})


@api_view(['POST'])
@permission_classes([IsAdminRole])
def history_resend(request, pk: int):
    """Send an email again as a new record (the original stays as it was)."""
    m = _msg(pk)
    ex = Execution.objects.create(automation=m.execution.automation, automation_name=m.execution.automation_name, trigger='resend',
                                  requested_by=request.user, status=Execution.Status.PROCESSING, started_at=timezone.now())
    copy = Message.objects.create(execution=ex, resend_of=m, to=m.to, cc=m.cc, bcc=m.bcc, recipient_names=m.recipient_names, subject=m.subject,
                                  html=m.html, text=m.text, attachments=m.attachments, attachment_spec=m.attachment_spec)
    copy = engine.send_message(copy, by=request.user)
    engine.finish(ex)
    audit('alert_resend', request, message=m.pk, new=copy.pk, ok=copy.status == Message.Status.ACCEPTED)
    return Response({'message': _message_json(copy, full=True)}, status=status.HTTP_201_CREATED)
