import csv
import io
import tempfile
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.accounts.audit import audit
from apps.accounts.permissions import IsAdminRole, IsPortalUser

from . import datasource, importer
from .models import DataImportBatch

ALLOWED = ('.xlsx', '.xlsm')


def _batch_json(batch: DataImportBatch, *, full: bool = False) -> dict:
    data = {
        'id': batch.pk, 'status': batch.status, 'file': batch.original_filename, 'checksum': batch.checksum_sha256,
        'sheet': batch.sheet_name, 'reconciliation_file': batch.reconciliation_filename or None,
        'conflict_source': batch.conflict_source or None, 'uploaded_at': batch.uploaded_at.isoformat(),
        'committed_at': batch.committed_at.isoformat() if batch.committed_at else None,
        'imported_by': batch.imported_by.get_username() if batch.imported_by else None, 'via': batch.initiated_via,
        'counts': batch.counts, 'rejected': batch.rejected_count, 'skipped': batch.skipped_count, 'error': batch.error or None,
    }
    if full:
        data['report'] = batch.report
    return data


def _get(batch_id: int) -> DataImportBatch:
    batch = DataImportBatch.objects.filter(pk=batch_id, kind=DataImportBatch.Kind.MASTER_WORKBOOK).first()
    if batch is None:
        raise NotFound('No such import.')
    return batch


def _saved(upload) -> Path:
    name = Path(upload.name).name
    if Path(name).suffix.lower() not in ALLOWED:
        raise ValidationError({'file': f'{name}: choose an Excel workbook (.xlsx).'})
    if upload.size > settings.MAX_WORKBOOK_BYTES:
        raise ValidationError({'file': f'{name} is larger than {settings.MAX_WORKBOOK_BYTES // (1024 * 1024)} MB.'})
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=Path(name).suffix.lower())
    for chunk in upload.chunks():
        handle.write(chunk)
    handle.close()
    return Path(handle.name)


@api_view(['GET'])
@permission_classes([IsAdminRole])
def import_list(request):
    return Response({'imports': [_batch_json(b) for b in DataImportBatch.objects.select_related('imported_by').filter(kind=DataImportBatch.Kind.MASTER_WORKBOOK)[:50]],
                     'database': datasource.completeness()})


@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser])
@permission_classes([IsAdminRole])
def import_preview(request):
    """Validate a workbook (and optionally the second report to compare with) without writing business data."""
    primary = request.FILES.get('file')
    if primary is None:
        raise ValidationError({'file': 'Choose the consolidated Master workbook (.xlsx).'})
    other = request.FILES.get('reconciliation_file')
    paths = [_saved(primary)] + ([_saved(other)] if other else [])
    try:
        batch = importer.preview(paths[0], Path(primary.name).name, user=request.user,
                                 reconciliation=paths[1] if other else None, reconciliation_name=Path(other.name).name if other else '',
                                 project=request.data.get('project') or None,
                                 daily_only=str(request.data.get('daily_only', '')).lower() in ('true', '1', 'yes'))
    except importer.ImportRejected as exc:
        return Response({'error': str(exc), 'details': {}}, status=exc.status)
    finally:
        for p in paths:
            p.unlink(missing_ok=True)
    return Response(_batch_json(batch, full=True), status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([IsAdminRole])
def import_detail(request, batch_id: int):
    return Response(_batch_json(_get(batch_id), full=True))


@api_view(['GET'])
@permission_classes([IsAdminRole])
def import_issues_csv(request, batch_id: int):
    """Every rejected or flagged row of the preview, as CSV."""
    batch = _get(batch_id)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(['file', 'severity', 'code', 'excel_row', 'site_id', 'message'])
    for role in ('primary', 'reconciliation'):
        part = batch.report.get(role) or {}
        for issue in part.get('all_issues', []):
            writer.writerow([part.get('filename'), issue['severity'], issue['code'], issue['row'], issue['site_id'], issue['message']])
    response = HttpResponse(out.getvalue(), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="import-{batch.pk}-issues.csv"'
    return response


@api_view(['POST'])
@parser_classes([JSONParser])
@permission_classes([IsAdminRole])
def import_commit(request, batch_id: int):
    batch = _get(batch_id)
    choice = request.data.get('conflict_source') or ''
    if choice and choice not in importer.CONFLICT_CHOICES:
        raise ValidationError({'conflict_source': 'Choose "primary" or "reconciliation".'})
    try:
        batch = importer.commit(batch, user=request.user, conflict_source=choice)
    except importer.ImportRejected as exc:
        return Response({'error': str(exc), 'details': {}}, status=exc.status)
    return Response({**_batch_json(batch, full=True), 'database': datasource.completeness()})


@api_view(['POST'])
@permission_classes([IsAdminRole])
def import_discard(request, batch_id: int):
    batch = _get(batch_id)
    if batch.status != DataImportBatch.Status.PREVIEWED:
        return Response({'error': 'Only a previewed import can be discarded.', 'details': {}}, status=409)
    batch.status = DataImportBatch.Status.DISCARDED
    batch.save(update_fields=['status'])
    audit('import_discarded', request, batch=batch.pk)
    return Response(_batch_json(batch))


@api_view(['GET', 'PUT'])
@parser_classes([JSONParser])
@permission_classes([IsPortalUser])
def data_source(request):
    """GET: the source every dashboard page uses (any signed-in user). PUT: switch it (Admins, explicit confirmation)."""
    if request.method == 'PUT':
        if not IsAdminRole().has_permission(request, None):
            return Response({'error': 'Only an Admin can change the dashboard data source.', 'details': {}}, status=403)
        source = request.data.get('source')
        if source not in datasource.SOURCES:
            raise ValidationError({'source': 'Choose "excel" or "database".'})
        if request.data.get('confirm') is not True:
            raise ValidationError({'confirm': 'Confirm the switch: it changes the source of every dashboard page for all users.'})
        state = datasource.completeness()
        if source == datasource.DATABASE:
            if state['empty']:
                return Response({'error': 'The database has no imported data, so it cannot power the dashboard.', 'details': {}}, status=409)
            if state['warnings'] and request.data.get('acknowledge_warnings') is not True:
                return Response({'error': 'The database data is incomplete. Acknowledge the warnings to switch anyway.',
                                 'details': {'warnings': state['warnings']}}, status=409)
        previous = datasource.active_source()
        datasource.set_active_source(source, request.user)
        audit('data_source_changed', request, previous=previous, source=source)
    active = datasource.active_source()
    return Response({'active': active, 'label': datasource.SOURCES[active],
                     'options': [{'value': k, 'label': v} for k, v in datasource.SOURCES.items()],
                     'database': datasource.completeness()})
