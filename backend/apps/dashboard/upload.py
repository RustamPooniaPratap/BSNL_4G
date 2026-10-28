"""Validate an uploaded Master workbook and, only if it passes, make it the active dataset.

Order of checks: file type and size, safe .xlsx container, full sheet parse and
validation (workbook.parse_sheet), reported data present. The upload is staged
in a temporary file; on any failure the staged file is deleted and the
previously active workbook keeps serving the dashboard.
"""
from __future__ import annotations

import hashlib
import logging
import threading
import zipfile
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from django.conf import settings

from . import store
from .workbook import Dataset, WorkbookError, load_dataset, prime_cache

logger = logging.getLogger(__name__)

MAX_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024  # zip-bomb guard: 1 GB expanded
_upload_lock = threading.Lock()


class UploadRejected(Exception):
    def __init__(self, message: str, problems: list[str] | None = None, status: int = 422):
        super().__init__(message)
        self.problems = problems or []
        self.status = status


def accept_upload(uploaded_file) -> tuple[Dataset, dict]:
    """Validate ``uploaded_file`` (a Django UploadedFile) and activate it. Raises UploadRejected."""
    original_name = Path(uploaded_file.name or 'workbook.xlsx').name
    suffix = Path(original_name).suffix.lower()
    if suffix != '.xlsx':
        hint = ' Macro-enabled workbooks (.xlsm) are not accepted.' if suffix == '.xlsm' else ''
        raise UploadRejected(f'Upload the Master workbook as an Excel .xlsx file.{hint}', status=400)
    if uploaded_file.size > settings.MAX_WORKBOOK_BYTES:
        limit = settings.MAX_WORKBOOK_BYTES // (1024 * 1024)
        raise UploadRejected(f'The workbook is larger than the {limit} MB limit.', status=413)
    if uploaded_file.size == 0:
        raise UploadRejected('The uploaded file is empty.', status=400)

    with _upload_lock:
        staged = store.incoming_path()
        try:
            digest = hashlib.sha256()
            with open(staged, 'xb') as destination:
                for chunk in uploaded_file.chunks():
                    digest.update(chunk)
                    destination.write(chunk)
            _check_container(staged)
            try:
                dataset = load_dataset(staged, display_name=original_name)
            except WorkbookError as exc:
                raise UploadRejected('The workbook does not have the expected structure.', [str(exc)]) from exc
            if not dataset.reported_dates:
                raise UploadRejected('The workbook contains no daily outage values for any date.',
                                     ['Every daily outage column in Up-Time Report is blank.'])

            record = store.activate(staged, original_name=original_name, sha256=digest.hexdigest())
        except BaseException:
            staged.unlink(missing_ok=True)
            raise

        # Re-stamp with the stored file's identity so the cache key matches later requests.
        dataset = replace(dataset, uploaded_at=datetime.fromisoformat(record['uploaded_at']))
        prime_cache(record['path'], dataset)
        logger.info('Activated Master workbook %s (%s)', original_name, record['stored_name'])
        return dataset, record


def _check_container(path: Path) -> None:
    """Confirm the file is a genuine, reasonably sized .xlsx package without macros."""
    if not zipfile.is_zipfile(path):
        raise UploadRejected('The file is not a valid Excel .xlsx workbook.',
                             ['The file content is not an Office Open XML package (it may be renamed or corrupted).'])
    try:
        with zipfile.ZipFile(path) as package:
            names = set(package.namelist())
            expanded = sum(info.file_size for info in package.infolist())
    except zipfile.BadZipFile as exc:
        raise UploadRejected('The file is not a valid Excel .xlsx workbook.', ['The package could not be opened.']) from exc
    if 'xl/workbook.xml' not in names:
        raise UploadRejected('The file is not an Excel workbook.', ['The package has no xl/workbook.xml part.'])
    if any(name.lower().endswith('vbaproject.bin') for name in names):
        raise UploadRejected('Workbooks containing macros are not accepted.',
                             ['Save the workbook as a macro-free .xlsx file and upload it again.'], status=400)
    if expanded > MAX_UNCOMPRESSED_BYTES:
        raise UploadRejected('The workbook expands to an unreasonable size and was rejected.', status=400)
