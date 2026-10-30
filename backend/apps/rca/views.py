"""RCA API. Permissions are enforced here, whatever the interface shows.

- Any portal user (Admin or CI): read the register and records, record a new RCA incident, update a
  record's follow-up (status up to Action Completed, corrective action, owner, dates) and add comments.
  The portal has no circle-level scope for CI users, so none is applied.
- Admin and NOC Lead: upload the consolidated RCA workbook (validate, confirm, import) and see the results,
  validation reports and consolidated workbook of their uploads. A NOC Lead sees their own uploads only.
- Admin only: the RCA Summary, every upload, reporting periods (expected scope, received / pending data, final
  reports), cause categories and mappings, root-cause review, verification and closure, and editing a manually
  recorded RCA created by someone else. CI users cannot upload.
- Imported source facts are never edited through the API; a corrected workbook is re-imported instead.
"""
import csv
import io
import tempfile
from datetime import date
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.http import FileResponse, HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.accounts.audit import audit
from apps.accounts.permissions import CanUploadRca, IsAdminRole, IsPortalUser
from apps.accounts.roles import ADMIN, can_upload_circle_rca, can_upload_consolidated_rca, can_upload_rca, role_of

from . import cycles, importer, parser, services
from .models import (RcaCauseCategory, RcaCauseMapping, RcaComment, RcaEvent, RcaImportBatch, RcaRecord,
                     RcaReport, RcaReportingCycle, RcaWorkflow)

ALLOWED = ('.xlsx', '.xlsm')
ADMIN_STATUSES = {RcaWorkflow.Status.CLOSED}
WORKFLOW_FIELDS = ('status', 'review_status', 'corrective_action', 'owner', 'target_date', 'completed_date', 'verification')


def _is_admin(request) -> bool:
    return role_of(request.user) == ADMIN


def _record(record_id: int) -> RcaRecord:
    rec = services.with_category(RcaRecord.objects.select_related('workflow', 'created_by')).filter(pk=record_id).first()
    if rec is None:
        raise NotFound('No such RCA record.')
    return rec


# --- Register ------------------------------------------------------------------------------------

@api_view(['GET'])
@permission_classes([IsPortalUser])
def options(request):
    return Response(services.options())


@api_view(['GET', 'POST'])
@parser_classes([JSONParser])
@permission_classes([IsPortalUser])
def records(request):
    if request.method == 'GET':
        return Response(services.register(request.query_params))
    fields = _manual_fields(request.data)
    with transaction.atomic():
        rec = RcaRecord.objects.create(**fields, source=RcaRecord.Source.MANUAL, created_by=request.user)
        RcaEvent.objects.create(record=rec, user=request.user, action='recorded', changes={})
    audit('rca_recorded', request, record=rec.pk, site=rec.site_id)
    same_day = RcaRecord.objects.filter(reporting_date=rec.reporting_date, project=rec.project, site_key=rec.site_key).exclude(pk=rec.pk).count()
    return Response({**services.record_json(_record(rec.pk), full=True),
                     'warning': f'{same_day} other RCA record(s) exist for this site on this date.' if same_day else None},
                    status=status.HTTP_201_CREATED)


@api_view(['GET', 'PATCH'])
@parser_classes([JSONParser])
@permission_classes([IsPortalUser])
def record_detail(request, record_id: int):
    rec = _record(record_id)
    if request.method == 'PATCH':
        if rec.source != RcaRecord.Source.MANUAL:
            return Response({'error': 'Imported RCA facts are kept as in the source workbook. Re-import a corrected workbook to change them.',
                             'details': {}}, status=409)
        if not (_is_admin(request) or rec.created_by_id == request.user.pk):
            raise PermissionDenied('Only an Admin or the person who recorded this RCA can edit it.')
        fields = _manual_fields({**services.record_json(rec), **request.data})
        before = {f: getattr(rec, f) for f in fields}
        for field, value in fields.items():
            setattr(rec, field, value)
        rec.save()
        changes = {f: {'from': _plain(before[f]), 'to': _plain(v)} for f, v in fields.items() if before[f] != v}
        RcaEvent.objects.create(record=rec, user=request.user, action='record_edited', changes=changes)
        audit('rca_record_edited', request, record=rec.pk)
        rec = _record(record_id)
    return Response(services.record_json(rec, full=True))


def _manual_fields(data) -> dict:
    """Validate a manually recorded RCA with the same rules as the import."""
    errors = {}
    day = parser._date(data.get('reporting_date'))
    if day is None:
        errors['reporting_date'] = 'Enter the reporting date.'
    elif day > timezone.localdate():
        errors['reporting_date'] = 'The reporting date cannot be in the future.'
    from apps.organization import services as organization
    project = data.get('project')
    if project not in organization.project_keys(active_only=True):
        errors['project'] = 'Choose an active project.'
    circle = str(data.get('circle') or '').strip().upper()
    if not circle:
        errors['circle'] = 'Choose a circle.'
    elif project and 'project' not in errors and not organization.is_associated(project, circle):
        errors['circle'] = f'{circle} is not an active circle of {project} (Administration > Organization).'
    site_id = str(data.get('site_id') or '').strip()
    if not site_id:
        errors['site_id'] = 'Enter the Site ID.'
    outage, valid = parser._number(data.get('outage_minutes'))
    if not valid or (outage is not None and outage < 0):
        errors['outage_minutes'] = 'Enter the outage in minutes (0 or more), or leave it blank if not known.'
    om_raw = str(data.get('om_start_raw') or '').strip()
    if om_raw and om_raw.casefold() not in ('yes', 'no'):
        errors['om_start_raw'] = 'Choose Yes or No, or leave it blank.'
    text = lambda name, limit: str(data.get(name) or '').strip()[:limit]  # noqa: E731
    if not text('rca_text', 5000):
        errors['rca_text'] = 'Describe the RCA.'
    if errors:
        raise ValidationError(errors)
    final_bucket, bucket_2, rca_text = text('final_bucket', 100), text('bucket_2', 100), text('rca_text', 5000)
    return {
        'reporting_date': day, 'project': project, 'project_raw': project, 'circle': circle, 'circle_raw': circle,
        'site_id': site_id, 'site_key': parser.site_key(site_id), 'site_name': text('site_name', 200), 'oa': text('oa', 100),
        'ba': text('ba', 100), 'om_start_raw': om_raw, 'om_start': {'yes': True, 'no': False}.get(om_raw.casefold()),
        'outage_minutes': outage, 'final_bucket': final_bucket, 'final_bucket_key': parser.text_key(final_bucket),
        'bucket_2': bucket_2, 'bucket_2_key': parser.text_key(bucket_2), 'rca_text': rca_text, 'rca_key': parser.text_key(rca_text),
    }


def _plain(value):
    return value.isoformat() if isinstance(value, date) else value


@api_view(['PUT'])
@parser_classes([JSONParser])
@permission_classes([IsPortalUser])
def record_workflow(request, record_id: int):
    """Follow-up of one record. CI may move it up to Action Completed; review, verification and closure are Admin's."""
    rec = _record(record_id)
    workflow = getattr(rec, 'workflow', None) or RcaWorkflow(record=rec)
    admin = _is_admin(request)
    data = request.data
    errors = {}
    values = {}
    for field in WORKFLOW_FIELDS:
        if field not in data:
            values[field] = getattr(workflow, field)
            continue
        raw = data.get(field)
        if field in ('target_date', 'completed_date'):
            value = parser._date(raw) if raw else None
            if raw and value is None:
                errors[field] = 'Enter a valid date.'
        else:
            value = str(raw or '').strip()
        values[field] = value
    choices = {'status': RcaWorkflow.Status.values, 'review_status': RcaWorkflow.Review.values, 'verification': RcaWorkflow.Verification.values}
    for field, allowed in choices.items():
        if values[field] and values[field] not in allowed:
            errors[field] = 'Choose one of the listed values.'
    changed = {f for f in WORKFLOW_FIELDS if values[f] != getattr(workflow, f)}
    if not admin:
        locked = {'review_status', 'verification'} & changed
        if locked or (values['status'] in ADMIN_STATUSES and 'status' in changed):
            raise PermissionDenied('Root-cause review, verification and closure are recorded by an Admin.')
    if values['status'] == RcaWorkflow.Status.ACTION_COMPLETED and not (values['corrective_action'] and values['completed_date']):
        errors['status'] = 'Action Completed needs the corrective action and its completion date.'
    if values['status'] == RcaWorkflow.Status.CLOSED and not values['verification']:
        errors['verification'] = 'Record the verification outcome before closing.'
    if values['completed_date'] and values['completed_date'] > timezone.localdate():
        errors['completed_date'] = 'The completion date cannot be in the future.'
    if values['completed_date'] and values['completed_date'] < rec.reporting_date:
        errors['completed_date'] = 'The completion date is before the RCA reporting date.'
    if errors:
        raise ValidationError(errors)
    if not changed:
        return Response(services.record_json(_record(record_id), full=True))
    before = {f: _plain(getattr(workflow, f)) for f in changed}
    for field in WORKFLOW_FIELDS:
        setattr(workflow, field, values[field])
    workflow.updated_by = request.user
    if admin and {'review_status', 'verification'} & changed:
        workflow.reviewer, workflow.reviewed_at = request.user, timezone.now()
    with transaction.atomic():
        workflow.save()
        RcaEvent.objects.create(record=rec, user=request.user, action='workflow_updated',
                                changes={f: {'from': before[f], 'to': _plain(values[f])} for f in changed})
    audit('rca_workflow_updated', request, record=rec.pk, fields=','.join(sorted(changed)))
    return Response(services.record_json(_record(record_id), full=True))


@api_view(['POST'])
@parser_classes([JSONParser])
@permission_classes([IsPortalUser])
def record_comments(request, record_id: int):
    rec = _record(record_id)
    text = str(request.data.get('text') or '').strip()
    if not text:
        raise ValidationError({'text': 'Write a comment.'})
    RcaComment.objects.create(record=rec, author=request.user, text=text[:5000], evidence=str(request.data.get('evidence') or '').strip()[:500])
    audit('rca_comment_added', request, record=rec.pk)
    return Response(services.record_json(_record(record_id), full=True), status=status.HTTP_201_CREATED)


# --- Summary -------------------------------------------------------------------------------------

@api_view(['GET'])
@permission_classes([IsAdminRole])
def summary(request):
    data = services.summary(request.query_params)
    # The reporting period matching the filtered dates (or the latest period), for its coverage and its report.
    params = request.query_params
    day = services._date(params.get('date'), 'date')
    start, end = services._date(params.get('date_from'), 'date_from'), services._date(params.get('date_to'), 'date_to')
    periods = RcaReportingCycle.objects.select_related('created_by')
    if day:
        cycle = next((c for c in periods.filter(reporting_date__lte=day) if c.end >= day), None)
    elif start and end:
        cycle = next((c for c in periods.filter(reporting_date=start) if c.end == end), None)
    else:
        cycle = periods.first()
    data['cycle'] = {**cycles.cycle_json(cycle), 'matches_filter': bool(day or (start and end))} if cycle else None
    return Response(data)


# --- Uploads -------------------------------------------------------------------------------------
# Two upload types, checked here on every request whatever the interface shows:
# - Upload Circle RCA: Admins and NOC Leads for every project and circle; CI users for the project/circle pairs granted
#   to them (Organization > User Access).
# - Upload Consolidated RCA: Admins and members of the "RCA Consolidated Uploaders" group only.
# Users see and act on their own uploads only; an Admin on every upload. Permissions are checked again at commit.

UPLOAD_TYPES = (RcaImportBatch.UploadType.CIRCLE, RcaImportBatch.UploadType.CONSOLIDATED)


def _may_upload(user, kind: str, project: str = '', circle: str | None = None) -> bool:
    if kind == RcaImportBatch.UploadType.CONSOLIDATED:
        return can_upload_consolidated_rca(user)
    if kind == RcaImportBatch.UploadType.CIRCLE:
        return can_upload_circle_rca(user, project, circle)
    return can_upload_rca(user)  # legacy uploads: as before (Admin, NOC Lead)


def _rights(user) -> dict:
    """What the upload page may offer (the server checks every request again)."""
    from apps.accounts.scope import allowed_pairs
    pairs = allowed_pairs(user)
    return {'circle': can_upload_circle_rca(user), 'consolidated': can_upload_consolidated_rca(user),
            'access': None if pairs is None else [{'project': p, 'circle': c} for p, c in sorted(pairs)]}


def _batch(request, batch_id: int) -> RcaImportBatch:
    batch = RcaImportBatch.objects.select_related('cycle', 'imported_by').filter(pk=batch_id).first()
    if batch is None or not (_is_admin(request) or batch.imported_by_id == request.user.pk):
        raise NotFound('No such RCA upload.')  # another user's upload is not revealed
    return batch


def _batch_json(batch: RcaImportBatch, *, full: bool = False) -> dict:
    return cycles.batch_json(batch, full=full)


@api_view(['GET'])
@permission_classes([IsPortalUser])
def import_list(request):
    """The signed-in user's uploads; an Admin may ask for every upload with ?all=1."""
    qs = RcaImportBatch.objects.select_related('imported_by')
    everyone = _is_admin(request) and request.query_params.get('all') == '1'
    if not everyone:
        qs = qs.filter(imported_by=request.user)
    kind = request.query_params.get('upload_type')
    if kind in UPLOAD_TYPES:
        qs = qs.filter(upload_type=kind)
    return Response({'imports': [_batch_json(b) for b in qs[:100]], 'records': RcaRecord.objects.count(), 'all': everyone,
                     'rights': _rights(request.user),
                     'max_bytes': settings.MAX_WORKBOOK_BYTES})  # shown on the upload page; the upload itself checks it


def _details(data) -> dict:
    """The upload's details, by type. A circle upload: project, circle and reporting date. A consolidated upload: report
    name, project scope and optionally the reporting date (otherwise the latest date in the workbook)."""
    from apps.organization import services as organization
    errors = {}
    kind = str(data.get('upload_type') or '')
    if kind not in UPLOAD_TYPES:
        raise ValidationError({'upload_type': 'Choose Upload Circle RCA or Upload Consolidated RCA.'})
    raw_start = data.get('period_start') or data.get('reporting_date')
    start = parser._date(raw_start) if raw_start else None
    if raw_start and start is None:
        errors['period_start'] = 'Enter a valid reporting date.'
    elif start and start > timezone.localdate():
        errors['period_start'] = 'The reporting date cannot be in the future.'
    end = parser._date(data.get('period_end')) if data.get('period_end') else start
    if start and end != start:
        errors['period_end'] = 'An RCA upload is for one reporting date; periods are daily.'
    remarks = str(data.get('remarks') or '').strip()[:2000]
    if kind == RcaImportBatch.UploadType.CIRCLE:
        project = str(data.get('project') or '')
        circle = str(data.get('circle') or '').strip().upper()
        if not raw_start:
            errors['period_start'] = 'Enter the reporting date.'
        if project not in organization.project_keys(active_only=True):
            errors['project'] = 'Choose the project.'
        elif not circle:
            errors['circle'] = 'Choose the circle.'
        elif not organization.is_associated(project, circle):
            errors['circle'] = f'{circle} is not an active circle of {project} (Administration > Organization).'
        if errors:
            raise ValidationError(errors)
        name = ' '.join(str(data.get('report_name') or '').split())[:200] or f'{circle} {project} RCA {start:%d %b %Y}'
        return {'upload_type': kind, 'report_name': name, 'period_start': start, 'project_scope': project, 'circle': circle,
                'remarks': remarks}
    name = ' '.join(str(data.get('report_name') or '').split())[:200]
    if not name:
        errors['report_name'] = 'Enter the report name, e.g. "October 2026 RCA Report".'
    scope = str(data.get('project_scope') or '')
    if scope != 'both' and scope not in organization.project_keys(active_only=True):  # "both": every project
        errors['project_scope'] = 'Choose a project, or every project.'
    if errors:
        raise ValidationError(errors)
    return {'upload_type': kind, 'report_name': name, 'period_start': start, 'project_scope': scope, 'remarks': remarks}


@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser])
@permission_classes([IsPortalUser])
def import_preview(request):
    """Upload a circle or consolidated RCA workbook with its details and validate it (nothing is imported yet)."""
    details = _details(request.data)
    if not _may_upload(request.user, details['upload_type'], details['project_scope'], details.get('circle')):
        audit('rca_upload_refused', request, upload_type=details['upload_type'], circle=details.get('circle') or '-')
        raise PermissionDenied('You may not upload this RCA file: consolidated uploads need the RCA Consolidated Uploaders group, '
                               'and circle uploads a project and circle granted to your account.')
    upload = _upload(request)
    name = Path(upload.name).name
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=Path(name).suffix.lower())
    for chunk in upload.chunks():
        handle.write(chunk)
    handle.close()
    try:
        batch = importer.preview(Path(handle.name), name, user=request.user, details=details)
    except (importer.ImportRejected, cycles.CycleError) as exc:
        audit('rca_upload_failed', request, file=name, report=details['report_name'])
        return Response({'error': str(exc), 'details': {}}, status=exc.status)
    finally:
        Path(handle.name).unlink(missing_ok=True)
    audit('rca_import_previewed', request, batch=batch.pk, file=name, report=details['report_name'], status=batch.status,
          upload_type=batch.upload_type, circle=batch.circle or '-')
    return Response(_batch_json(batch, full=True), status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([IsPortalUser])
def import_detail(request, batch_id: int):
    return Response(_batch_json(_batch(request, batch_id), full=True))


@api_view(['GET'])
@permission_classes([IsPortalUser])
def import_issues_csv(request, batch_id: int):
    """Every rejected or flagged row, plus differences from stored records, as CSV."""
    batch = _batch(request, batch_id)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(['file', 'severity', 'code', 'excel_row', 'site_id', 'message'])
    for item in batch.report.get('all_issues', []):
        writer.writerow([batch.original_filename, item['severity'], item['code'], item['row'] or '', item['site_id'], item['message']])
    for conflict in batch.report.get('conflicts', []):
        fields = '; '.join(f'{f}: database "{d["database"]}" vs file "{d["file"]}"' for f, d in conflict['differences'].items())
        writer.writerow([batch.original_filename, 'conflict', 'differs_from_database', conflict['row'], conflict['site_id'], fields])
    for item in batch.report.get('missing', []):
        writer.writerow([batch.original_filename, 'correction', 'not_in_corrected_file', '', item['site_id'],
                         f'Stored record #{item["record_id"]} ({item["project"]} / {item["circle"]}, {item.get("reporting_date", "")}, '
                         f'from {item["source_file"] or "the portal"}) is not in this workbook.'])
    if batch.error and not batch.report:
        writer.writerow([batch.original_filename, 'error', 'unreadable_workbook', '', '', batch.error])
    response = HttpResponse('\ufeff' + out.getvalue(), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="rca-import-{batch.pk}-validation.csv"'
    return response


@api_view(['POST'])
@parser_classes([JSONParser])
@permission_classes([IsPortalUser])
def import_commit(request, batch_id: int):
    batch = _batch(request, batch_id)
    # Checked again: the user's group or project/circle access may have changed since the preview.
    if not _may_upload(request.user, batch.upload_type, batch.project_scope, batch.circle):
        raise PermissionDenied('You may no longer upload this RCA file.')
    try:
        batch = importer.commit(batch, user=request.user, conflict_action=request.data.get('conflict_action') or '',
                                missing_action=request.data.get('missing_action') or '',
                                accept_rejected=request.data.get('accept_rejected') is True)
    except (importer.ImportRejected, cycles.CycleError) as exc:
        return Response({'error': str(exc), 'details': {}}, status=exc.status)
    audit('rca_import_committed', request, batch=batch.pk, **{k: v for k, v in batch.counts.items()})
    # Every period whose records changed: the upload's own and those of earlier dates the workbook added or corrected.
    touched = {batch.cycle} if batch.cycle_id else set()
    for day in batch.counts.get('dates_changed', []):
        touched |= {c for c in RcaReportingCycle.objects.filter(reporting_date__lte=day) if c.end.isoformat() >= day}
    finals = [f for f in (cycles.after_commit(c, user=request.user) for c in touched) if f is not None]
    for f in finals:
        audit('rca_final_report_generated', request, cycle=f.cycle_id, version=f.version, automatic=True)
    final = next((f for f in finals if f.cycle_id == batch.cycle_id), finals[0] if finals else None)
    return Response({**_batch_json(batch, full=True), 'records': RcaRecord.objects.count(),
                     'final_report': cycles.report_json(final) if final else None})


@api_view(['POST'])
@permission_classes([IsPortalUser])
def import_discard(request, batch_id: int):
    batch = _batch(request, batch_id)
    if batch.status != RcaImportBatch.Status.PREVIEWED:
        return Response({'error': 'Only an upload awaiting confirmation can be discarded.', 'details': {}}, status=409)
    batch.status, batch.rows = RcaImportBatch.Status.DISCARDED, []
    batch.save(update_fields=['status', 'rows'])
    audit('rca_import_discarded', request, batch=batch.pk)
    return Response(_batch_json(batch))


@api_view(['GET'])
@permission_classes([CanUploadRca])
def import_workbook(request, batch_id: int):
    """The consolidated RCA workbook of the period an upload was accepted into (the uploader's own, or any for an Admin)."""
    batch = _batch(request, batch_id)
    if batch.cycle_id is None or batch.status != RcaImportBatch.Status.COMMITTED:
        return Response({'error': 'The consolidated report is available once the upload has been imported.', 'details': {}}, status=409)
    return _period_workbook(request, batch.cycle)


# --- Reporting periods (Admin) -------------------------------------------------------------------

def _upload(request):
    upload = request.FILES.get('file')
    if upload is None:
        raise ValidationError({'file': 'Choose the RCA workbook (.xlsx).'})
    name = Path(upload.name).name
    if Path(name).suffix.lower() not in ALLOWED:
        raise ValidationError({'file': f'{name}: choose an Excel workbook (.xlsx).'})
    if upload.size > settings.MAX_WORKBOOK_BYTES:
        raise ValidationError({'file': f'{name} is larger than {settings.MAX_WORKBOOK_BYTES // (1024 * 1024)} MB.'})
    return upload


def _cycle(cycle_id: int) -> RcaReportingCycle:
    cycle = RcaReportingCycle.objects.select_related('created_by').filter(pk=cycle_id).first()
    if cycle is None:
        raise NotFound('No such reporting period.')
    return cycle


def _cycle_error(exc: cycles.CycleError) -> Response:
    return Response({'error': str(exc), 'details': {}}, status=exc.status)


@api_view(['GET', 'POST'])
@parser_classes([JSONParser])
@permission_classes([IsAdminRole])
def cycle_list(request):
    if request.method == 'GET':
        return Response({'cycles': [cycles.cycle_json(c) for c in RcaReportingCycle.objects.select_related('created_by')[:36]],
                         'default_units': [list(u) for u in cycles.default_units()],
                         'available_units': [list(u) for u in cycles.available_units()]})
    start = parser._date(request.data.get('period_start') or request.data.get('reporting_date'))
    end = parser._date(request.data.get('period_end')) if request.data.get('period_end') else start
    if start is None or end is None:
        raise ValidationError({'period_start': 'Enter the reporting date or period.'})
    if end < start:
        raise ValidationError({'period_end': 'The period ends before it starts.'})
    if start > timezone.localdate():
        raise ValidationError({'period_start': 'The reporting period cannot start in the future.'})
    try:
        units = cycles.validate_units(request.data['units']) if 'units' in request.data else cycles.default_units()
        with transaction.atomic():
            if cycles.period_cycle(start, end) is not None:
                raise ValidationError({'period_start': f'The period {cycles.period_label(start, end)} already exists.'})
            cycle = cycles.period_cycle(start, end, create=True, user=request.user,
                                        name=' '.join(str(request.data.get('name') or '').split())[:200])
            cycle.notes = str(request.data.get('notes') or '').strip()[:2000]
            cycle.save(update_fields=['notes'])
            cycles.set_required(cycle, units)
    except cycles.CycleError as exc:
        raise ValidationError({'period_start': str(exc)}) from exc
    audit('rca_cycle_started', request, cycle=cycle.pk, start=start.isoformat(), end=end.isoformat(), required=len(units))
    return Response(cycles.cycle_json(cycle, full=True), status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([IsAdminRole])
def cycle_detail(request, cycle_id: int):
    return Response(cycles.cycle_json(_cycle(cycle_id), full=True))


@api_view(['PUT'])
@parser_classes([JSONParser])
@permission_classes([IsAdminRole])
def cycle_required(request, cycle_id: int):
    """Configure the projects / circles the period is expected to cover."""
    cycle = _cycle(cycle_id)
    try:
        units = cycles.validate_units(request.data.get('units'))
        cycles.set_required(cycle, units)
    except cycles.CycleError as exc:
        return _cycle_error(exc)
    audit('rca_cycle_required_changed', request, cycle=cycle.pk, required=len(units))
    return Response(cycles.cycle_json(cycle, full=True))


@api_view(['POST'])
@permission_classes([IsAdminRole])
def cycle_finalize(request, cycle_id: int):
    """Generate the final report (or the revised version after an accepted correction). Unchanged records: no new version."""
    cycle = _cycle(cycle_id)
    try:
        report, created = cycles.generate_final(cycle, user=request.user)
    except cycles.CycleError as exc:
        return _cycle_error(exc)
    if created:
        audit('rca_final_report_generated', request, cycle=cycle.pk, version=report.version, automatic=False)
    return Response({**cycles.cycle_json(cycle, full=True), 'created': created, 'report': cycles.report_json(report)},
                    status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


@api_view(['GET'])
@permission_classes([IsAdminRole])
def cycle_workbook(request, cycle_id: int):
    return _period_workbook(request, _cycle(cycle_id))


def _period_workbook(request, cycle: RcaReportingCycle):
    """The consolidated workbook now: the current final version when it reflects the stored records, else a labelled draft."""
    state = cycles.status(cycle)
    if state['code'] == 'final':
        return _final_file(request, cycle.reports.first())
    content, filename = cycles.partial_workbook(cycle, user=request.user)
    audit('rca_partial_report_downloaded', request, cycle=cycle.pk, status=state['code'])
    response = HttpResponse(content, content_type=XLSX)
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@api_view(['GET'])
@permission_classes([IsAdminRole])
def cycle_report_file(request, cycle_id: int, report_id: int):
    report = RcaReport.objects.filter(pk=report_id, cycle_id=cycle_id).first()
    if report is None:
        raise NotFound('No such report.')
    return _final_file(request, report)


def _final_file(request, report: RcaReport):
    path = Path(report.stored_path)
    if not path.is_file():
        return Response({'error': f'The stored file of report v{report.version} is missing.', 'details': {}}, status=410)
    audit('rca_final_report_downloaded', request, cycle=report.cycle_id, version=report.version)
    return FileResponse(open(path, 'rb'), as_attachment=True, filename=report.filename, content_type=XLSX)


# --- Cause mapping (Admin) -----------------------------------------------------------------------

@api_view(['GET'])
@permission_classes([IsAdminRole])
def causes(request):
    return Response(services.cause_queue(request.query_params))


@api_view(['POST'])
@parser_classes([JSONParser])
@permission_classes([IsAdminRole])
def cause_categories(request):
    name = ' '.join(str(request.data.get('name') or '').split())
    if not name:
        raise ValidationError({'name': 'Enter a category name.'})
    if RcaCauseCategory.objects.filter(name__iexact=name).exists():
        raise ValidationError({'name': f'A category named "{name}" already exists.'})
    category = RcaCauseCategory.objects.create(name=name[:120], description=str(request.data.get('description') or '').strip(),
                                               created_by=request.user)
    audit('rca_category_created', request, category=category.name)
    return Response({'id': category.pk, 'name': category.name}, status=status.HTTP_201_CREATED)


@api_view(['POST', 'DELETE'])
@parser_classes([JSONParser])
@permission_classes([IsAdminRole])
def cause_mappings(request):
    """POST {keys, category}: approve the mapping of these descriptions. DELETE {keys}: return them to the queue.

    Only the listed descriptions are mapped (no automatic matching of similar text); the source RCA text is untouched.
    """
    keys = [str(k) for k in request.data.get('keys') or [] if str(k).strip()]
    if not keys:
        raise ValidationError({'keys': 'Select at least one description.'})
    known = dict(RcaRecord.objects.filter(rca_key__in=keys).order_by().values_list('rca_key', 'rca_text').distinct())
    unknown = [k for k in keys if k not in known]
    if unknown:
        raise ValidationError({'keys': f'{len(unknown)} selected description(s) are not in the RCA records.'})
    if request.method == 'DELETE':
        deleted, _ = RcaCauseMapping.objects.filter(rca_key__in=keys).delete()
        audit('rca_mapping_removed', request, count=deleted)
        return Response(services.cause_queue({}))
    category = RcaCauseCategory.objects.filter(pk=request.data.get('category')).first()
    if category is None:
        raise ValidationError({'category': 'Choose a category.'})
    with transaction.atomic():
        for key in keys:
            RcaCauseMapping.objects.update_or_create(rca_key=key, defaults={'category': category, 'example_text': known[key],
                                                                             'reviewed_by': request.user})
    audit('rca_mapping_approved', request, category=category.name, count=len(keys))
    return Response(services.cause_queue({}))
