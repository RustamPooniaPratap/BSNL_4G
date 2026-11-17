"""BSNL Module API (/api/bsnl/): Auto Email Reports and BSNL Letters. See apps/bsnl/README.md.

Every endpoint requires a signed-in portal user and checks the module permission on the server (permissions.py); data
is limited to the user's project/circle pairs. Downloads never send email; sending is a separate, confirmed action.
"""
from __future__ import annotations

import io
import zipfile
from datetime import date, timedelta

from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import JSONParser
from rest_framework.response import Response

from apps.accounts.access import can, pairs_for
from apps.accounts.audit import audit
from apps.accounts.permissions import IsPortalUser
from apps.organization.models import Circle
from apps.rca import taxonomy

from . import delivery, documents, letters, reports, scheduler
from .common import Period, d_long, d_short, fmt, report_period, whole_minutes
from .models import (Bucket, BsnlLetter, CircleLetterProfile, DistributionRecipient, LetterEvent, LetterStatus, RcaBucketMapping, ReportRun,
                     ReportType)
from .permissions import LETTERS, REPORTS, circle_projects, covers, letter_visible, require

MAX_PERIOD_DAYS = 92


class DataUnavailable(APIException):
    status_code = 503
    default_detail = 'Uptime data is unavailable.'


def _letter_event_note(letter: BsnlLetter, event: LetterEvent, total_minutes: int) -> str:
    if event.action in ('generated', 'regenerated') and 'hours' in event.note.lower():
        suffix = '; edits discarded' if event.note.endswith('; edits discarded') else ''
        return f'{letter.outage_count} outages, {fmt(total_minutes)} Outage Minutes{suffix}'
    return event.note


def _dataset(user, action: str = 'view'):
    from apps.dashboard.workbook import WorkbookError
    from apps.sitedata import dashboard_source
    try:
        return dashboard_source.dataset(pairs_for(user, REPORTS, action), reports.SCOPE)
    except WorkbookError as exc:
        raise DataUnavailable(f'Uptime data is unavailable: {exc}') from exc


def _projects() -> list[str]:
    from apps.organization.models import Project
    return list(Project.objects.filter(is_active=True).order_by('sort_order', 'key').values_list('key', flat=True))


def _project(value) -> str:
    value = str(value or '').strip()
    if value and value not in _projects():
        raise ValidationError({'project': 'Choose a site category (project) or All.'})
    return value


def _report_type(value) -> str:
    if value not in (ReportType.D1, ReportType.WEEKLY):
        raise ValidationError({'type': 'Choose the D-1 or Weekly report.'})
    return value


def _circle(code) -> Circle | None:
    code = str(code or '').strip()
    if not code:
        return None
    circle = Circle.objects.filter(code=code).first()
    if circle is None:
        raise ValidationError({'circle': 'Unknown circle.'})
    return circle


def _sees_circle(user, module: str, code: str) -> bool:
    """The user holds View on at least one project of the circle (the data shown is still limited to their pairs)."""
    pairs = pairs_for(user, module, 'view')
    return pairs is None or any(c == code for _, c in pairs)


def _report_error(exc: Exception):
    return Response({'error': str(exc)}, status=status.HTTP_409_CONFLICT)


# --- Auto Email Reports ----------------------------------------------------------------------------------------------

@api_view(['GET'])
@permission_classes([IsPortalUser])
def report_options(request):
    require(request.user, REPORTS, 'view', whole=False)
    return Response({
        'projects': _projects(),
        'schedule': {**scheduler.settings_value(), 'daily_time': '09:00 IST', 'weekly_time': 'Monday 10:00 IST'},
        'sending_enabled': delivery.sending_enabled(),
        'recipients_loaded': DistributionRecipient.objects.filter(is_active=True).count(),
        'permissions': {'send': can(request.user, REPORTS, 'send'), 'manage': can(request.user, REPORTS, 'manage'),
                        'all_india': covers(request.user, REPORTS, 'view', None)},
        'target_pct': reports.TARGET, 'population': 'On-Air sites',
    })


@api_view(['GET'])
@permission_classes([IsPortalUser])
def report_overview(request):
    require(request.user, REPORTS, 'view', whole=False)
    report_type, project = _report_type(request.query_params.get('type')), _project(request.query_params.get('project'))
    try:
        data = reports.circle_overview(_dataset(request.user), report_type, project)
    except reports.ReportError as exc:
        return _report_error(exc)
    for row in data['circles']:
        row['complete'] = covers(request.user, REPORTS, 'view', row['circle'], project)
        row['can_send'] = covers(request.user, REPORTS, 'send', row['circle'], project)
    return Response(data)


def _build(request, action: str = 'view') -> tuple[dict, Circle | None]:
    params = request.query_params if request.method == 'GET' else request.data
    report_type, project, circle = _report_type(params.get('type')), _project(params.get('project')), _circle(params.get('circle'))
    if circle is None or action != 'view':
        require(request.user, REPORTS, action, circle.code if circle else None, project)
    else:
        require(request.user, REPORTS, 'view', whole=False)
        if not _sees_circle(request.user, REPORTS, circle.code):
            raise NotFound('No such circle in your access.')
    pairs = pairs_for(request.user, REPORTS, 'view')
    try:
        report = reports.build(_dataset(request.user), report_type, {'code': circle.code, 'name': circle.name} if circle else None,
                               project=project, pairs=pairs, source='uptime data')
    except reports.ReportError as exc:
        raise _Conflict(str(exc)) from exc
    return report, circle


class _Conflict(APIException):
    status_code = 409


@api_view(['GET'])
@permission_classes([IsPortalUser])
def report_preview(request):
    report, _circle_obj = _build(request)
    return Response({key: report[key] for key in ('title', 'subject', 'html', 'to', 'cc', 'period', 'kpis', 'report_type', 'circle', 'project', 'data_status')}
                    | {'attachment': report['file'] + '.xlsx', 'sheet_count': len(report['sheets']),
                       'sheets': [s['name'] for s in report['sheets']]})


def _file(content: bytes, name: str, mime: str) -> HttpResponse:
    response = HttpResponse(content, content_type=mime)
    response['Content-Disposition'] = f'attachment; filename="{name}"'
    response['Cache-Control'] = 'no-store'
    return response


def _report_eml(report: dict) -> bytes:
    return documents.eml(to=report['to'], cc=report['cc'], subject=report['subject'], html=report['html'],
                         attachments=[(report['file'] + '.xlsx', documents.xlsx(report['sheets']), documents.XLSX)])


@api_view(['GET'])
@permission_classes([IsPortalUser])
def report_download(request):
    """``file=eml``: the ready-to-send draft with the Excel attached (nothing is sent); ``file=xlsx``: the attachment.
    (Not ``format``: DRF reserves that query parameter for content negotiation.)"""
    fmt = request.query_params.get('file')
    if fmt not in ('eml', 'xlsx'):
        raise ValidationError({'file': 'Choose eml or xlsx.'})
    report, _ = _build(request)
    audit('bsnl_report_downloaded', request, report=report['report_type'], circle=report['circle'] or 'All India', format=fmt)
    if fmt == 'xlsx':
        return _file(documents.xlsx(report['sheets']), report['file'] + '.xlsx', documents.XLSX)
    return _file(_report_eml(report), report['file'] + '.eml', documents.EML)


@api_view(['GET'])
@permission_classes([IsPortalUser])
def report_download_all(request):
    """One .eml per Circle the user fully covers, in a ZIP (the reference downloads them one by one)."""
    require(request.user, REPORTS, 'view', whole=False)
    report_type, project = _report_type(request.query_params.get('type')), _project(request.query_params.get('project'))
    ds = _dataset(request.user)
    pairs = pairs_for(request.user, REPORTS, 'view')
    buffer, count = io.BytesIO(), 0
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for circle in Circle.objects.filter(code__in=set(ds.sites['circle'])).order_by('name'):
            if not covers(request.user, REPORTS, 'view', circle.code, project):
                continue
            try:
                report = reports.build(ds, report_type, {'code': circle.code, 'name': circle.name}, project=project, pairs=pairs, source='uptime data')
            except reports.ReportError:
                continue
            archive.writestr(report['file'] + '.eml', _report_eml(report))
            count += 1
    if not count:
        return Response({'error': 'No circle report is available for your access.'}, status=status.HTTP_409_CONFLICT)
    audit('bsnl_report_downloaded', request, report=report_type, circle='all circles', format='zip', count=count)
    latest = reports.latest_date(ds)
    period = report_period(report_type, latest)
    return _file(buffer.getvalue(), f'{report_type.replace("-", "")}_Circle_emails_{period.start.isoformat()}.zip', 'application/zip')


@api_view(['POST'])
@parser_classes([JSONParser])
@permission_classes([IsPortalUser])
def report_send(request):
    """Send one report email now (confirmed in the UI). Disabled unless the server allows sending."""
    try:
        delivery.require_enabled()
    except delivery.SendingDisabled as exc:
        return Response({'error': str(exc)}, status=status.HTTP_409_CONFLICT)
    report, circle = _build(request, 'send')
    run = delivery.send_report(report, circle=circle, trigger='manual', user=request.user)
    audit('bsnl_report_sent', request, report=report['report_type'], circle=report['circle'] or 'All India', status=run.status)
    return Response({'run': _run_json(run)}, status=200 if run.status == ReportRun.Status.SENT else 502)


def _run_json(r: ReportRun) -> dict:
    return {'id': r.pk, 'report_type': r.report_type, 'circle': r.circle.code if r.circle_id else '', 'circle_name': r.circle.name if r.circle_id else 'All India',
            'project': r.project, 'period_start': r.period_start.isoformat() if hasattr(r.period_start, 'isoformat') else r.period_start,
            'period_end': r.period_end.isoformat() if hasattr(r.period_end, 'isoformat') else r.period_end, 'trigger': r.trigger,
            'status': r.status, 'to': r.to, 'cc': r.cc, 'subject': r.subject, 'attachment': r.attachment_name, 'error': r.error,
            'smtp_response': r.smtp_response, 'created_by': r.created_by.get_username() if r.created_by_id else 'scheduler',
            'created_at': r.created_at.isoformat(), 'finished_at': r.finished_at.isoformat() if r.finished_at else None}


@api_view(['GET'])
@permission_classes([IsPortalUser])
def report_runs(request):
    require(request.user, REPORTS, 'view', whole=False)
    runs = ReportRun.objects.select_related('circle', 'created_by')[:500]
    visible = [r for r in runs if covers(request.user, REPORTS, 'view', r.circle.code if r.circle_id else None, r.project)]
    return Response({'runs': [_run_json(r) for r in visible[:200]]})


class ScheduleSerializer(serializers.Serializer):
    daily = serializers.BooleanField()
    weekly = serializers.BooleanField()


@api_view(['GET', 'PUT'])
@parser_classes([JSONParser])
@permission_classes([IsPortalUser])
def report_schedule(request):
    if request.method == 'GET':
        require(request.user, REPORTS, 'view', whole=False)
        return Response({**scheduler.settings_value(), 'sending_enabled': delivery.sending_enabled()})
    require(request.user, REPORTS, 'manage', None)
    data = ScheduleSerializer(data=request.data)
    data.is_valid(raise_exception=True)
    from apps.common.models import Setting
    Setting.put(scheduler.SETTING, dict(data.validated_data), request.user)
    audit('bsnl_schedule_changed', request, **data.validated_data)
    return Response({**scheduler.settings_value(), 'sending_enabled': delivery.sending_enabled()})


# --- Distribution Master -------------------------------------------------------------------------------------------

class RecipientSerializer(serializers.Serializer):
    circle = serializers.CharField(allow_blank=True, required=False, max_length=20)
    report_type = serializers.ChoiceField(choices=ReportType.values)
    name = serializers.CharField(max_length=120)
    designation = serializers.CharField(max_length=120, allow_blank=True, required=False)
    email = serializers.EmailField(max_length=254)
    kind = serializers.ChoiceField(choices=DistributionRecipient.Kind.values)
    is_active = serializers.BooleanField(required=False, default=True)

    def validate(self, attrs):
        attrs['circle'] = _circle(attrs.get('circle'))
        attrs['email'] = attrs['email'].strip().lower()
        if attrs['report_type'] == ReportType.ALL_INDIA and attrs['circle'] is not None:
            raise serializers.ValidationError({'circle': 'All India recipients have no circle.'})
        if attrs['report_type'] != ReportType.ALL_INDIA and attrs['circle'] is None:
            raise serializers.ValidationError({'circle': 'Choose the circle.'})
        return attrs


def _recipient_json(r: DistributionRecipient) -> dict:
    return {'id': r.pk, 'circle': r.circle.code if r.circle_id else '', 'circle_name': r.circle.name if r.circle_id else 'All India',
            'report_type': r.report_type, 'name': r.name, 'designation': r.designation, 'email': r.email, 'kind': r.kind,
            'is_active': r.is_active, 'updated_at': r.updated_at.isoformat()}


def _recipient_module(report_type: str) -> str:
    return LETTERS if report_type == ReportType.LETTER else REPORTS


def _can_manage_recipients(user, report_type: str) -> bool:
    return can(user, _recipient_module(report_type), 'manage')


def _save_recipient(request, recipient: DistributionRecipient | None):
    data = RecipientSerializer(data=request.data)
    data.is_valid(raise_exception=True)
    v = data.validated_data
    if not _can_manage_recipients(request.user, v['report_type']) or (recipient and not _can_manage_recipients(request.user, recipient.report_type)):
        raise PermissionDenied('You do not have permission to edit these recipients.')
    require(request.user, _recipient_module(v['report_type']), 'manage', v['circle'].code if v['circle'] else None)
    recipient = recipient or DistributionRecipient(created_by=request.user)
    for field in ('circle', 'report_type', 'name', 'designation', 'email', 'kind', 'is_active'):
        setattr(recipient, field, v.get(field, '' if field == 'designation' else getattr(recipient, field)))
    recipient.updated_by = request.user
    try:
        with transaction.atomic():
            recipient.save()
    except IntegrityError:
        raise ValidationError({'email': 'This email is already a recipient of this report for this circle.'}) from None
    audit('bsnl_recipient_saved', request, recipient=recipient.pk, report=recipient.report_type,
          circle=recipient.circle.code if recipient.circle_id else 'All India', active=recipient.is_active)
    return Response({'recipient': _recipient_json(recipient)})


@api_view(['GET', 'POST'])
@parser_classes([JSONParser])
@permission_classes([IsPortalUser])
def recipients_list(request):
    if request.method == 'POST':
        return _save_recipient(request, None)
    if not (can(request.user, REPORTS, 'view') or can(request.user, LETTERS, 'view')):
        raise PermissionDenied('You do not have access to the BSNL Module.')
    qs = DistributionRecipient.objects.select_related('circle')
    if request.query_params.get('report_type'):
        qs = qs.filter(report_type=request.query_params['report_type'])
    rows = [r for r in qs if covers(request.user, _recipient_module(r.report_type), 'view', r.circle.code if r.circle_id else None)]
    return Response({'recipients': [_recipient_json(r) for r in rows],
                     'can_manage': {t: _can_manage_recipients(request.user, t) for t in ReportType.values}})


@api_view(['PUT'])
@parser_classes([JSONParser])
@permission_classes([IsPortalUser])
def recipient_detail(request, recipient_id: int):
    recipient = DistributionRecipient.objects.select_related('circle').filter(pk=recipient_id).first()
    if recipient is None:
        raise NotFound('No such recipient.')
    return _save_recipient(request, recipient)


# --- BSNL Letters --------------------------------------------------------------------------------------------------

def _letter_period(params) -> tuple[Period, str]:
    kind = params.get('period') or 'period'
    if kind in ('d1', 'week'):
        latest = letters.latest_rca_date()
        if latest is None:
            raise ValidationError({'period': 'No RCA records are available.'})
        from .common import d1_period, week_period
        return (d1_period(latest) if kind == 'd1' else week_period(latest)), kind
    if kind != 'period':
        raise ValidationError({'period': 'Choose D-1, Last week or Selected From–To.'})
    try:
        start, end = date.fromisoformat(params.get('date_from', '')), date.fromisoformat(params.get('date_to', ''))
    except ValueError:
        raise ValidationError({'date_from': 'Enter the From and To dates as YYYY-MM-DD.'}) from None
    if end < start:
        raise ValidationError({'date_to': 'The To date must not be before the From date.'})
    if (end - start).days + 1 > MAX_PERIOD_DAYS:
        raise ValidationError({'date_to': f'A letter covers at most {MAX_PERIOD_DAYS} days.'})
    if end > timezone.localdate():
        raise ValidationError({'date_to': 'The To date cannot be in the future.'})
    return Period(start, end), kind


def _letter_json(letter: BsnlLetter, user=None, *, full: bool = False) -> dict:
    total_minutes = (letters.summary(letter.annexure)['outage_minutes'] if letter.annexure
                     else whole_minutes(float(letter.total_hours) * 60))
    data = {'id': letter.pk, 'reference': letter.reference, 'circle': letter.circle.code, 'circle_name': letter.circle.name,
            'project': letter.project, 'period_kind': letter.period_kind, 'period_start': letter.period_start.isoformat(),
            'period_end': letter.period_end.isoformat(), 'period_label': f'{d_short(letter.period_start)} – {d_long(letter.period_end)}',
            'outage_count': letter.outage_count, 'site_count': letter.site_count, 'total_minutes': total_minutes,
            'total_hours': float(letter.total_hours),
            'status': letter.status, 'prepared_by': letter.prepared_by.get_username() if letter.prepared_by_id else '',
            'created_at': letter.created_at.isoformat(), 'updated_at': letter.updated_at.isoformat(),
            'approved_by': letter.approved_by.get_username() if letter.approved_by_id else '',
            'approved_at': letter.approved_at.isoformat() if letter.approved_at else None,
            'sent_at': letter.sent_at.isoformat() if letter.sent_at else None, 'send_status': letter.send_status,
            'send_error': letter.send_error, 'edited': bool(letter.edited_html), 'recipients': letter.recipients}
    if full:
        code, project = letter.circle.code, letter.project
        data |= {'html': letters.display_html(letter), 'generated_html': letters.display_generated_html(letter),
                 'annexure': [{**row, 'outage_minutes': whole_minutes(letters.row_minutes(row))} for row in letter.annexure],
                 'causes': [{**cause, 'outage_minutes': whole_minutes(
                     cause.get('outage_minutes', float(cause.get('hours') or 0) * 60))} for cause in letter.causes],
                 'letter_date': letter.letter_date.isoformat(), 'subject': letters.subject(letter),
                 'events': [{'action': e.action, 'status_before': e.status_before, 'status_after': e.status_after,
                             'note': _letter_event_note(letter, e, total_minutes),
                             'actor': e.actor_name, 'created_at': e.created_at.isoformat()} for e in letter.events.all()],
                 'current_recipients': reports.recipients(code, ReportType.LETTER),
                 'permissions': {a: covers(user, LETTERS, a, code, project) for a in ('edit', 'approve', 'send')},
                 'transitions': sorted(letters.TRANSITIONS.get(letter.status, set())),
                 'sending_enabled': delivery.sending_enabled()}
    return data


@api_view(['GET'])
@permission_classes([IsPortalUser])
def letter_options(request):
    require(request.user, LETTERS, 'view', whole=False)
    latest = letters.latest_rca_date()
    return Response({'projects': _projects(), 'latest_rca_date': latest.isoformat() if latest else None,
                     'permissions': {a: can(request.user, LETTERS, a) for a in ('edit', 'approve', 'send', 'manage')},
                     'statuses': LetterStatus.values, 'max_period_days': MAX_PERIOD_DAYS})


@api_view(['GET'])
@permission_classes([IsPortalUser])
def letter_overview(request):
    """Customer (BSNL)-bucket outages by Circle for the period (reference pageLetter list) and the letter register."""
    require(request.user, LETTERS, 'view', whole=False)
    period, kind = _letter_period(request.query_params)
    project = _project(request.query_params.get('project'))
    pairs = pairs_for(request.user, LETTERS, 'view')
    from apps.organization.models import ProjectCircle
    codes = sorted({c for p, c in ProjectCircle.objects.filter(is_active=True, circle__is_active=True).values_list('project__key', 'circle__code')
                    if (not project or p == project) and (pairs is None or (p, c) in pairs)})
    names = dict(Circle.objects.filter(code__in=codes).values_list('code', 'name'))
    rows = []
    for code in sorted(codes, key=lambda c: names.get(c, c)):
        outs = letters.cust_outages(code, period, project=project, pairs=pairs)
        s = letters.summary(outs)
        existing = BsnlLetter.objects.filter(circle__code=code, project=project, period_start=period.start, period_end=period.end).first()
        rows.append({'circle': code, 'name': names.get(code, code), **s, **reports.recipients(code, ReportType.LETTER),
                     'complete': covers(request.user, LETTERS, 'view', code, project),
                     'letter': {'id': existing.pk, 'reference': existing.reference, 'status': existing.status} if existing else None})
    register = [_letter_json(lt) for lt in BsnlLetter.objects.select_related('circle', 'prepared_by', 'approved_by')[:500]
                if covers(request.user, LETTERS, 'view', lt.circle.code, lt.project)][:200]
    return Response({'period': {'kind': kind, 'start': period.start.isoformat(), 'end': period.end.isoformat(),
                                'label': f'{d_short(period.start)} – {d_long(period.end)}'},
                     'circles': rows, 'register': register})


@api_view(['POST'])
@parser_classes([JSONParser])
@permission_classes([IsPortalUser])
def letter_open(request):
    """The Circle's letter for the period: the existing one, or a new Draft (needs Edit) generated from the RCA records."""
    circle = _circle(request.data.get('circle'))
    if circle is None:
        raise ValidationError({'circle': 'Choose the circle.'})
    project = _project(request.data.get('project'))
    period, kind = _letter_period(request.data)
    require(request.user, LETTERS, 'view', circle.code, project)
    existing = BsnlLetter.objects.filter(circle=circle, project=project, period_start=period.start, period_end=period.end).first()
    if existing is None:
        require(request.user, LETTERS, 'edit', circle.code, project)
    try:
        letter, created = letters.open_letter(circle, period, kind, project=project, user=request.user, pairs=None)
    except letters.LetterError as exc:
        return Response({'error': str(exc)}, status=exc.status_code)
    if created:
        audit('bsnl_letter_created', request, reference=letter.reference)
    return Response({'letter': _letter_json(letter, request.user, full=True), 'created': created},
                    status=status.HTTP_201_CREATED if created else 200)


def _letter(request, letter_id: int) -> BsnlLetter:
    letter = BsnlLetter.objects.select_related('circle', 'prepared_by', 'approved_by').filter(pk=letter_id).first()
    if letter is None:
        raise NotFound('No such letter.')
    letter_visible(request.user, letter)
    return letter


@api_view(['GET'])
@permission_classes([IsPortalUser])
def letter_detail(request, letter_id: int):
    require(request.user, LETTERS, 'view', whole=False)
    return Response({'letter': _letter_json(_letter(request, letter_id), request.user, full=True)})


def _letter_action(request, letter_id: int, action: str, fn):
    letter = _letter(request, letter_id)
    require(request.user, LETTERS, action, letter.circle.code, letter.project)
    try:
        letter = fn(letter)
    except letters.LetterError as exc:
        return Response({'error': str(exc)}, status=exc.status_code)
    except delivery.SendingDisabled as exc:
        return Response({'error': str(exc)}, status=status.HTTP_409_CONFLICT)
    letter = BsnlLetter.objects.select_related('circle', 'prepared_by', 'approved_by').get(pk=letter.pk)
    return Response({'letter': _letter_json(letter, request.user, full=True)})


@api_view(['PUT'])
@parser_classes([JSONParser])
@permission_classes([IsPortalUser])
def letter_content(request, letter_id: int):
    html = request.data.get('html')
    if not isinstance(html, str):
        raise ValidationError({'html': 'Send the letter content.'})
    return _letter_action(request, letter_id, 'edit', lambda lt: letters.save_edit(lt, html, request.user))


@api_view(['POST'])
@permission_classes([IsPortalUser])
def letter_regenerate(request, letter_id: int):
    return _letter_action(request, letter_id, 'edit', lambda lt: letters.regenerate(lt, request.user, None))


@api_view(['POST'])
@permission_classes([IsPortalUser])
def letter_approve(request, letter_id: int):
    def approve(lt):
        result = letters.transition(lt, LetterStatus.APPROVED, request.user)
        audit('bsnl_letter_approved', request, reference=lt.reference)
        return result
    return _letter_action(request, letter_id, 'approve', approve)


class StatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=[LetterStatus.DRAFT, LetterStatus.SENT, LetterStatus.ACKNOWLEDGED,
                                              LetterStatus.ACCEPTED, LetterStatus.REJECTED])
    note = serializers.CharField(max_length=2000, allow_blank=True, required=False, default='')

    def validate(self, attrs):
        if attrs['status'] == LetterStatus.SENT and not attrs['note'].strip():
            raise serializers.ValidationError({'note': 'Say how the letter was sent outside the portal.'})
        return attrs


@api_view(['POST'])
@parser_classes([JSONParser])
@permission_classes([IsPortalUser])
def letter_status(request, letter_id: int):
    """Record a later status: back to Draft, sent outside the portal, acknowledged, exclusion accepted / rejected."""
    data = StatusSerializer(data=request.data)
    data.is_valid(raise_exception=True)
    v = data.validated_data

    def change(lt):
        result = letters.transition(lt, v['status'], request.user, note=v['note'].strip())
        audit('bsnl_letter_status', request, reference=lt.reference, status=v['status'])
        return result
    return _letter_action(request, letter_id, 'approve', change)


@api_view(['POST'])
@permission_classes([IsPortalUser])
def letter_send(request, letter_id: int):
    def send(lt):
        result = delivery.send_letter(lt, request.user)
        audit('bsnl_letter_sent', request, reference=lt.reference, status=result.send_status)
        return result
    return _letter_action(request, letter_id, 'send', send)


@api_view(['GET'])
@permission_classes([IsPortalUser])
def letter_download(request, letter_id: int, fmt: str):
    """doc (Word), xlsx (annexure), eml (Approved letters only; nothing is sent) or html (for Print / Save as PDF)."""
    require(request.user, LETTERS, 'view', whole=False)
    letter = _letter(request, letter_id)
    name = documents.safe_name(letter.reference)
    if fmt == 'doc':
        return _file(letters.doc_html(letter).encode('utf-8'), f'{name}.doc', documents.DOC)
    if fmt == 'xlsx':
        return _file(letters.annexure_xlsx(letter.annexure), f'Annexure_{name}.xlsx', documents.XLSX)
    if fmt == 'html':
        response = HttpResponse(letters.doc_html(letter), content_type='text/html; charset=utf-8')
        response['Content-Security-Policy'] = "default-src 'none'; style-src 'unsafe-inline'"
        return response
    if fmt == 'eml':
        if letter.status == LetterStatus.DRAFT:
            return Response({'error': 'Approve the letter before downloading its email.'}, status=status.HTTP_409_CONFLICT)
        return _file(letters.eml(letter), f'{name}.eml', documents.EML)
    raise NotFound('Unknown format.')


@api_view(['GET'])
@permission_classes([IsPortalUser])
def letter_register_xlsx(request):
    require(request.user, LETTERS, 'view', whole=False)
    rows = [['Ref', 'Circle', 'Period', 'Outages', 'Outage Minutes', 'Prepared', 'Prepared by', 'Status', 'Approved by', 'Sent']]
    for lt in BsnlLetter.objects.select_related('circle', 'prepared_by', 'approved_by'):
        if covers(request.user, LETTERS, 'view', lt.circle.code, lt.project):
            rows.append([lt.reference, lt.circle.name, f'{d_short(lt.period_start)} – {d_short(lt.period_end)}', lt.outage_count,
                         (letters.summary(lt.annexure)['outage_minutes'] if lt.annexure
                          else whole_minutes(float(lt.total_hours) * 60)),
                         timezone.localtime(lt.created_at).strftime('%d %b %Y %H:%M'),
                         lt.prepared_by.get_username() if lt.prepared_by_id else '', lt.status,
                         lt.approved_by.get_username() if lt.approved_by_id else '',
                         timezone.localtime(lt.sent_at).strftime('%d %b %Y %H:%M') if lt.sent_at else ''])
    return _file(documents.xlsx([{'name': 'Register', 'rows': rows}]), 'BSNL_letter_register.xlsx', documents.XLSX)


# --- Letter masters: circle profiles and bucket mapping ----------------------------------------------------------------

class ProfileSerializer(serializers.Serializer):
    bsnl_designation = serializers.CharField(max_length=200, allow_blank=True)
    bsnl_address = serializers.CharField(max_length=2000, allow_blank=True)
    sender_name = serializers.CharField(max_length=120, allow_blank=True)
    sender_designation = serializers.CharField(max_length=200, allow_blank=True)
    company = serializers.CharField(max_length=200, allow_blank=True)


@api_view(['GET'])
@permission_classes([IsPortalUser])
def profiles(request):
    require(request.user, LETTERS, 'view', whole=False)
    found = {p.circle_id: p for p in CircleLetterProfile.objects.all()}
    out = []
    for c in Circle.objects.filter(is_active=True).order_by('name'):
        if not _sees_circle(request.user, LETTERS, c.code):
            continue
        p = found.get(c.pk)
        out.append({'circle': c.code, 'name': c.name, **{f: getattr(p, f) if p else '' for f in ProfileSerializer().fields}})
    return Response({'profiles': out, 'can_manage': can(request.user, LETTERS, 'manage')})


@api_view(['PUT'])
@parser_classes([JSONParser])
@permission_classes([IsPortalUser])
def profile_detail(request, circle_code: str):
    circle = _circle(circle_code)
    if circle is None:
        raise NotFound('No such circle.')
    require(request.user, LETTERS, 'manage', circle.code)
    data = ProfileSerializer(data=request.data)
    data.is_valid(raise_exception=True)
    profile, _ = CircleLetterProfile.objects.get_or_create(circle=circle)
    for field, value in data.validated_data.items():
        setattr(profile, field, value.strip())
    profile.updated_by = request.user
    profile.save()
    audit('bsnl_letter_profile_saved', request, circle=circle.code)
    return Response({'profile': {'circle': circle.code, 'name': circle.name, **{f: getattr(profile, f) for f in data.validated_data}}})


@api_view(['GET', 'PUT'])
@parser_classes([JSONParser])
@permission_classes([IsPortalUser])
def bucket_mapping(request):
    """The approved Final Buckets and their current responsibility classification."""
    if request.method == 'PUT':
        require(request.user, LETTERS, 'manage', None)
        items = request.data.get('mapping')
        if not isinstance(items, list):
            raise ValidationError({'mapping': 'Send the mapping rows.'})
        from .classification import normalize_responsibility_bucket
        normalized_items = []
        seen = set()
        for item in items:
            if not isinstance(item, dict):
                raise ValidationError({'mapping': 'Each row must contain an approved Final Bucket and a responsibility bucket.'})
            final = taxonomy.approved_final(item.get('final_bucket'))
            bucket = normalize_responsibility_bucket(item.get('bucket'))
            if final is None or bucket is None:
                raise ValidationError({'mapping': 'Each row needs an approved Final Bucket and a valid responsibility bucket.'})
            key = taxonomy.match_key(final)
            if key in seen:
                raise ValidationError({'mapping': f'Duplicate Final Bucket mapping: {final}.'})
            seen.add(key)
            normalized_items.append({'final_bucket': final, 'bucket': bucket})
        with transaction.atomic():
            for item in normalized_items:
                RcaBucketMapping.objects.update_or_create(final_bucket=item['final_bucket'],
                                                          defaults={'bucket': item['bucket'], 'updated_by': request.user})
        audit('bsnl_bucket_mapping_saved', request, rows=len(normalized_items))
    else:
        if not (can(request.user, LETTERS, 'view') or can(request.user, REPORTS, 'view')):
            raise PermissionDenied('You do not have access to the BSNL Module.')
    from .classification import mapping_for_approved_finals
    from .common import bucket_map
    return Response({'mapping': [{'final_bucket': f, 'bucket': b} for f, b in mapping_for_approved_finals(bucket_map()).items()],
                     'buckets': list(Bucket.values), 'can_manage': can(request.user, LETTERS, 'manage'),
                     'rule': 'Blank, unapproved, or unmapped Final Buckets are Unclassified.'})
