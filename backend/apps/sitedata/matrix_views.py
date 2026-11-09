"""Consolidation Matrix import API (/api/sitedata/matrix/): preview, review, confirm, discard and the rejected-row report.

The Data Source page's "Import a workbook into PostgreSQL" offers two workbook types; this is the Consolidation Matrix
pipeline (apps.sitedata.matrix), independent of the Up-Time Report importer (apps.uptimedb, /api/imports/). It writes
only the new data layer's site master (sitedata_site, sitedata_siteidentifier, sitedata_identifierconflict) and the
upload history; never performance records, legacy uptimedb tables or RCA data. Admins only, as the other imports.
"""
import csv
import io
import tempfile
from pathlib import Path

from django.http import HttpResponse
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.accounts.audit import audit
from apps.accounts.permissions import IsAdminRole

from . import exceptions, matrix, uploads
from .models import UploadBatch

MAX_BYTES = 50 * 1024 * 1024


def _batch_json(batch: UploadBatch) -> dict:
    report = batch.report or {}
    return {
        'id': batch.pk, 'kind': batch.kind, 'technology': batch.technology or None, 'file': batch.original_filename, 'checksum': batch.checksum_sha256,
        'status': batch.processing_status, 'validation_status': batch.validation_status,
        'uploaded_at': batch.uploaded_at.isoformat() if batch.uploaded_at else None,
        'committed_at': batch.committed_at.isoformat() if batch.committed_at else None,
        'uploaded_by': batch.uploaded_by.username if batch.uploaded_by else None,
        'error': batch.error or report.get('error') or None,
        'counts': {name: getattr(batch, f'records_{name}') for name in uploads.COUNT_FIELDS},
        'report': {k: v for k, v in report.items() if k not in ('exception_report',)},
        'can_commit': batch.processing_status == UploadBatch.Processing.PREVIEWED and batch.validation_status != UploadBatch.Validation.FAILED,
    }


def _get(batch_id: int, kind: str = matrix.KIND, label: str = 'Consolidation Matrix') -> UploadBatch:
    batch = UploadBatch.objects.filter(pk=batch_id, kind=kind).select_related('uploaded_by').first()
    if batch is None:
        raise NotFound(f'No {label} upload with this id.')
    return batch


@api_view(['GET'])
@permission_classes([IsAdminRole])
def matrix_list(request):
    batches = UploadBatch.objects.filter(kind=matrix.KIND).select_related('uploaded_by').order_by('-uploaded_at')[:20]
    return Response({'imports': [{k: v for k, v in _batch_json(b).items() if k != 'report'} for b in batches]})


@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser])
@permission_classes([IsAdminRole])
def matrix_preview(request):
    """Validate a Consolidation Matrix against the site master. Writes only the upload record (nothing else)."""
    upload = request.FILES.get('file')
    if upload is None:
        raise ValidationError({'file': 'Choose the Consolidated Escalation Matrix workbook (.xlsx).'})
    if not upload.name.lower().endswith(('.xlsx', '.xlsm')):
        raise ValidationError({'file': 'The Consolidation Matrix must be an Excel workbook (.xlsx).'})
    if upload.size > MAX_BYTES:
        raise ValidationError({'file': f'The file is larger than {MAX_BYTES // (1024 * 1024)} MB.'})
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / Path(upload.name).name
        with open(path, 'wb') as handle:
            for chunk in upload.chunks():
                handle.write(chunk)
        batch = matrix.preview(path, Path(upload.name).name, user=request.user)
    audit('sitedata.matrix_previewed', request, batch=batch.pk, file=batch.original_filename, status=batch.validation_status)
    body = _batch_json(batch)
    if batch.validation_status == UploadBatch.Validation.FAILED:
        return Response({**body, 'error': body['error']}, status=status.HTTP_400_BAD_REQUEST)
    return Response(body, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([IsAdminRole])
def matrix_detail(request, batch_id: int):
    return Response(_batch_json(_get(batch_id)))


@api_view(['POST'])
@parser_classes([JSONParser])
@permission_classes([IsAdminRole])
def matrix_commit(request, batch_id: int):
    """Import a previewed matrix after explicit confirmation (``confirm: true``), in one transaction."""
    batch = _get(batch_id)
    if request.data.get('confirm') is not True:
        raise ValidationError({'confirm': 'Confirm the import after reviewing the preview.'})
    try:
        batch = matrix.commit(batch, user=request.user, request=request)
    except uploads.UploadRejected as exc:
        return Response({'error': str(exc), 'details': {}}, status=status.HTTP_409_CONFLICT)
    from . import portfolio
    portfolio.clear_cache()  # the dashboard pages read the updated site master on their next request
    return Response(_batch_json(batch))


@api_view(['POST'])
@permission_classes([IsAdminRole])
def matrix_discard(request, batch_id: int):
    batch = _get(batch_id)
    if batch.processing_status != UploadBatch.Processing.PREVIEWED:
        return Response({'error': 'Only a previewed upload can be discarded.', 'details': {}}, status=409)
    batch.processing_status = UploadBatch.Processing.DISCARDED
    batch.save(update_fields=['processing_status'])
    audit('sitedata.matrix_discarded', request, batch=batch.pk)
    return Response(_batch_json(batch))


@api_view(['GET'])
@permission_classes([IsAdminRole])
def matrix_issues_csv(request, batch_id: int):
    """Every rejected row, conflict and review item of the preview (the exception report), as CSV."""
    batch = _get(batch_id)
    path = (batch.report or {}).get('exception_report')
    if path and Path(path).is_file():
        data = Path(path).read_bytes()
    else:
        out = io.StringIO()
        csv.writer(out).writerow(exceptions.COLUMNS)
        data = out.getvalue().encode('utf-8')
    response = HttpResponse(data, content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="matrix-{batch.pk}-issues.csv"'
    return response
