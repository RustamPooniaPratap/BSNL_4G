"""Storage for accepted Master workbook uploads.

Accepted uploads are copied into WORKBOOK_STORE_DIR under a generated name;
``active.json`` points at the one the dashboard uses. The pointer is replaced
atomically, so a failed or rejected upload never disturbs the active dataset.
The original uploaded file is never modified.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path

from django.conf import settings

ACTIVE_FILE = 'active.json'
KEEP_ACCEPTED = 5  # older inactive uploads beyond this are deleted


def store_dir() -> Path:
    directory = Path(settings.WORKBOOK_STORE_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def incoming_path() -> Path:
    """Staging path for an upload that has not been validated yet."""
    return store_dir() / f'.incoming-{uuid.uuid4().hex}.xlsx'


def active_record() -> dict | None:
    """The active workbook record, or None if nothing valid has been uploaded."""
    pointer = Path(settings.WORKBOOK_STORE_DIR) / ACTIVE_FILE
    try:
        record = json.loads(pointer.read_text(encoding='utf-8'))
    except (FileNotFoundError, ValueError):
        return None
    path = Path(settings.WORKBOOK_STORE_DIR) / record.get('stored_name', '')
    if not record.get('stored_name') or not path.is_file():
        return None
    return {**record, 'path': path}


def activate(staged: Path, *, original_name: str, sha256: str) -> dict:
    """Move a validated staging file into the store and point ``active.json`` at it."""
    uploaded_at = datetime.now()
    stored_name = f'{uploaded_at:%Y%m%d-%H%M%S}-{sha256[:10]}.xlsx'
    destination = store_dir() / stored_name
    os.replace(staged, destination)
    record = {
        'stored_name': stored_name,
        'original_name': original_name,
        'uploaded_at': uploaded_at.isoformat(timespec='seconds'),
        'sha256': sha256,
        'size_bytes': destination.stat().st_size,
    }
    pointer = store_dir() / ACTIVE_FILE
    temporary = pointer.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(record, indent=2), encoding='utf-8')
    os.replace(temporary, pointer)
    _prune(keep=stored_name)
    return {**record, 'path': destination}


def _prune(keep: str) -> None:
    accepted = sorted((p for p in store_dir().glob('*.xlsx') if not p.name.startswith('.')), reverse=True)
    for old in accepted[KEEP_ACCEPTED:]:
        if old.name != keep:
            old.unlink(missing_ok=True)
