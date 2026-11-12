"""Upload history: staging a copy of each file, checksums, and the preview / commit life cycle of an UploadBatch.

Every importer works in two steps. preview() stages a copy (the original is never modified), analyses it against the
database and stores the report; nothing is written to the site or performance tables. commit() re-reads the staged
copy (checksum verified), repeats the analysis, refuses when the result differs from the preview, then writes in one
transaction.
"""
from __future__ import annotations

import hashlib
import shutil
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path, PureWindowsPath

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from .models import UploadBatch

COUNT_FIELDS = ('received', 'accepted', 'rejected', 'duplicate', 'unmatched', 'conflict', 'superseded')
# PostgreSQL advisory lock that serialises every write of the data layer (imports, pending processing, corrections), so
# two commits can never classify against the same stored values and both write (double click, retry, two users).
WRITE_LOCK = 4202611


class UploadRejected(Exception):
    """The file cannot be imported (wrong format, wrong scope, blocked rule)."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def staging_dir() -> Path:
    path = Path(getattr(settings, 'SITEDATA_STAGING_DIR', '') or Path(settings.DATA_DIR) / 'processed' / 'sitedata')
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_stored(stored: str, root: Path) -> Path | None:
    """Where a stored file reference points on this server (None when there is no reference).

    New references are relative to their root (the staging or exception directory), so the data directory can move
    between machines. Legacy references are absolute paths of the machine that wrote them: used as they are when the file
    exists there, otherwise the file is looked up by its name in the current root (a copied data directory). The caller
    checks that the result exists (and its checksum, for staged copies)."""
    if not stored:
        return None
    path = Path(stored)
    if not path.anchor and not PureWindowsPath(stored).anchor:  # relative: the current root
        return root / path
    if path.is_file():
        return path
    return root / PureWindowsPath(stored).name  # a Windows path keeps its file name on any platform


def staged_path(batch: UploadBatch) -> Path | None:
    """The staged copy's path on this server (not verified; see staged_file)."""
    return resolve_stored(batch.stored_path, staging_dir())


def new_batch(kind: str, source: Path, name: str, user=None, **fields) -> UploadBatch:
    """Stage a copy of the upload and create its batch (status: previewed, validation pending). The batch stores the
    copy's path relative to staging_dir()."""
    checksum = sha256(source)
    target = staging_dir() / f'{datetime.now():%Y%m%d-%H%M%S}-{kind}-{checksum[:10]}{Path(name).suffix.lower()}'
    shutil.copyfile(source, target)
    return UploadBatch.objects.create(kind=kind, original_filename=name, checksum_sha256=checksum, stored_path=target.name,
                                      uploaded_by=user if getattr(user, 'is_authenticated', False) else None, **fields)


def staged_file(batch: UploadBatch) -> Path:
    """The staged copy, verified against the checksum taken at upload."""
    path = staged_path(batch)
    if path is None or not path.is_file():
        raise UploadRejected(f'The staged copy of upload #{batch.pk} is missing; upload the file again.')
    if sha256(path) != batch.checksum_sha256:
        raise UploadRejected(f'The staged copy of upload #{batch.pk} changed since the preview; upload the file again.')
    return path


def require_previewed(batch: UploadBatch) -> None:
    if batch.processing_status != UploadBatch.Processing.PREVIEWED:
        raise UploadRejected(f'Upload #{batch.pk} is {batch.get_processing_status_display().lower()}; only a previewed upload can be committed.')
    if batch.validation_status == UploadBatch.Validation.FAILED:
        raise UploadRejected(f'Upload #{batch.pk} failed validation and cannot be committed.')


def write_lock() -> None:
    """Take the data-layer write lock for the current transaction (PostgreSQL; SQLite serialises writers itself)."""
    if connection.vendor == 'postgresql':
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(%s)', [WRITE_LOCK])


@contextmanager
def committing(batch: UploadBatch):
    """The commit transaction of a previewed upload: the write lock, the batch row locked and its status checked again
    inside the lock. Yields the locked batch; the caller analyses and writes within the block, so a second commit of the
    same upload waits and is then refused (already committed) instead of writing twice."""
    with transaction.atomic():
        write_lock()
        locked = UploadBatch.objects.select_for_update().get(pk=batch.pk)
        require_previewed(locked)
        yield locked


def refresh_after_daily_write(dates, request=None) -> None:
    """After daily records changed: recalculate the monthly results of the affected months (finalized months are left
    as they are; writes into them are refused anyway) and drop the cached dashboard datasets."""
    from . import calculations, portfolio
    for month in sorted({d.replace(day=1) for d in dates}):
        try:
            calculations.calculate_month(month, request=request)
        except calculations.MonthFinalized:
            pass
    portfolio.clear_cache()


def record_preview(batch: UploadBatch, counts: dict, report: dict, *, failed: bool = False, exception_items: list | None = None) -> UploadBatch:
    """Store the analysis of a preview: counts, report, validation status and the exception report (CSV + summary)."""
    from . import exceptions
    if exception_items is not None:
        report = {**report, 'exceptions': exceptions.summary(exception_items), 'exception_report': exceptions.write(batch, exception_items)}
    for name in COUNT_FIELDS:
        setattr(batch, f'records_{name}', counts.get(name, 0))
    warnings = report.get('warnings') or counts.get('rejected') or counts.get('unmatched') or counts.get('conflict')
    batch.validation_status = (UploadBatch.Validation.FAILED if failed else
                               UploadBatch.Validation.WARNINGS if warnings else UploadBatch.Validation.PASSED)
    batch.report = {**report, 'counts': counts}
    batch.save()
    return batch


def same_counts(batch: UploadBatch, counts: dict) -> bool:
    return all(getattr(batch, f'records_{name}') == counts.get(name, 0) for name in COUNT_FIELDS)


def mark_committed(batch: UploadBatch, report_update: dict | None = None) -> UploadBatch:
    batch.processing_status = UploadBatch.Processing.COMMITTED
    batch.committed_at = timezone.now()
    if report_update:
        batch.report = {**batch.report, **report_update}
    batch.save()
    return batch


def discard(batch: UploadBatch) -> UploadBatch:
    if batch.processing_status != UploadBatch.Processing.PREVIEWED:
        raise UploadRejected(f'Upload #{batch.pk} is {batch.get_processing_status_display().lower()}; only a preview can be discarded.')
    batch.processing_status = UploadBatch.Processing.DISCARDED
    batch.save(update_fields=['processing_status'])
    return batch


def examples(items, limit: int = 20) -> list:
    return list(items)[:limit]
