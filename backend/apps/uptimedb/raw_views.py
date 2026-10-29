"""Raw daily CSV upload API (Data Entry -> Upload CSV). Permissions are enforced here, whatever the interface shows.

- Any portal user may use it within their circles (accounts.scope): Admin and NOC Lead every circle, a CI user only
  the circles assigned to the account (none assigned: nothing).
- An upload is visible to the user who made it and to Admins, and only within the user's circles; anything else
  answers "not found" so other users' uploads are not revealed.
"""
from __future__ import annotations

import csv
import io
import tempfile
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone
from openpyxl import Workbook
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.accounts.audit import audit
from apps.accounts.permissions import IsAdminRole, IsPortalUser
from apps.accounts.roles import ADMIN, role_of
from apps.accounts.scope import KNOWN_CIRCLES, allowed_circles, may_use_circle

from . import arrivals
from .models import DataImportBatch, UptimeSite
from .raw import parser
from .raw.rules import PROJECT_RULES
from .raw.resolvers import RESOLVERS
from .raw.service import EXPORT_HEADER, PROJECTS, Details, RawUploadRejected, commit, discard, export_rows, preview, rows_page, validation_csv

MAX_EXPORT_DAYS = 92


def _is_admin(request) -> bool:
    return role_of(request.user) == ADMIN


def _batch_json(batch: DataImportBatch, *, full: bool = False) -> dict:
    report = batch.report or {}
    data = {
        'id': batch.pk, 'status': batch.status, 'status_label': batch.get_status_display(), 'file': batch.original_filename,
        'checksum': batch.checksum_sha256, 'project': batch.project, 'circle': batch.circle,
        'reporting_date': batch.reporting_date.isoformat() if batch.reporting_date else None, 'remarks': batch.remarks or None,
        'uploaded_by': batch.imported_by.get_username() if batch.imported_by else None, 'uploaded_at': batch.uploaded_at.isoformat(),
        'committed_at': batch.committed_at.isoformat() if batch.committed_at else None, 'error': batch.error or None,
        'summary': report.get('summary'), 'daily': (batch.counts or {}).get('daily'),
        'rejected_count': batch.rejected_count, 'skipped_count': batch.skipped_count,
    }
    if full:
        data.update({k: report.get(k) for k in ('file_issues', 'blocked', 'availability_rule', 'resolver', 'master_scope', 'already_imported')})
        data['file_info'] = report.get('file')  # header line, preamble, columns, dates and circles found in the file
        data['rows'] = rows_page(batch) if report else None
    return data


def _batch(request, batch_id: int) -> DataImportBatch:
    batch = DataImportBatch.objects.select_related('imported_by').filter(pk=batch_id, kind=DataImportBatch.Kind.RAW_DAILY_CSV).first()
    if batch is None or not (_is_admin(request) or batch.imported_by_id == request.user.pk) or not may_use_circle(request.user, batch.circle):
        raise NotFound('No such upload.')
    return batch


def _error(exc: RawUploadRejected) -> Response:
    return Response({'error': str(exc), 'details': {}}, status=exc.status)


@api_view(['GET'])
@permission_classes([IsPortalUser])
def raw_options(request):
    """What the form may offer this user: projects, the circles of the site master within the user's scope, limits."""
    allowed = allowed_circles(request.user)
    master = sorted(set(UptimeSite.objects.order_by().values_list('project', 'circle').distinct()))
    return Response({
        'projects': [{'value': p, 'configured': RESOLVERS[p].configured, 'availability_column': PROJECT_RULES[p].availability_column,
                      'circles': [c for proj, c in master if proj == p and (allowed is None or c in allowed)]} for p in PROJECTS],
        'assigned_circles': None if allowed is None else sorted(allowed),
        'max_bytes': settings.MAX_UPLOAD_BYTES,
        'formula': 'outage minutes = 1440 × (1 − availability / 100)',
    })


@api_view(['GET'])
@permission_classes([IsPortalUser])
def raw_list(request):
    qs = DataImportBatch.objects.select_related('imported_by').filter(kind=DataImportBatch.Kind.RAW_DAILY_CSV)
    if not _is_admin(request):
        qs = qs.filter(imported_by=request.user)
    allowed = allowed_circles(request.user)
    if allowed is not None:
        qs = qs.filter(circle__in=allowed)
    return Response({'uploads': [_batch_json(b) for b in qs[:100]]})


def _details(request) -> Details:
    data = request.data
    errors = {}
    project = str(data.get('project') or '')
    if project not in PROJECTS:
        errors['project'] = 'Choose 4G Saturation or LWE.'
    circle = str(data.get('circle') or '').strip().upper()
    if circle not in KNOWN_CIRCLES:
        errors['circle'] = 'Choose a circle.'
    day = parser.parse_date(str(data.get('reporting_date') or ''))
    if day is None:
        errors['reporting_date'] = 'Enter the reporting date.'
    elif day > timezone.localdate():
        errors['reporting_date'] = 'The reporting date cannot be in the future.'
    if errors:
        raise ValidationError(errors)
    if not may_use_circle(request.user, circle):
        raise PermissionDenied(f'You are not assigned to circle {circle}. Ask an Admin to assign it to your account.')
    return Details(project, circle, day, str(data.get('remarks') or '').strip()[:2000])


@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser])
@permission_classes([IsPortalUser])
def raw_preview(request):
    details = _details(request)
    upload = request.FILES.get('file')
    if upload is None:
        raise ValidationError({'file': 'Choose the raw daily CSV file.'})
    name = Path(upload.name).name
    if Path(name).suffix.lower() != '.csv':
        raise ValidationError({'file': f'{name}: choose the CSV file exported from CNMC (.csv).'})
    if upload.size > settings.MAX_UPLOAD_BYTES:
        raise ValidationError({'file': f'{name} is larger than {settings.MAX_UPLOAD_BYTES // (1024 * 1024)} MB.'})
    handle = tempfile.NamedTemporaryFile(delete=False, suffix='.csv')
    for chunk in upload.chunks():
        handle.write(chunk)
    handle.close()
    try:
        batch = preview(Path(handle.name), name, details, user=request.user)
    except RawUploadRejected as exc:
        audit('raw_upload_failed', request, file=name, circle=details.circle, project=details.project)
        return _error(exc)
    finally:
        Path(handle.name).unlink(missing_ok=True)
    audit('raw_upload_previewed', request, batch=batch.pk, file=name, circle=details.circle, project=details.project, status=batch.status)
    return Response(_batch_json(batch, full=True), status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([IsPortalUser])
def raw_detail(request, batch_id: int):
    return Response(_batch_json(_batch(request, batch_id), full=True))


@api_view(['GET'])
@permission_classes([IsPortalUser])
def raw_rows(request, batch_id: int):
    try:
        page = int(request.query_params.get('page') or 1)
    except ValueError as exc:
        raise ValidationError({'page': 'Enter a page number.'}) from exc
    return Response(rows_page(_batch(request, batch_id), status=request.query_params.get('status') or '', page=page))


@api_view(['GET'])
@permission_classes([IsPortalUser])
def raw_issues_csv(request, batch_id: int):
    batch = _batch(request, batch_id)
    response = HttpResponse('﻿' + validation_csv(batch), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="raw-upload-{batch.pk}-validation.csv"'
    return response


@api_view(['POST'])
@parser_classes([JSONParser])
@permission_classes([IsPortalUser])
def raw_commit(request, batch_id: int):
    batch = _batch(request, batch_id)
    if request.data.get('confirm') is not True:
        raise ValidationError({'confirm': 'Confirm the import explicitly.'})
    try:
        batch = commit(batch, user=request.user)
    except RawUploadRejected as exc:
        return _error(exc)
    audit('raw_upload_committed', request, batch=batch.pk, circle=batch.circle, project=batch.project, **batch.counts.get('daily', {}))
    return Response(_batch_json(batch, full=True))


@api_view(['POST'])
@permission_classes([IsPortalUser])
def raw_discard(request, batch_id: int):
    try:
        batch = discard(_batch(request, batch_id))
    except RawUploadRejected as exc:
        return _error(exc)
    audit('raw_upload_discarded', request, batch=batch.pk)
    return Response(_batch_json(batch))


@api_view(['GET'])
@permission_classes([IsPortalUser])
def raw_export(request):
    """Consolidated daily records (PostgreSQL) of approved master sites, limited to the user's circles."""
    params = request.query_params
    project = params.get('project') or ''
    if project not in PROJECTS:
        raise ValidationError({'project': 'Choose 4G Saturation or LWE.'})
    start, end = parser.parse_date(params.get('date_from') or ''), parser.parse_date(params.get('date_to') or '')
    if start is None or end is None or end < start:
        raise ValidationError({'date_from': 'Enter the first and last reporting dates.'})
    if (end - start).days >= MAX_EXPORT_DAYS:
        raise ValidationError({'date_to': f'Export at most {MAX_EXPORT_DAYS} days at a time.'})
    allowed = allowed_circles(request.user)
    circle = (params.get('circle') or '').upper()
    if circle:
        if not may_use_circle(request.user, circle):
            raise PermissionDenied(f'You are not assigned to circle {circle}.')
        circles = [circle]
    else:
        circles = None if allowed is None else sorted(allowed)
        if circles == []:
            raise PermissionDenied('No circle is assigned to your account.')
    rows = export_rows(project=project, circles=circles, date_from=start, date_to=end)
    audit('raw_data_exported', request, project=project, circle=circle or 'all permitted', rows=len(rows))
    stem = f'daily_{project.replace(" ", "_")}_{circle or "circles"}_{start.isoformat()}_{end.isoformat()}'
    if params.get('output') == 'xlsx':  # not "format": DRF reserves that parameter for its renderers
        book = Workbook()
        ws = book.active
        ws.title = 'Daily records'
        ws.append(EXPORT_HEADER)
        for row in rows:
            ws.append(row)
        if not rows:
            ws.append(['No daily records for these filters.'])
        out = io.BytesIO()
        book.save(out)
        response = HttpResponse(out.getvalue(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = f'attachment; filename="{stem}.xlsx"'
        return response
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(EXPORT_HEADER)
    writer.writerows(rows)
    response = HttpResponse('﻿' + out.getvalue(), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{stem}.csv"'
    return response


def _query_date(request, name: str):
    text = request.query_params.get(name, '').strip()
    if not text:
        return None
    day = parser.parse_date(text)
    if day is None:
        raise ValidationError({name: 'Give the date as YYYY-MM-DD.'})
    return day


@api_view(['GET'])
@permission_classes([IsAdminRole])  # CSV arrival tracking is an Admin page; circles are still limited by accounts.scope
def arrival_tracker(request):
    """Per project/circle for ?date=YYYY-MM-DD: stored daily-data coverage and raw CSV uploads, plus a daily range
    (?start=&end=, at most 92 days) for gaps. Read only; computed from PostgreSQL on every request."""
    day = _query_date(request, 'date')
    if day is None:
        raise ValidationError({'date': 'Give the reporting date as YYYY-MM-DD.'})
    start, end = _query_date(request, 'start'), _query_date(request, 'end')
    if bool(start) != bool(end):
        raise ValidationError({'range': 'Give both start and end, or neither.'})
    if start and end and start > end:
        raise ValidationError({'range': 'The range start is after its end.'})
    if start and end and (end - start).days >= arrivals.MAX_RANGE_DAYS:
        raise ValidationError({'range': f'Choose at most {arrivals.MAX_RANGE_DAYS} days.'})
    return Response(arrivals.tracker(day, allowed_circles(request.user), start, end))
