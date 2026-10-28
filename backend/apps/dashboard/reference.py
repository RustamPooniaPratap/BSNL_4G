"""O&M Head per circle, read from the "first page" reference sheet in Data/reference.

The Master workbook has no O&M Head column. The reference sheet ("BSNL 4G - first page.xlsx",
Sheet1) lists Circle, Client and O&M Head per circle and network. Its circle codes differ from
the workbook's (RAJ for RJ, BR for BH, ...), so they are mapped. "-" or blank means no name is
given, and is returned as None, never guessed. The file is re-read when it changes.
"""
from __future__ import annotations

import threading
from pathlib import Path

from django.conf import settings
from openpyxl import load_workbook

FILE_PATTERN = '*first page*.xlsx'
CIRCLE_CODES = {'RAJ': 'RJ', 'BR': 'BH', 'JKD': 'JH', 'MAH': 'MH', 'TGN': 'TL'}
CLIENTS = {'4g sat': '4G Saturation', '4g saturation': '4G Saturation', '4g': '4G Saturation', 'lwe': 'LWE'}
BLANK = {'', '-', '--', 'na', 'n/a'}

_lock = threading.Lock()
_cache: dict = {'key': None, 'value': None}


def reference_file() -> Path | None:
    folder = Path(settings.DATA_DIR) / 'reference'
    files = [p for p in folder.glob(FILE_PATTERN) if not p.name.startswith('~$')] if folder.is_dir() else []
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def om_heads() -> dict:
    path = reference_file()
    if path is None:
        return {'source': None, 'heads': [], 'message': f'No reference sheet matching "{FILE_PATTERN}" in Data/reference.'}
    key = (str(path), path.stat().st_mtime_ns)
    with _lock:
        if _cache['key'] != key:
            _cache.update(key=key, value=_read(path))
        return _cache['value']


def _read(path: Path) -> dict:
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        rows = list(book.worksheets[0].iter_rows(values_only=True))
    finally:
        book.close()  # read-only mode keeps the file open; Windows would then block replacing it
    header_row = next((i for i, r in enumerate(rows) if r and 'O&M Head' in [str(v).strip() if v else '' for v in r]), None)
    if header_row is None:
        return {'source': path.name, 'heads': [], 'message': 'The reference sheet has no "O&M Head" column.'}
    headers = [str(v).strip() if v else '' for v in rows[header_row]]
    col = {name: headers.index(name) for name in ('Circle', 'Client', 'O&M Head') if name in headers}
    heads = []
    for row in rows[header_row + 1:]:
        circle = str(row[col['Circle']] or '').strip() if 'Circle' in col else ''
        client = str(row[col['Client']] or '').strip().casefold() if 'Client' in col else ''
        if not circle or client not in CLIENTS:
            continue  # blank, subtotal or note rows
        name = str(row[col['O&M Head']] or '').strip()
        heads.append({'report_type': CLIENTS[client], 'circle': CIRCLE_CODES.get(circle, circle), 'circle_in_sheet': circle,
                      'om_head': None if name.casefold() in BLANK else name})
    return {'source': path.name, 'heads': heads, 'message': None}
