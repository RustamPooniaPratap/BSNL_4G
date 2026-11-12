"""Up-Time Report import into the new data layer (/api/sitedata/uptime/): preview, review, confirm, discard, issue report.

The Up-Time Report goes into the central daily table every dashboard page reads (apps.sitedata.uptime_master).
daily.py prevents duplicate site/date/technology records and keeps source precedence and
authorized corrections. Writes only sitedata_dailysiteperformance, sitedata_dailyperformanceevent, the Uptime-only
columns of sitedata_site and the upload record; never RCA data. Admins only.
"""
import tempfile
from pathlib import Path

from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.accounts.audit import audit
from apps.accounts.permissions import IsAdminRole

from django.db import IntegrityError

from . import uploads, uptime_master
from .matrix_views import MAX_BYTES, _batch_json, _get, exception_csv_response
from .models import Technology, UploadBatch

KIND, LABEL = uptime_master.KIND, 'Up-Time Report'


def _uptime(batch_id: int) -> UploadBatch:
    return _get(batch_id, KIND, LABEL)


@api_view(['GET'])
@permission_classes([IsAdminRole])
def uptime_list(request):
    batches = UploadBatch.objects.filter(kind=KIND).select_related('uploaded_by').order_by('-uploaded_at')[:20]
    return Response({'imports': [{k: v for k, v in _batch_json(b).items() if k != 'report'} for b in batches]})


@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser])
@permission_classes([IsAdminRole])
def uptime_preview(request):
    """Validate an Up-Time Report against the new data layer. Writes only the upload record."""
    upload = request.FILES.get('file')
    if upload is None:
        raise ValidationError({'file': 'Choose the Up-Time Report workbook (.xlsx).'})
    if not upload.name.lower().endswith(('.xlsx', '.xlsm')):
        raise ValidationError({'file': 'The Up-Time Report must be an Excel workbook (.xlsx).'})
    if upload.size > MAX_BYTES:
        raise ValidationError({'file': f'The file is larger than {MAX_BYTES // (1024 * 1024)} MB.'})
    project = (request.data.get('project') or '').strip() or None
    if project is not None and project not in Technology.values:
        raise ValidationError({'project': 'Choose 4G Saturation or LWE, or leave it to the Project column.'})
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / Path(upload.name).name
        with open(path, 'wb') as handle:
            for chunk in upload.chunks():
                handle.write(chunk)
        batch = uptime_master.preview(path, Path(upload.name).name, project=project, user=request.user)
    audit('sitedata.uptime_previewed', request, batch=batch.pk, file=batch.original_filename, status=batch.validation_status)
    body = _batch_json(batch)
    if batch.validation_status == UploadBatch.Validation.FAILED:
        return Response(body, status=status.HTTP_400_BAD_REQUEST)
    return Response(body, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([IsAdminRole])
def uptime_detail(request, batch_id: int):
    return Response(_batch_json(_uptime(batch_id)))


@api_view(['POST'])
@parser_classes([JSONParser])
@permission_classes([IsAdminRole])
def uptime_commit(request, batch_id: int):
    """Import a previewed Up-Time Report after explicit confirmation (``confirm: true``), in one transaction."""
    batch = _uptime(batch_id)
    if request.data.get('confirm') is not True:
        raise ValidationError({'confirm': 'Confirm the import after reviewing the preview.'})
    try:
        batch = uptime_master.commit(batch, user=request.user, request=request)
    except uploads.UploadRejected as exc:
        return Response({'error': str(exc), 'details': {}}, status=status.HTTP_409_CONFLICT)
    except IntegrityError:
        return Response({'error': f'Upload #{batch.pk} could not be committed: a site-day would be stored twice (written by another '
                                  'import at the same time). Preview the file again.', 'details': {}}, status=status.HTTP_409_CONFLICT)
    from . import portfolio
    portfolio.clear_cache()  # the dashboard pages read the new values on their next request
    return Response(_batch_json(batch))


@api_view(['POST'])
@permission_classes([IsAdminRole])
def uptime_discard(request, batch_id: int):
    batch = _uptime(batch_id)
    if batch.processing_status != UploadBatch.Processing.PREVIEWED:
        return Response({'error': 'Only a previewed upload can be discarded.', 'details': {}}, status=409)
    batch.processing_status = UploadBatch.Processing.DISCARDED
    batch.save(update_fields=['processing_status'])
    audit('sitedata.uptime_discarded', request, batch=batch.pk)
    return Response(_batch_json(batch))


@api_view(['GET'])
@permission_classes([IsAdminRole])
def uptime_issues_csv(request, batch_id: int):
    """Every rejected row, unmatched site and conflict of the preview (the exception report), as CSV (410 when the
    recorded report file is missing on this server)."""
    batch = _uptime(batch_id)
    return exception_csv_response(batch, f'uptime-{batch.pk}-issues.csv')


# --- Sites of Up-Time Reports that are not in the site master (apps/sitedata/unmatched.py) ---------------------------

@api_view(['GET'])
@permission_classes([IsAdminRole])
def unmatched_report(request):
    """Data quality: every unmatched site with its project, circle, dates, pending site-days, reason and status."""
    from . import unmatched
    return Response(unmatched.report())


@api_view(['POST'])
@permission_classes([IsAdminRole])
def unmatched_refresh(request):
    """Record the per-site detail of uploads committed before it was stored (re-reads their staged copies)."""
    from . import unmatched
    try:
        updated = unmatched.refresh_details(user=request.user, request=request)
    except uploads.UploadRejected as exc:
        return Response({'error': str(exc), 'details': {}}, status=status.HTTP_409_CONFLICT)
    return Response({'uploads_updated': updated, **unmatched.report()})


@api_view(['POST'])
@parser_classes([JSONParser])
@permission_classes([IsAdminRole])
def unmatched_map(request):
    """Approve an alternate identifier for an existing master site: ``identifier``, ``site_id`` (BSNL Site ID), ``reason``."""
    from . import unmatched
    from .identifiers import key_of
    from .models import Site
    site = Site.objects.filter(site_key=key_of(str(request.data.get('site_id') or ''))).first()
    if site is None:
        raise ValidationError({'site_id': 'No master site with this BSNL Site ID.'})
    try:
        identifier = unmatched.map_alternate(str(request.data.get('identifier') or ''), site, user=request.user,
                                             reason=str(request.data.get('reason') or ''), request=request)
    except unmatched.ResolutionRejected as exc:
        return Response({'error': str(exc), 'details': {}}, status=status.HTTP_400_BAD_REQUEST)
    return Response({'identifier': identifier.value, 'site_id': site.bsnl_site_id, **unmatched.report()}, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@parser_classes([JSONParser])
@permission_classes([IsAdminRole])
def unmatched_process(request):
    """Import the pending values of sites that now resolve (``confirm: true``), under their original uploads."""
    from . import unmatched
    if request.data.get('confirm') is not True:
        raise ValidationError({'confirm': 'Confirm processing the pending records.'})
    try:
        result = unmatched.process_pending(user=request.user, request=request)
    except (unmatched.ResolutionRejected, uploads.UploadRejected) as exc:
        return Response({'error': str(exc), 'details': {}}, status=status.HTTP_409_CONFLICT)
    return Response({**result, **unmatched.report()})
