"""Raw daily CNMC CSV upload API (Data Entry -> Upload CSV), mounted at /api/raw-uploads/, and the CSV arrival tracker
(/api/arrival-tracker/). Both run on the data layer: uploads are previewed and committed by sitedata.rawcsv into the
central daily table at precedence 1 (raw CSV), exactly where every dashboard page reads.

Permissions are enforced here, whatever the interface shows:
- CSV Upload (accounts catalog ``csv_upload.upload``) on the project/circle pair: Admin and NOC Lead everywhere, a CI
  user only on the pairs granted to the account (none granted: nothing). MP under 4G does not open MP under LWE.
- Projects (technologies) and circles come from the Organization: a circle is offered for a project only while it is
  associated with it and the project, circle and association are active.
- An upload is visible to the user who made it and to Admins, and only within the user's scope; anything else answers
  "not found" so other users' uploads are not revealed.
- Every row is classified (rawcsv: matched, unmatched_programme, outside_programme, invalid; summary['classification']).
  Only programme rows that do not resolve are pending (pending_sites); rows of BTSs outside the programme are counted
  for information only. No site is ever created from a CSV row.
"""
from __future__ import annotations

import csv
import io
import tempfile
from collections import Counter
from pathlib import Path

from django.conf import settings
from django.db import IntegrityError
from django.db.models import Count
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.accounts.access import can, pairs_for
from apps.accounts.audit import audit
from apps.accounts.permissions import Can, IsAdminRole
from apps.accounts.roles import ADMIN, role_of
from apps.organization import services as organization

from . import arrivals, rawcsv, rules, uploads
from .models import Site, SiteIdentifier, Technology, UploadBatch
from .sources import cnmc_csv

UPLOAD = ('csv_upload', 'upload')
ROW_PAGE = 100

# Reason code -> (status group shown in the preview filter, label).
REASONS = {
    'ready': ('ready', 'Ready to import'),
    'identical': ('identical', 'Already stored with the same value: skipped'),
    'duplicate_row': ('duplicate', 'Repeat of an earlier row with the same value: one record'),
    'conflicting_rows': ('duplicate', 'The site appears more than once with different values: not imported'),
    'conflict_existing': ('duplicate', 'A value of equal or higher precedence is already stored: kept'),
    'outside_scope': ('out_of_scope', 'Outside the dashboard reporting scope'),
    'other_technology': ('out_of_scope', 'Site of the other technology'),
    'unmatched': ('unresolved', 'Not in the site master: kept pending (no site is created)'),  # uploads before the classification
    'unmatched_programme': ('unresolved', 'Programme identifier that names no site of this upload: kept pending (no site is created)'),
    'outside_programme': ('out_of_scope', 'Not a programme site (no identifier known to the site master or LWE mapping): information only'),
    'blank_site_id': ('unresolved', 'Blank BTS IP ID'),
    'no_identifier': ('unresolved', 'No identifier on the row'),
    'invalid_identifier': ('unresolved', 'Identifier cell is not a single identifier'),
    'ambiguous_identifier': ('unresolved', 'Identifier claimed by several sites'),
    'identifier_mismatch': ('unresolved', 'Identifiers name different sites'),
    'identifier_not_in_mapping': ('unresolved', 'Band identifier not in the LWE mapping'),
    'other_circle': ('scope_mismatch', 'Circle in the file differs from the selected circle'),
    'site_of_other_circle': ('scope_mismatch', 'Master site of another circle'),
    'not_reported': ('availability', 'Availability blank: not reported (never 0)'),
    'invalid_availability': ('availability', 'Availability not a number'),
    'availability_out_of_range': ('availability', 'Availability outside 0-100'),
    'other_report_date': ('date', 'Report Date differs from the entered reporting date'),
    'future_date': ('date', 'Report Date is in the future'),
    'malformed_row': ('other', 'Row could not be read'),
}
SUMMARY_GROUPS = {
    'ready_to_import': ('ready',), 'identical_skipped': ('identical',), 'out_of_scope': ('out_of_scope',),
    'unresolved_or_ambiguous': ('unresolved',), 'availability_problems': ('availability',), 'duplicates_or_conflicts': ('duplicate',),
    'date_mismatches': ('date',), 'project_or_circle_mismatches': ('scope_mismatch',), 'other_invalid': ('other',),
}


def allowed_pairs(user):
    """Pairs of the user's CSV Upload permission (None: every pair)."""
    return pairs_for(user, *UPLOAD)


def may_use(user, project: str, circle: str) -> bool:
    return can(user, *UPLOAD, project, circle)


def _is_admin(request) -> bool:
    return role_of(request.user) == ADMIN


def _rows(batch: UploadBatch) -> list[dict]:
    out = []
    for r in (batch.report or {}).get('rows', []):
        group, label = REASONS.get(r['code'], ('other', r['code']))
        out.append({**r, 'status': group, 'label': label, 'note': '', 'category': r.get('category') or rawcsv.category_of(r['code'])})
    return out


def _summary(batch: UploadBatch, rows: list[dict]) -> dict | None:
    if not rows and not batch.records_received:
        return None
    by_code = Counter(r['code'] for r in rows)
    by_status = Counter(r['status'] for r in rows)
    summary = {name: sum(by_status.get(g, 0) for g in groups) for name, groups in SUMMARY_GROUPS.items()}
    summary.update({'total_rows': len(rows) or batch.records_received,
                    'valid_in_scope': sum(by_status.get(g, 0) for g in ('ready', 'identical', 'duplicate')),
                    'by_code': dict(by_code), 'by_status': dict(by_status)})
    stored = (batch.report or {}).get('classification')
    by_category = Counter(r['category'] for r in rows)
    summary['classification'] = stored or {c: by_category.get(c, 0) for c in rawcsv.CATEGORIES}
    return summary


def _status(batch: UploadBatch) -> tuple[str, str]:
    if batch.processing_status == UploadBatch.Processing.PREVIEWED and batch.validation_status == UploadBatch.Validation.FAILED:
        return 'rejected', 'Rejected (validation failed)'
    return batch.processing_status, batch.get_processing_status_display()


def _already_imported(batch: UploadBatch) -> dict | None:
    if not batch.checksum_sha256:
        return None
    previous = (UploadBatch.objects.filter(kind=batch.kind, checksum_sha256=batch.checksum_sha256, circle=batch.circle,
                                           reporting_date=batch.reporting_date, processing_status=UploadBatch.Processing.COMMITTED)
                .exclude(pk=batch.pk).order_by('committed_at').first())
    return {'batch': previous.pk, 'committed_at': previous.committed_at.isoformat()} if previous else None


def _batch_json(batch: UploadBatch, *, full: bool = False) -> dict:
    report = batch.report or {}
    rows = _rows(batch)
    state, label = _status(batch)
    committed = batch.processing_status == UploadBatch.Processing.COMMITTED
    data = {
        'id': batch.pk, 'status': state, 'status_label': label, 'file': batch.original_filename, 'checksum': batch.checksum_sha256,
        'project': batch.technology, 'circle': batch.circle,
        'reporting_date': batch.reporting_date.isoformat() if batch.reporting_date else None, 'remarks': batch.remarks or None,
        'uploaded_by': batch.uploaded_by.get_username() if batch.uploaded_by else None, 'uploaded_at': batch.uploaded_at.isoformat(),
        'committed_at': batch.committed_at.isoformat() if batch.committed_at else None,
        'error': batch.error or report.get('error') or None,
        'summary': _summary(batch, rows),
        'daily': {'inserted': batch.records_accepted, 'filled': 0, 'skipped_identical': batch.records_duplicate, 'skipped_repeats': 0,
                  'rejected': batch.records_rejected, 'conflicts': batch.records_conflict, 'pending': batch.records_unmatched} if committed else None,
        'rejected_count': batch.records_rejected, 'skipped_count': batch.records_duplicate + batch.records_unmatched,
    }
    if full:
        in_scope = report.get('sites_in_scope') or 0
        with_value = report.get('sites_with_value') or 0
        data.update({
            'file_issues': [{'code': 'file', 'message': data['error']}] if data['error'] else [],
            'blocked': batch.validation_status == UploadBatch.Validation.FAILED,
            'availability_rule': {'column': rules.AVAILABILITY_COLUMN, 'confirmed': True,
                                  'formula': 'outage minutes = 1440 × (1 − availability / 100)'},
            'resolver': {'project': batch.technology, 'configured': True},
            'master_scope': {'sites': in_scope, 'sites_in_file': with_value, 'missing_from_file': max(0, in_scope - with_value), 'missing_examples': []}
            if report else None,
            'already_imported': _already_imported(batch),
            'pending_sites': sorted({r['raw_id'] for r in rows if r['category'] == rawcsv.UNMATCHED_PROGRAMME})[:200],
            'pending_sites_count': len({r['raw_id'] for r in rows if r['category'] == rawcsv.UNMATCHED_PROGRAMME}),
            'rows': _page(rows, '', 1) if rows else None,
        })
    return data


def _page(rows: list[dict], status_filter: str, page: int) -> dict:
    if status_filter:
        rows = [r for r in rows if r['status'] == status_filter]
    pages = max(1, -(-len(rows) // ROW_PAGE))
    page = min(max(1, page), pages)
    return {'count': len(rows), 'page': page, 'pages': pages, 'rows': rows[(page - 1) * ROW_PAGE: page * ROW_PAGE]}


def _batch(request, batch_id: int) -> UploadBatch:
    batch = UploadBatch.objects.select_related('uploaded_by').filter(pk=batch_id, kind__in=arrivals.RAW_KINDS).first()
    if batch is None or not (_is_admin(request) or batch.uploaded_by_id == request.user.pk) or not may_use(request.user, batch.technology, batch.circle):
        raise NotFound('No such upload.')
    return batch


def _alert(request, batch_id, name: str, reason: str, project: str, circle: str, day, status_label: str = 'Failed') -> None:
    """Upload Failure Alert (Administration › Alert): queued for the worker, never affects the upload's own answer."""
    from apps.alerts.events import upload_failed
    upload_failed(kind='raw_csv', batch_id=batch_id, file=name, reason=reason, uploader_id=request.user.pk, project=project,
                  circle=circle, date=day.isoformat() if day else '', status=status_label)


@api_view(['GET'])
@permission_classes([Can(*UPLOAD)])
def raw_options(request):
    """What the form may offer this user: the active projects (technologies with a raw CSV import), and per project its
    active circles within the user's scope with their site-master size."""
    allowed = allowed_pairs(request.user)
    sites = dict(((t, c), n) for t, c, n in Site.objects.filter(reporting_scope=Site.Scope.DASHBOARD).order_by()
                 .values_list('technology', 'circle').annotate(n=Count('id')))
    pairs = organization.associations(active_only=True)
    lwe_mapping = SiteIdentifier.objects.filter(kind__in=(SiteIdentifier.Kind.BAND_2100, SiteIdentifier.Kind.BAND_700)).exists()
    projects = []
    for p in organization.project_keys(active_only=True):
        if p not in rawcsv.KINDS:
            continue
        circles = [c for proj, c in pairs if proj == p and (allowed is None or (p, c) in allowed)]
        projects.append({'value': p, 'configured': p != Technology.LWE or lwe_mapping, 'availability_column': rules.AVAILABILITY_COLUMN,
                         'circles': circles, 'site_counts': {c: sites.get((p, c), 0) for c in circles}})
    return Response({
        'projects': projects,
        'assigned_circles': None if allowed is None else sorted({c for _, c in allowed}),
        'access': None if allowed is None else [{'project': p, 'circle': c} for p, c in sorted(allowed)],
        'max_bytes': settings.MAX_UPLOAD_BYTES,
        'formula': 'outage minutes = 1440 × (1 − availability / 100)',
    })


@api_view(['GET'])
@permission_classes([Can(*UPLOAD)])
def raw_list(request):
    qs = UploadBatch.objects.select_related('uploaded_by').filter(kind__in=arrivals.RAW_KINDS).order_by('-uploaded_at')
    if not _is_admin(request):
        qs = qs.filter(uploaded_by=request.user)
    allowed = allowed_pairs(request.user)
    batches = [b for b in qs[:300] if allowed is None or (b.technology, b.circle) in allowed][:100]
    return Response({'uploads': [_batch_json(b) for b in batches]})


def _details(request):
    data = request.data
    errors = {}
    project = str(data.get('project') or '')
    if project not in organization.project_keys(active_only=True):
        errors['project'] = 'Choose an active project.'
    elif project not in rawcsv.KINDS:
        errors['project'] = f'Raw daily uploads are not available for {project}.'
    circle = str(data.get('circle') or '').strip().upper()
    if not circle:
        errors['circle'] = 'Choose a circle.'
    elif 'project' not in errors and not organization.is_associated(project, circle):
        errors['circle'] = f'{circle} is not an active circle of {project} (Administration > Organization).'
    day = cnmc_csv.parse_date(str(data.get('reporting_date') or ''))
    if day is None:
        errors['reporting_date'] = 'Enter the reporting date.'
    elif day > timezone.localdate():
        errors['reporting_date'] = 'The reporting date cannot be in the future.'
    if errors:
        raise ValidationError(errors)
    if not may_use(request.user, project, circle):
        raise PermissionDenied(f'You are not assigned to {circle} under {project}. Ask an Admin to grant it to your account.')
    return project, circle, day, str(data.get('remarks') or '').strip()[:2000]


@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser])
@permission_classes([Can(*UPLOAD)])
def raw_preview(request):
    """Validate a raw daily CSV against the site master. Writes only the upload record and its staged copy."""
    project, circle, day, remarks = _details(request)
    upload = request.FILES.get('file')
    if upload is None:
        raise ValidationError({'file': 'Choose the raw daily CSV file.'})
    name = Path(upload.name).name
    if Path(name).suffix.lower() != '.csv':
        raise ValidationError({'file': f'{name}: choose the CSV file exported from CNMC (.csv).'})
    if upload.size > settings.MAX_UPLOAD_BYTES:
        raise ValidationError({'file': f'{name} is larger than {settings.MAX_UPLOAD_BYTES // (1024 * 1024)} MB.'})
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'upload.csv'
        with open(path, 'wb') as handle:
            for chunk in upload.chunks():
                handle.write(chunk)
        batch = rawcsv.preview(path, name, technology=project, circle=circle, reporting_date=day, user=request.user)
    if remarks:
        batch.remarks = remarks
        batch.save(update_fields=['remarks'])
    audit('raw_upload_previewed', request, batch=batch.pk, file=name, circle=circle, project=project, status=batch.validation_status)
    if batch.validation_status == UploadBatch.Validation.FAILED:
        _alert(request, batch.pk, name, batch.error or 'The file did not pass validation.', project, circle, day, 'Rejected')
        if batch.error:  # the file itself could not be read: nothing to preview
            return Response({'error': batch.error, 'details': {'upload': batch.pk}}, status=status.HTTP_400_BAD_REQUEST)
    return Response(_batch_json(batch, full=True), status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([Can(*UPLOAD)])
def raw_detail(request, batch_id: int):
    return Response(_batch_json(_batch(request, batch_id), full=True))


@api_view(['GET'])
@permission_classes([Can(*UPLOAD)])
def raw_rows(request, batch_id: int):
    try:
        page = int(request.query_params.get('page') or 1)
    except ValueError as exc:
        raise ValidationError({'page': 'Enter a page number.'}) from exc
    rows = _rows(_batch(request, batch_id))
    category = request.query_params.get('category') or ''
    if category:  # matched / unmatched_programme / outside_programme / invalid (approved rule B-8)
        rows = [r for r in rows if r.get('category') == category]
    return Response(_page(rows, request.query_params.get('status') or '', page))


@api_view(['GET'])
@permission_classes([Can(*UPLOAD)])
def raw_issues_csv(request, batch_id: int):
    """Every row that is not imported, with its reason, plus a file-level problem."""
    batch = _batch(request, batch_id)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(['file', 'line', 'raw_bts_ip_id', 'master_site_id', 'circle', 'report_date', 'availability', 'outage_minutes',
                     'status', 'reason_code', 'reason'])
    if batch.error:
        writer.writerow([batch.original_filename, '', '', '', '', '', '', '', 'file', 'file', batch.error])
    for r in _rows(batch):
        if r['code'] == 'ready':
            continue
        writer.writerow([batch.original_filename, r['line'], r['raw_id'], r['site_id'] or '', r['circle'], r['report_date'], r['raw_availability'],
                         '' if r['outage_minutes'] is None else r['outage_minutes'], r['status'], r['code'], r['message'] or r['label']])
    response = HttpResponse('﻿' + out.getvalue(), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="raw-upload-{batch.pk}-validation.csv"'
    return response


@api_view(['POST'])
@parser_classes([JSONParser])
@permission_classes([Can(*UPLOAD)])
def raw_commit(request, batch_id: int):
    batch = _batch(request, batch_id)
    if request.data.get('confirm') is not True:
        raise ValidationError({'confirm': 'Confirm the import explicitly.'})
    try:
        batch = rawcsv.commit(batch, user=request.user, request=request)
    except uploads.UploadRejected as exc:
        _alert(request, batch.pk, batch.original_filename, str(exc), batch.technology, batch.circle, batch.reporting_date)
        return Response({'error': str(exc), 'details': {}}, status=status.HTTP_409_CONFLICT)
    except IntegrityError:
        message = (f'Upload #{batch.pk} could not be committed: a site-day was written by another import at the same time. '
                   'Preview the file again.')
        _alert(request, batch.pk, batch.original_filename, message, batch.technology, batch.circle, batch.reporting_date)
        return Response({'error': message, 'details': {}}, status=status.HTTP_409_CONFLICT)
    audit('raw_upload_committed', request, batch=batch.pk, circle=batch.circle, project=batch.technology, accepted=batch.records_accepted)
    return Response(_batch_json(batch, full=True))


@api_view(['POST'])
@permission_classes([Can(*UPLOAD)])
def raw_discard(request, batch_id: int):
    try:
        batch = uploads.discard(_batch(request, batch_id))
    except uploads.UploadRejected as exc:
        return Response({'error': str(exc), 'details': {}}, status=status.HTTP_409_CONFLICT)
    audit('raw_upload_discarded', request, batch=batch.pk)
    return Response(_batch_json(batch))


def _query_date(request, name: str):
    text = request.query_params.get(name, '').strip()
    if not text:
        return None
    day = cnmc_csv.parse_date(text)
    if day is None:
        raise ValidationError({name: 'Give the date as YYYY-MM-DD.'})
    return day


@api_view(['GET'])
@permission_classes([IsAdminRole])  # CSV arrival tracking is an Admin page
def arrival_tracker(request):
    """Per technology/circle for ?date=YYYY-MM-DD: stored daily-data coverage and raw CSV uploads, plus a daily range
    (?start=&end=, at most 92 days) for gaps. Read only; computed from the data layer on every request."""
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
    return Response(arrivals.tracker(day, None, start, end))
