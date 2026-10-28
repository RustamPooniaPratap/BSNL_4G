"""RCA API. Permissions are enforced here, whatever the interface shows.

- Any portal user (Admin or CI): read the register and records, record a new RCA incident, update a
  record's follow-up (status up to Action Completed, corrective action, owner, dates) and add comments.
  The portal has no circle-level scope for CI users, so none is applied.
- Admin only: the RCA Summary, imports, cause categories and mappings, root-cause review, verification
  and closure, and editing a manually recorded RCA created by someone else.
- Imported source facts are never edited through the API; a corrected workbook is re-imported instead.
"""
import csv
import io
import tempfile
from datetime import date
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.accounts.audit import audit
from apps.accounts.permissions import IsAdminRole, IsPortalUser
from apps.accounts.roles import ADMIN, role_of

from . import importer, parser, services
from .models import RcaCauseCategory, RcaCauseMapping, RcaComment, RcaEvent, RcaImportBatch, RcaRecord, RcaWorkflow

ALLOWED = ('.xlsx', '.xlsm')
PROJECTS = ('4G Saturation', 'LWE')
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
    project = data.get('project')
    if project not in PROJECTS:
        errors['project'] = 'Choose 4G Saturation or LWE.'
    circle = str(data.get('circle') or '').strip().upper()
    if circle not in parser.CIRCLE_CODES:
        errors['circle'] = 'Choose a circle.'
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
    return Response(services.summary(request.query_params))


# --- Imports (Admin) -----------------------------------------------------------------------------

def _batch_json(batch: RcaImportBatch, *, full: bool = False) -> dict:
    data = {
        'id': batch.pk, 'status': batch.status, 'file': batch.original_filename, 'checksum': batch.checksum_sha256,
        'sheet': batch.sheet_name, 'uploaded_at': batch.uploaded_at.isoformat(),
        'committed_at': batch.committed_at.isoformat() if batch.committed_at else None,
        'imported_by': batch.imported_by.get_username() if batch.imported_by else None,
        'counts': batch.counts, 'conflict_action': batch.conflict_action or None, 'error': batch.error or None,
    }
    if full:
        data['report'] = {k: v for k, v in batch.report.items() if k != 'all_issues'}
    return data


def _batch(batch_id: int) -> RcaImportBatch:
    batch = RcaImportBatch.objects.filter(pk=batch_id).first()
    if batch is None:
        raise NotFound('No such RCA import.')
    return batch


@api_view(['GET'])
@permission_classes([IsAdminRole])
def import_list(request):
    return Response({'imports': [_batch_json(b) for b in RcaImportBatch.objects.select_related('imported_by')[:30]],
                     'records': RcaRecord.objects.count()})


@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser])
@permission_classes([IsAdminRole])
def import_preview(request):
    upload = request.FILES.get('file')
    if upload is None:
        raise ValidationError({'file': 'Choose the RCA workbook (.xlsx).'})
    name = Path(upload.name).name
    if Path(name).suffix.lower() not in ALLOWED:
        raise ValidationError({'file': f'{name}: choose an Excel workbook (.xlsx).'})
    if upload.size > settings.MAX_WORKBOOK_BYTES:
        raise ValidationError({'file': f'{name} is larger than {settings.MAX_WORKBOOK_BYTES // (1024 * 1024)} MB.'})
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=Path(name).suffix.lower())
    for chunk in upload.chunks():
        handle.write(chunk)
    handle.close()
    try:
        batch = importer.preview(Path(handle.name), name, user=request.user)
    except importer.ImportRejected as exc:
        return Response({'error': str(exc), 'details': {}}, status=exc.status)
    finally:
        Path(handle.name).unlink(missing_ok=True)
    audit('rca_import_previewed', request, batch=batch.pk, file=name)
    return Response(_batch_json(batch, full=True), status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([IsAdminRole])
def import_detail(request, batch_id: int):
    return Response(_batch_json(_batch(batch_id), full=True))


@api_view(['GET'])
@permission_classes([IsAdminRole])
def import_issues_csv(request, batch_id: int):
    """Every rejected or flagged row, plus conflicts with the database, as CSV."""
    batch = _batch(batch_id)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(['file', 'severity', 'code', 'excel_row', 'site_id', 'message'])
    for item in batch.report.get('all_issues', []):
        writer.writerow([batch.original_filename, item['severity'], item['code'], item['row'] or '', item['site_id'], item['message']])
    for conflict in batch.report.get('conflicts', []):
        fields = '; '.join(f'{f}: database "{d["database"]}" vs file "{d["file"]}"' for f, d in conflict['differences'].items())
        writer.writerow([batch.original_filename, 'conflict', 'differs_from_database', conflict['row'], conflict['site_id'], fields])
    response = HttpResponse('﻿' + out.getvalue(), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="rca-import-{batch.pk}-validation.csv"'
    return response


@api_view(['POST'])
@parser_classes([JSONParser])
@permission_classes([IsAdminRole])
def import_commit(request, batch_id: int):
    batch = _batch(batch_id)
    try:
        batch = importer.commit(batch, user=request.user, conflict_action=request.data.get('conflict_action') or '')
    except importer.ImportRejected as exc:
        return Response({'error': str(exc), 'details': {}}, status=exc.status)
    audit('rca_import_committed', request, batch=batch.pk, **{k: v for k, v in batch.counts.items()})
    return Response({**_batch_json(batch, full=True), 'records': RcaRecord.objects.count()})


@api_view(['POST'])
@permission_classes([IsAdminRole])
def import_discard(request, batch_id: int):
    batch = _batch(batch_id)
    if batch.status != RcaImportBatch.Status.PREVIEWED:
        return Response({'error': 'Only a previewed import can be discarded.', 'details': {}}, status=409)
    batch.status, batch.rows = RcaImportBatch.Status.DISCARDED, []
    batch.save(update_fields=['status', 'rows'])
    audit('rca_import_discarded', request, batch=batch.pk)
    return Response(_batch_json(batch))


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
