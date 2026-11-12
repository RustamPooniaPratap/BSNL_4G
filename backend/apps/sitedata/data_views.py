"""Data administration API of the data layer (Admins only), mounted at /api/sitedata/:

- daily/correct/: authorized correction of one site-day (precedence 3, never overridden by an upload). A site-day with
  a record is corrected (daily.correct); one without a record gets one (daily.add_correction). A reason is required;
  every correction is an upload of kind "correction" plus a DailyPerformanceEvent with the old and new value.
- daily/history/: the stored value of a site-day and its event trail (conflicts, superseded values, corrections).
- lwe-mapping/: the LWE Band ID mapping import (preview, review, confirm, discard, rejected-row report), as the
  Consolidation Matrix import.
- months/: monthly results per month and their finalization; finalize/ protects a month from uploads.
"""
from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.accounts.audit import audit
from apps.accounts.permissions import IsAdminRole

from . import bandmap, calculations, daily, uploads
from .identifiers import key_of
from .matrix_views import MAX_BYTES, _batch_json, _get
from .models import (CoverageThreshold, DailyPerformanceEvent, DailySitePerformance, MonthFinalization, MonthlySitePerformance, ReportingUnit,
                     ReportingUnitChange, Site, Technology, UploadBatch)


def _date(value, field: str) -> date:
    try:
        return date.fromisoformat(str(value or '')[:10])
    except ValueError as exc:
        raise ValidationError({field: 'Give the date as YYYY-MM-DD.'}) from exc


def _site(value) -> Site:
    site = Site.objects.filter(site_key=key_of(value)).first()
    if site is None:
        raise ValidationError({'site': f'{value} is not a site of the site master.'})
    return site


def _record_json(rec: DailySitePerformance | None) -> dict | None:
    if rec is None:
        return None
    return {'id': rec.pk, 'site': rec.site.bsnl_site_id, 'technology': rec.technology, 'circle': rec.circle,
            'report_date': rec.report_date.isoformat(), 'availability_pct': rec.availability_pct, 'outage_minutes': rec.outage_minutes,
            'revision': rec.revision, 'source': rec.batch.get_kind_display(), 'source_file': rec.batch.original_filename, 'batch': rec.batch_id}


@api_view(['POST'])
@parser_classes([JSONParser])
@permission_classes([IsAdminRole])
def daily_correct(request):
    data = request.data
    site = _site(data.get('site'))
    day = _date(data.get('report_date'), 'report_date')
    try:
        availability = float(data.get('availability_pct'))
    except (TypeError, ValueError) as exc:
        raise ValidationError({'availability_pct': 'Give the availability as a percentage (0-100).'}) from exc
    if not 0 <= availability <= 100:
        raise ValidationError({'availability_pct': 'Availability must be between 0 and 100.'})
    reason = str(data.get('reason') or '').strip()
    if not reason:
        raise ValidationError({'reason': 'A correction needs a reason.'})
    force = data.get('force') is True
    record = DailySitePerformance.objects.filter(site=site, report_date=day, technology=site.technology).first()
    try:
        if record is None:
            record = daily.add_correction(site, day, availability, user=request.user, reason=reason, request=request, force=force)
        else:
            record = daily.correct(record, availability, user=request.user, reason=reason, request=request, force=force)
    except (ValueError, daily.FinalizedPeriod) as exc:
        return Response({'error': str(exc), 'details': {}}, status=status.HTTP_409_CONFLICT)
    except DjangoPermissionDenied as exc:
        return Response({'error': str(exc), 'details': {}}, status=status.HTTP_403_FORBIDDEN)
    record = DailySitePerformance.objects.select_related('site', 'batch').get(pk=record.pk)
    return Response({'record': _record_json(record)})


@api_view(['GET'])
@permission_classes([IsAdminRole])
def daily_history(request):
    site = _site(request.query_params.get('site'))
    day = _date(request.query_params.get('date'), 'date')
    record = DailySitePerformance.objects.select_related('site', 'batch').filter(site=site, report_date=day).first()
    events = DailyPerformanceEvent.objects.filter(site=site, report_date=day).select_related('batch', 'stored_batch', 'user')
    return Response({'record': _record_json(record), 'events': [{
        'action': e.action, 'action_label': e.get_action_display(), 'at': e.created_at.isoformat(),
        'proposed_availability_pct': e.proposed_availability_pct, 'stored_availability_pct': e.stored_availability_pct,
        'upload': e.batch_id, 'upload_kind': e.batch.get_kind_display(), 'upload_file': e.batch.original_filename,
        'stored_upload': e.stored_batch_id, 'user': e.user.get_username() if e.user else None, 'reason': e.reason} for e in events]})


# --- LWE Band ID mapping --------------------------------------------------------------------------

def _mapping(batch_id: int) -> UploadBatch:
    return _get(batch_id, kind=bandmap.KIND, label='LWE Band ID mapping')


@api_view(['GET'])
@permission_classes([IsAdminRole])
def mapping_list(request):
    batches = UploadBatch.objects.filter(kind=bandmap.KIND).select_related('uploaded_by').order_by('-uploaded_at')[:20]
    return Response({'imports': [{k: v for k, v in _batch_json(b).items() if k != 'report'} for b in batches]})


@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser])
@permission_classes([IsAdminRole])
def mapping_preview(request):
    upload = request.FILES.get('file')
    if upload is None:
        raise ValidationError({'file': 'Choose the LWE Band ID mapping workbook (.xlsx).'})
    if not upload.name.lower().endswith('.xlsx'):
        raise ValidationError({'file': 'The LWE Band ID mapping must be an Excel workbook (.xlsx).'})
    if upload.size > MAX_BYTES:
        raise ValidationError({'file': f'The file is larger than {MAX_BYTES // (1024 * 1024)} MB.'})
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / Path(upload.name).name
        with open(path, 'wb') as handle:
            for chunk in upload.chunks():
                handle.write(chunk)
        batch = bandmap.preview(path, Path(upload.name).name, user=request.user)
    audit('sitedata.band_mapping_previewed', request, batch=batch.pk, file=batch.original_filename, status=batch.validation_status)
    body = _batch_json(batch)
    code = status.HTTP_400_BAD_REQUEST if batch.validation_status == UploadBatch.Validation.FAILED else status.HTTP_201_CREATED
    return Response({**body, 'details': {}} if code == status.HTTP_400_BAD_REQUEST else body, status=code)


@api_view(['GET'])
@permission_classes([IsAdminRole])
def mapping_detail(request, batch_id: int):
    return Response(_batch_json(_mapping(batch_id)))


@api_view(['POST'])
@parser_classes([JSONParser])
@permission_classes([IsAdminRole])
def mapping_commit(request, batch_id: int):
    batch = _mapping(batch_id)
    if request.data.get('confirm') is not True:
        raise ValidationError({'confirm': 'Confirm the import after reviewing the preview.'})
    try:
        batch = bandmap.commit(batch, user=request.user, request=request)
    except uploads.UploadRejected as exc:
        return Response({'error': str(exc), 'details': {}}, status=status.HTTP_409_CONFLICT)
    return Response(_batch_json(batch))


@api_view(['POST'])
@permission_classes([IsAdminRole])
def mapping_discard(request, batch_id: int):
    try:
        batch = uploads.discard(_mapping(batch_id))
    except uploads.UploadRejected as exc:
        return Response({'error': str(exc), 'details': {}}, status=status.HTTP_409_CONFLICT)
    audit('sitedata.band_mapping_discarded', request, batch=batch.pk)
    return Response(_batch_json(batch))


@api_view(['GET'])
@permission_classes([IsAdminRole])
def mapping_issues_csv(request, batch_id: int):
    return _issues(batch_id)


def _issues(batch_id: int):
    import csv
    import io

    from django.http import HttpResponse

    from . import exceptions
    batch = _mapping(batch_id)
    path = (batch.report or {}).get('exception_report')
    from . import exceptions as exception_files
    resolved = exception_files.resolve(path) if path else None
    if resolved is not None and resolved.is_file():
        data = resolved.read_bytes()
    else:
        out = io.StringIO()
        csv.writer(out).writerow(exceptions.COLUMNS)
        data = out.getvalue().encode('utf-8')
    response = HttpResponse(data, content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="lwe-mapping-{batch.pk}-issues.csv"'
    return response


# --- Monthly results and finalization (approved rule B-7) -------------------------------------------

def _month_end(month: date) -> date:
    import calendar
    return month.replace(day=calendar.monthrange(month.year, month.month)[1])


def month_completeness(month: date) -> dict:
    """Complete / Incomplete status of a month from the reporting units and coverage of each of its calendar days (days
    after today count as not yet received). Missing unit-days are listed for follow-up and traceability."""
    from datetime import timedelta

    from django.utils import timezone

    from . import reporting
    end = _month_end(month)
    days = [month + timedelta(days=i) for i in range((end - month).days + 1)]
    cov = reporting.coverage(days)
    today = timezone.localdate()
    missing: dict = {}
    for day in days:
        for (technology, circle), entry in cov.get(day, {}).items():
            if day > today or not entry['covered']:
                missing.setdefault((technology, circle), []).append(day.isoformat())
    return {'status': MonthFinalization.Status.INCOMPLETE if missing else MonthFinalization.Status.COMPLETE,
            'missing': [{'technology': t, 'circle': c, 'dates': d} for (t, c), d in sorted(missing.items())],
            'coverage': {'days': len(days), 'thresholds': sorted({e['threshold'] for units in cov.values() for e in units.values()}),
                         'unit_days': sum(len(u) for u in cov.values()),
                         'covered_unit_days': sum(1 for u in cov.values() for e in u.values() if e['covered'])}}


def _finalization_json(f: MonthFinalization | None) -> dict | None:
    if f is None:
        return None
    return {'revision': f.revision, 'status': f.status, 'status_label': f.get_status_display(), 'missing': f.missing,
            'finalized_at': f.finalized_at.isoformat(), 'finalized_by': f.finalized_by.get_username() if f.finalized_by else None,
            'reopened_at': f.reopened_at.isoformat() if f.reopened_at else None,
            'reopened_by': f.reopened_by.get_username() if f.reopened_by else None, 'reopen_reason': f.reopen_reason or None}


@api_view(['GET'])
@permission_classes([IsAdminRole])
def months(request):
    from django.db.models import Count, Max, Q
    rows = (MonthlySitePerformance.objects.filter(is_current=True).values('month')
            .annotate(records=Count('id'), finalized=Count('id', filter=Q(finalized_at__isnull=False)), calculated_at=Max('calculated_at'))
            .order_by('-month'))
    latest = {}
    for f in MonthFinalization.objects.select_related('finalized_by', 'reopened_by').order_by('month', 'revision'):
        latest[f.month] = f
    out = []
    for r in rows:
        f = latest.get(r['month'])
        open_final = f if f and f.reopened_at is None else None
        status_code = open_final.status if open_final else ('reopened' if f else 'open')
        label = open_final.get_status_display() if open_final else ('Reopened' if f else 'Not finalized')
        out.append({'month': r['month'].isoformat(), 'records': r['records'], 'finalized': r['finalized'] == r['records'] and r['records'] > 0,
                    'calculated_at': r['calculated_at'].isoformat() if r['calculated_at'] else None,
                    'finalization_status': status_code, 'finalization_label': label, 'finalization': _finalization_json(f)})
    return Response({'months': out})


@api_view(['POST'])
@parser_classes([JSONParser])
@permission_classes([IsAdminRole])
def months_finalize(request):
    """Finalize a month, also with missing data (then "Incomplete - Missing Data", the missing unit-days kept). Runs under
    the data-layer write lock so no import lands between the recalculation and the finalization."""
    from django.db import transaction
    month = _date(request.data.get('month'), 'month').replace(day=1)
    if request.data.get('confirm') is not True:
        raise ValidationError({'confirm': 'Confirm the finalization explicitly.'})
    notes = str(request.data.get('notes') or '').strip()
    with transaction.atomic():
        uploads.write_lock()
        if MonthFinalization.objects.filter(month=month, reopened_at__isnull=True).exists():
            return Response({'error': f'{month:%b %Y} is already finalized; reopen it first.', 'details': {}}, status=status.HTTP_409_CONFLICT)
        try:
            calculations.calculate_month(month, request=request)
        except calculations.MonthFinalized as exc:
            return Response({'error': str(exc), 'details': {}}, status=status.HTTP_409_CONFLICT)
        state = month_completeness(month)
        n = calculations.finalize_month(month, user=request.user, request=request)
        revision = (MonthFinalization.objects.filter(month=month).order_by('-revision').values_list('revision', flat=True).first() or 0) + 1
        final = MonthFinalization.objects.create(month=month, revision=revision, status=state['status'], missing=state['missing'],
                                                 coverage=state['coverage'], finalized_by=request.user, notes=notes)
    audit('sitedata.month_finalized_status', request, month=month, status=final.status, revision=revision, missing_units=len(state['missing']))
    return Response({'month': month.isoformat(), 'finalized_records': n, 'finalization': _finalization_json(final)})


@api_view(['POST'])
@parser_classes([JSONParser])
@permission_classes([IsAdminRole])
def months_reopen(request):
    """Reopen a finalized month so late data can be imported (controlled and audited): the monthly results are no longer
    finalized and the finalization record keeps who reopened it, when and why. Finalize again afterwards (new revision)."""
    from django.db import transaction
    from django.utils import timezone
    month = _date(request.data.get('month'), 'month').replace(day=1)
    reason = str(request.data.get('reason') or '').strip()
    if not reason:
        raise ValidationError({'reason': 'Give the reason for reopening the month.'})
    with transaction.atomic():
        uploads.write_lock()
        final = MonthFinalization.objects.select_for_update().filter(month=month, reopened_at__isnull=True).first()
        if final is None:
            return Response({'error': f'{month:%b %Y} is not finalized.', 'details': {}}, status=status.HTTP_409_CONFLICT)
        MonthlySitePerformance.objects.filter(month=month, is_current=True).update(finalized_at=None, finalized_by=None)
        final.reopened_at, final.reopened_by, final.reopen_reason = timezone.now(), request.user, reason
        final.save(update_fields=['reopened_at', 'reopened_by', 'reopen_reason'])
    audit('sitedata.month_reopened', request, month=month, revision=final.revision, reason=reason)
    return Response({'month': month.isoformat(), 'finalization': _finalization_json(final)})


# --- Reporting units (approved rules B-1 / B-2) -------------------------------------------------------

def _unit_json(u: ReportingUnit) -> dict:
    return {'id': u.pk, 'technology': u.technology, 'circle': u.circle, 'active_from': u.active_from.isoformat(),
            'active_until': u.active_until.isoformat() if u.active_until else None, 'notes': u.notes,
            'changes': [{'action': c.action, 'before': c.before, 'after': c.after, 'reason': c.reason,
                         'user': c.user.get_username() if c.user else None, 'at': c.created_at.isoformat()}
                        for c in u.changes.select_related('user').all()[:20]]}


def _unit_state(u: ReportingUnit) -> dict:
    return {'technology': u.technology, 'circle': u.circle, 'active_from': u.active_from.isoformat(),
            'active_until': u.active_until.isoformat() if u.active_until else None, 'notes': u.notes}


def _optional_date(value, field):
    return None if value in (None, '') else _date(value, field)


@api_view(['GET', 'POST'])
@parser_classes([JSONParser])
@permission_classes([IsAdminRole])
def reporting_units(request):
    """GET: every reporting unit (circle + technology) with its effective dates and recent changes. POST: add a unit
    ({technology, circle, active_from, reason}); the project/circle must be set up in the Organization."""
    from django.db import transaction

    from apps.organization import services as organization
    if request.method == 'GET':
        return Response({'units': [_unit_json(u) for u in ReportingUnit.objects.all()]})
    data = request.data
    technology, circle = str(data.get('technology') or ''), str(data.get('circle') or '').strip().upper()
    reason = str(data.get('reason') or '').strip()
    errors = {}
    if technology not in Technology.values:
        errors['technology'] = f'Choose one of {", ".join(Technology.values)}.'
    if not circle:
        errors['circle'] = 'Choose a circle.'
    if not reason:
        errors['reason'] = 'Give the reason for the change.'
    active_from = _date(data.get('active_from'), 'active_from') if data.get('active_from') else None
    if active_from is None:
        errors['active_from'] = 'Give the activation date (first expected reporting date).'
    if errors:
        raise ValidationError(errors)
    check = organization.check_pairs([(technology, circle)])
    if check['blocking']:
        raise ValidationError({'circle': organization.blocking_message(check)})
    if ReportingUnit.objects.filter(technology=technology, circle=circle).exists():
        return Response({'error': f'{technology} {circle} already exists; correct or reactivate it instead.', 'details': {}}, status=status.HTTP_409_CONFLICT)
    with transaction.atomic():
        unit = ReportingUnit.objects.create(technology=technology, circle=circle, active_from=active_from, notes=str(data.get('notes') or ''))
        ReportingUnitChange.objects.create(unit=unit, action=ReportingUnitChange.Action.CREATED, before={}, after=_unit_state(unit), reason=reason, user=request.user)
    _after_configuration_change()
    audit('sitedata.reporting_unit_created', request, unit=str(unit), active_from=active_from, reason=reason)
    return Response({'unit': _unit_json(unit)}, status=status.HTTP_201_CREATED)


@api_view(['PATCH'])
@parser_classes([JSONParser])
@permission_classes([IsAdminRole])
def reporting_unit(request, unit_id: int):
    """Correct ({active_from?, notes?}), deactivate ({active_until}) or reactivate ({active_until: null}) a unit, with a
    reason. Every change is kept (ReportingUnitChange); finalized months keep their finalization snapshot."""
    from django.db import transaction
    data = request.data
    reason = str(data.get('reason') or '').strip()
    if not reason:
        raise ValidationError({'reason': 'Give the reason for the change.'})
    with transaction.atomic():
        unit = ReportingUnit.objects.select_for_update().filter(pk=unit_id).first()
        if unit is None:
            return Response({'error': 'No such reporting unit.', 'details': {}}, status=status.HTTP_404_NOT_FOUND)
        before = _unit_state(unit)
        if 'active_from' in data:
            unit.active_from = _date(data.get('active_from'), 'active_from')
        if 'active_until' in data:
            unit.active_until = _optional_date(data.get('active_until'), 'active_until')
        if 'notes' in data:
            unit.notes = str(data.get('notes') or '')
        if unit.active_until is not None and unit.active_until < unit.active_from:
            raise ValidationError({'active_until': 'The deactivation date cannot be before the activation date.'})
        after = _unit_state(unit)
        if after == before:
            return Response({'unit': _unit_json(unit)})
        action = (ReportingUnitChange.Action.DEACTIVATED if before['active_until'] is None and after['active_until'] is not None else
                  ReportingUnitChange.Action.REACTIVATED if before['active_until'] is not None and after['active_until'] is None else
                  ReportingUnitChange.Action.CORRECTED)
        unit.save()
        ReportingUnitChange.objects.create(unit=unit, action=action, before=before, after=after, reason=reason, user=request.user)
    _after_configuration_change()
    audit('sitedata.reporting_unit_changed', request, unit=str(unit), action=action, before=before, after=after, reason=reason)
    return Response({'unit': _unit_json(unit)})


# --- Coverage threshold (approved rule B-6) -----------------------------------------------------------

@api_view(['GET', 'POST'])
@parser_classes([JSONParser])
@permission_classes([IsAdminRole])
def coverage_threshold(request):
    """GET: the current coverage threshold and its full history. POST: a new value from an effective date
    ({value_pct, effective_from, reason, confirm_retroactive?}). Every change is kept with the previous value, the
    administrator and the time. A date before today re-labels earlier non-finalized dates and needs
    ``confirm_retroactive: true``; a date inside a finalized month is refused (finalized results are never rewritten)."""
    from django.db import transaction
    from django.utils import timezone

    from . import reporting
    today = timezone.localdate()
    if request.method == 'GET':
        history = CoverageThreshold.objects.select_related('changed_by').order_by('-effective_from', '-id')
        return Response({'current_pct': reporting.threshold_on(today), 'availability_threshold_pct': 98.5, 'history': [{
            'value_pct': float(h.value_pct), 'previous_value_pct': None if h.previous_value_pct is None else float(h.previous_value_pct),
            'effective_from': h.effective_from.isoformat(), 'reason': h.reason, 'changed_by': h.changed_by.get_username() if h.changed_by else None,
            'changed_at': h.changed_at.isoformat()} for h in history]})
    data = request.data
    try:
        value = float(data.get('value_pct'))
    except (TypeError, ValueError) as exc:
        raise ValidationError({'value_pct': 'Give the coverage threshold as a percentage (0-100).'}) from exc
    if not 0 <= value <= 100:
        raise ValidationError({'value_pct': 'The coverage threshold must be between 0 and 100.'})
    effective = _date(data.get('effective_from'), 'effective_from')
    reason = str(data.get('reason') or '').strip()
    if not reason:
        raise ValidationError({'reason': 'Give the reason for the change.'})
    finalized = MonthFinalization.objects.filter(reopened_at__isnull=True, month__gte=effective.replace(day=1)).values_list('month', flat=True)
    if finalized:
        raise ValidationError({'effective_from': 'Finalized months cannot be re-evaluated: choose a date after '
                                                 + ', '.join(f'{m:%b %Y}' for m in sorted(finalized)) + ' (or reopen those months first).'})
    if effective < today and data.get('confirm_retroactive') is not True:
        raise ValidationError({'confirm_retroactive': f'{effective:%d %b %Y} is in the past: the statuses of earlier non-finalized dates will change. '
                                                      'Confirm with confirm_retroactive: true.'})
    with transaction.atomic():
        previous = reporting.threshold_on(effective)
        row = CoverageThreshold.objects.create(value_pct=reporting.as_decimal(value), previous_value_pct=reporting.as_decimal(previous),
                                               effective_from=effective, reason=reason, changed_by=request.user)
    _after_configuration_change()
    audit('sitedata.coverage_threshold_changed', request, value=value, previous=previous, effective_from=effective, reason=reason)
    return Response({'value_pct': float(row.value_pct), 'previous_value_pct': previous, 'effective_from': effective.isoformat()},
                    status=status.HTTP_201_CREATED)


def _after_configuration_change() -> None:
    from . import portfolio
    portfolio.clear_cache()
