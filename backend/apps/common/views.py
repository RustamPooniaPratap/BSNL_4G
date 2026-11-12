import logging
import re
from datetime import datetime
from pathlib import Path

import pandas as pd
from django.conf import settings
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from apps.accounts.permissions import IsAdminRole

from . import email as mail

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = ('.csv', '.xlsx', '.xls')
PREVIEW_ROWS = 5

# Candidate column hints matching inspect_raw.py. They only suggest columns; nothing is mapped automatically.
ID_HINTS = ["site", "bts", "ip id", "id"]
AVAIL_HINTS = ["avail", "aval", "uptime", "up time"]
DATE_HINTS = ["date", "day", "month", "period", "time"]


def find_candidates(columns, hints):
    return [c for c in columns if any(h in str(c).lower() for h in hints)]


def get_raw_dir() -> Path:
    """Return the directory that stores uploaded raw files."""
    raw_dir = Path(settings.RAW_UPLOAD_DIR)
    raw_dir.mkdir(parents=True, exist_ok=True)
    return raw_dir


def _safe_filename(name: str) -> str:
    stem, suffix = Path(Path(name).name).stem, Path(name).suffix.lower()
    stem = re.sub(r'[^A-Za-z0-9 ._()\'-]+', '_', stem).strip(' .') or 'upload'
    return f'{stem[:120]}{suffix}'


def _unique_destination(directory: Path, filename: str) -> Path:
    """Never overwrite an existing raw file; add a timestamp suffix instead."""
    destination = directory / filename
    if not destination.exists():
        return destination
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    stem, suffix = Path(filename).stem, Path(filename).suffix
    candidate = directory / f'{stem}_{stamp}{suffix}'
    counter = 1
    while candidate.exists():
        candidate = directory / f'{stem}_{stamp}_{counter}{suffix}'
        counter += 1
    return candidate


@api_view(['GET'])
@permission_classes([AllowAny])  # liveness only: no data
def health_check(request):
    """
    Basic health check endpoint confirming DRF and backend availability.
    """
    return Response({
        'status': 'healthy',
        'service': '4G Saturation & LWE Portal API',
        'version': '0.1.0'
    })


@api_view(['GET'])
@permission_classes([IsAdminRole])  # used by CSV arrival tracking (Admins only)
def list_raw_files(request):
    """
    List all uploaded raw data files (CSV, Excel) in Data/raw.
    """
    raw_dir = get_raw_dir()
    files = []
    for f in sorted(raw_dir.glob('*')):
        if f.is_file() and not f.name.startswith('.') and not f.name.startswith('~$'):
            stat = f.stat()
            files.append({
                'name': f.name,
                'size_bytes': stat.st_size,
                'modified_at': datetime.fromtimestamp(stat.st_mtime).isoformat(timespec='seconds'),
                'extension': f.suffix.lower(),
            })

    return Response({
        'count': len(files),
        'files': files
    })


@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser])
@permission_classes([IsAdminRole])
def upload_file(request):
    """
    Store an uploaded CSV / Excel file in Data/raw and return a read-only preview.

    Uploading does not change the dashboard: the dashboard reads only the Master workbook.
    """
    file_obj = request.FILES.get('file')
    if not file_obj:
        return Response(
            {'error': 'No file was provided in the request (expected form field "file").', 'details': {}},
            status=status.HTTP_400_BAD_REQUEST
        )

    filename = _safe_filename(file_obj.name)
    ext = Path(filename).suffix
    if ext not in ALLOWED_EXTENSIONS:
        return Response(
            {'error': f'Unsupported file extension "{ext}". Allowed formats are .csv, .xlsx, .xls.', 'details': {}},
            status=status.HTTP_400_BAD_REQUEST
        )
    if file_obj.size > settings.MAX_UPLOAD_BYTES:
        limit_mb = settings.MAX_UPLOAD_BYTES // (1024 * 1024)
        return Response(
            {'error': f'The file is larger than the {limit_mb} MB upload limit.', 'details': {}},
            status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
        )

    dest_path = _unique_destination(get_raw_dir(), filename)
    try:
        with open(dest_path, 'xb') as destination:
            for chunk in file_obj.chunks():
                destination.write(chunk)
    except OSError:
        logger.exception('Failed to store uploaded file %s', dest_path.name)
        return Response(
            {'error': 'The file could not be saved on the server.', 'details': {}},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    try:
        if ext == '.csv':
            # dtype=str keeps IDs such as 00123 intact.
            df = pd.read_csv(dest_path, dtype=str, keep_default_na=False)
        else:
            df = pd.read_excel(dest_path, dtype=str)
    except Exception:
        logger.warning('Uploaded file %s was saved but could not be parsed', dest_path.name, exc_info=True)
        return Response({
            'status': 'partial_success',
            'warning': 'The file was saved, but its contents could not be read as a table. '
                       'Check that it is a valid CSV or Excel file.',
            'filename': dest_path.name,
            'size_bytes': dest_path.stat().st_size,
        }, status=status.HTTP_200_OK)

    columns = [str(c) for c in df.columns]
    return Response({
        'status': 'success',
        'message': f'File "{dest_path.name}" uploaded and inspected. It has not been applied to the dashboard.',
        'filename': dest_path.name,
        'size_bytes': dest_path.stat().st_size,
        'row_count': len(df),
        'column_count': len(columns),
        'columns': columns,
        'preview': df.head(PREVIEW_ROWS).to_dict(orient='records'),
        'candidate_columns': {
            'site_id': find_candidates(columns, ID_HINTS),
            'availability': find_candidates(columns, AVAIL_HINTS),
            'date': find_candidates(columns, DATE_HINTS),
        }
    }, status=status.HTTP_201_CREATED)


# --- Email (CSV arrival reminders and personal emails) ---------------------------------------

def _email_error(exc: 'mail.EmailRejected') -> Response:
    return Response({'error': str(exc), 'details': exc.details}, status=exc.status)


def _reminder(data) -> 'mail.Reminder':
    """Validate a reminder's circle, report type and date against the data layer's site master."""
    from apps.sitedata.models import Site

    errors = {}
    circle = data.get('circle') if isinstance(data.get('circle'), str) else ''
    report_type = data.get('report_type') if isinstance(data.get('report_type'), str) else ''
    try:
        reporting_date = datetime.strptime(str(data.get('reporting_date', '')), '%Y-%m-%d').date()
    except ValueError:
        reporting_date = None
        errors['reporting_date'] = ['Enter the reporting date as YYYY-MM-DD.']
    deadline = None
    if data.get('deadline'):
        try:
            deadline = datetime.fromisoformat(str(data['deadline'])).strftime('%d %b %Y, %H:%M')
        except ValueError:
            errors['deadline'] = ['Enter the deadline as YYYY-MM-DDTHH:MM.']
    if not circle or not report_type:
        errors['circle'] = ['Choose the circle and report type.']
    elif not Site.objects.filter(reporting_scope=Site.Scope.DASHBOARD, technology=report_type, circle=circle).exists():
        errors['circle'] = [f'{circle} has no {report_type} sites in the site master.']
    if errors:
        raise mail.EmailRejected('Invalid reminder.', errors)
    return mail.Reminder(circle=circle, report_type=report_type, reporting_date=reporting_date, deadline=deadline)


@api_view(['GET'])
@permission_classes([IsAdminRole])  # email belongs to CSV arrival tracking
def email_status(request):
    """Whether email is in test mode (printed in the backend terminal) or live."""
    return Response(mail.status())


@api_view(['GET'])
@permission_classes([IsAdminRole])  # email belongs to CSV arrival tracking
def reminder_template(request):
    """The standard reminder's subject and body for a circle, report type and reporting date."""
    try:
        subject, body = mail.reminder_content(_reminder(request.query_params))
    except mail.EmailRejected as exc:
        return _email_error(exc)
    return Response({'subject': subject, 'body': body, **mail.status()})


@api_view(['POST'])
@permission_classes([IsAdminRole])  # email belongs to CSV arrival tracking
def send_reminder(request):
    """Send the standard reminder now. The text is built here, never taken from the browser."""
    try:
        reminder = _reminder(request.data)
        to = mail.clean_addresses(request.data.get('to'), 'to', required=True)
        cc = mail.clean_addresses(request.data.get('cc'), 'cc', required=False)
        subject, body = mail.reminder_content(reminder)
        event = f'reminder|{reminder.report_type}|{reminder.circle}|{reminder.reporting_date}|{",".join(sorted(to))}'
        result = mail.send_email(to=to, cc=cc, subject=subject, body=body, kind='reminder', event_key=event)
    except mail.EmailRejected as exc:
        return _email_error(exc)
    except mail.EmailFailed as exc:
        return Response({'error': str(exc), 'details': {'code': 'send_failed'}}, status=status.HTTP_502_BAD_GATEWAY)
    return Response(result, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAdminRole])  # email belongs to CSV arrival tracking
def send_personal_email(request):
    """Send an email written (or edited) by the user, after validating every field."""
    try:
        to = mail.clean_addresses(request.data.get('to'), 'to', required=True)
        cc = mail.clean_addresses(request.data.get('cc'), 'cc', required=False)
        subject, body = mail.clean_text(request.data.get('subject'), request.data.get('body'))
        result = mail.send_email(to=to, cc=cc, subject=subject, body=body, kind='personal')
    except mail.EmailRejected as exc:
        return _email_error(exc)
    except mail.EmailFailed as exc:
        return Response({'error': str(exc), 'details': {'code': 'send_failed'}}, status=status.HTTP_502_BAD_GATEWAY)
    return Response(result, status=status.HTTP_200_OK)
