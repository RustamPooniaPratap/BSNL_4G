"""Read a raw CNMC daily availability dump (``nw_aval_btsipid_wise_day...csv``) into rows. No database access.

Observed format (one file per circle and day): a header with, among ~60 columns, ``BTS IP ID``, ``Circle``,
``Nw Avail (4G)``, ``Nw Avail (4G TCS)`` and ``Report Date`` (DD-MM-YYYY). Some exports put a summary or title
row above the header, so the header is found by its column names within the first rows, and the rows above it
are reported as a preamble, never read as data. The monthly variant of the dump (``MONTH`` and ``YEAR`` columns,
no ``Report Date``) is refused: it is a month summary, not a day's data.

Columns are matched by normalised header text (case, spaces and punctuation ignored), never by position. Every
value is kept as written with its file line number; nothing is converted here except the trimmed text.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

HEADER_SEARCH_ROWS = 10
ENCODINGS = ('utf-8-sig', 'cp1252')
DATE_FORMATS = ('%d-%m-%Y', '%d/%m/%Y', '%d.%m.%Y', '%Y-%m-%d', '%d-%b-%Y', '%d-%b-%y')


class RawParseError(ValueError):
    """The file is not a supported raw daily CSV."""


def norm(header: str) -> str:
    """Header key: lower case, letters and digits only ("Nw Avail (4G TCS)" -> "nwavail4gtcs")."""
    return re.sub(r'[^a-z0-9]', '', (header or '').lower())


# Field -> accepted header keys.
COLUMNS = {
    'site_id': ('btsipid',),
    'site_name': ('btsname',),
    'circle': ('circle',),
    'report_date': ('reportdate',),
    'avail_4g': ('nwavail4g',),
    'avail_4g_tcs': ('nwavail4gtcs',),
    'outage_raw': ('outagemin',),
    'band': ('bandcategory',),
    'site_type': ('sitetype',),
}
REQUIRED = ('site_id', 'circle', 'report_date')
LABELS = {'site_id': 'BTS IP ID', 'circle': 'Circle', 'report_date': 'Report Date'}


@dataclass
class RawRow:
    line: int  # 1-based line in the file
    values: dict[str, str]


@dataclass
class ParsedRaw:
    encoding: str
    header_line: int
    headers: list[str]
    columns: dict[str, str]  # field -> header as written
    rows: list[RawRow]
    preamble: list[str] = field(default_factory=list)
    blank_lines: int = 0
    malformed: list[dict] = field(default_factory=list)  # {'line', 'cells', 'expected'}
    unknown_headers: list[str] = field(default_factory=list)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def parse_date(value: str) -> date | None:
    text = (value or '').strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _decode(data: bytes) -> tuple[str, str]:
    if b'\x00' in data[:4096]:
        raise RawParseError('The file is not a text CSV (it contains binary data). Upload the CSV exported from CNMC.')
    for encoding in ENCODINGS:
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise RawParseError('The file is not readable as UTF-8 or Windows text.')


def parse(path: Path, *, max_bytes: int | None = None) -> ParsedRaw:
    data = Path(path).read_bytes()
    if max_bytes is not None and len(data) > max_bytes:
        raise RawParseError(f'The file is larger than {max_bytes // (1024 * 1024)} MB.')
    if not data.strip():
        raise RawParseError('The file is empty.')
    text, encoding = _decode(data)
    try:
        lines = list(csv.reader(io.StringIO(text, newline='')))
    except csv.Error as exc:
        raise RawParseError(f'The file is not a valid CSV ({exc}).') from exc

    header_at = None
    for i, row in enumerate(lines[:HEADER_SEARCH_ROWS]):
        keys = {norm(c) for c in row}
        if 'btsipid' in keys and ('reportdate' in keys or {'month', 'year'} <= keys or 'circle' in keys):
            header_at = i
            break
    if header_at is None:
        raise RawParseError(f'No header row with "BTS IP ID" in the first {HEADER_SEARCH_ROWS} rows. This is not a raw CNMC availability CSV.')
    headers = [c.strip() for c in lines[header_at]]
    keys = [norm(h) for h in headers]
    if 'reportdate' not in keys and {'month', 'year'} <= set(keys):
        raise RawParseError('This is the monthly summary dump (MONTH and YEAR columns, no Report Date). Upload the daily file '
                            '(nw_aval_btsipid_wise_day…), which has a Report Date for each row.')
    columns: dict[str, str] = {}
    index: dict[str, int] = {}
    for fieldname, accepted in COLUMNS.items():
        positions = [i for i, k in enumerate(keys) if k in accepted]
        if len(positions) > 1:
            raise RawParseError(f'The column "{headers[positions[0]]}" appears more than once.')
        if positions:
            columns[fieldname], index[fieldname] = headers[positions[0]], positions[0]
    missing = [LABELS[f] for f in REQUIRED if f not in columns]
    if missing:
        raise RawParseError(f'Missing required columns: {", ".join(missing)}.')

    preamble = [', '.join(c for c in row if c.strip())[:200] for row in lines[:header_at] if any(c.strip() for c in row)]
    rows, malformed, blank = [], [], 0
    for offset, row in enumerate(lines[header_at + 1:], start=header_at + 2):
        if not any(c.strip() for c in row):
            blank += 1
            continue
        if len(row) != len(headers):
            malformed.append({'line': offset, 'cells': len(row), 'expected': len(headers)})
            continue
        rows.append(RawRow(offset, {f: row[i].strip() for f, i in index.items()}))
    if not rows and not malformed:
        raise RawParseError('The file has a header but no data rows.')
    used = {norm(h) for h in columns.values()}
    return ParsedRaw(encoding=encoding, header_line=header_at + 1, headers=headers, columns=columns, rows=rows,
                     preamble=preamble, blank_lines=blank, malformed=malformed,
                     unknown_headers=[h for h in headers if h and norm(h) not in used])


ALIAS_SOURCE = 'raw_daily_csv'


def canonical_circle(raw: str, project: str | None = None, resolver=None) -> str:
    """The site-master circle code of a raw circle code, through the Organization's raw daily CSV aliases (Administration >
    Organization > Code Mapping; e.g. the verified "OR" for "OD" of the Odisha dump). A code that is neither an alias nor
    a circle is returned as written (upper case), so it is reported as a mismatch, never turned into a circle."""
    from apps.organization.services import AliasResolver
    resolver = resolver or AliasResolver(ALIAS_SOURCE)
    return resolver.resolve(raw, project) or (raw or '').strip().upper()
