"""Read-only access to the active Master workbook's "Up-Time Report" sheet.

The active workbook is the last one accepted through the upload API (see
store.py and upload.py). MASTER_WORKBOOK_PATH is only a fallback for when
nothing has been uploaded yet.

Verified layout (see docs/data-dictionary.md):

* Excel row 1 holds column totals, row 2 holds the headers, data starts on row 3.
* One row per site. The business key is (Project, btsIpId).
* The first run of date-labelled columns holds daily OUTAGE MINUTES for the
  reporting month. A later run with the same date labels holds the derived
  daily up-time (``=1-outage/1440``). That second block is ignored: it shows
  100% for days that have not been reported yet.

The source workbook is never written to. Parsed data is cached in memory and
re-read only when the file's modification time or size changes.
"""
from __future__ import annotations

import calendar
import logging
import re
import threading
import zipfile
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from django.conf import settings
from openpyxl.utils import get_column_letter

from . import store

logger = logging.getLogger(__name__)

SHEET_NAME = 'Up-Time Report'
HEADER_ROW = 1  # zero-based: headers are on Excel row 2
MINUTES_PER_DAY = 1440

# Workbook "Project" value -> report type shown in the application.
REPORT_TYPES = {'4G Satu.': '4G Saturation', 'LWE': 'LWE'}
# LWE rows spell out two circles that 4G rows abbreviate. The workbook's own
# Summ sheet maps them with IF($B="MP","Madhya Pradesh",IF($B="OD","Odisha",...)).
CIRCLE_ALIASES = {'Madhya Pradesh': 'MP', 'Odisha': 'OD'}

REQUIRED_COLUMNS = ('Project', 'Circle', 'btsIpId', 'Site name', 'On-Air')
OPTIONAL_TEXT_COLUMNS = {'OA': 'oa', 'BA': 'ba', 'EB': 'eb', 'IE Name': 'ie_name', 'CI Name': 'ci_name'}
MAX_EXAMPLES = 5

# Sheets of the consolidated workbook and how the application uses them.
SHEET_ROLES = {
    'Up-Time Report': 'Source data: site rows with daily and monthly outage minutes (read by the dashboard)',
    'Summ': 'Summary formulas over Up-Time Report (site counts and MTD uptime are cross-checked)',
    'Day wise Trend': 'Daily and weekly uptime formulas (cross-checked against the dashboard)',
    'Uptime Bucketization': 'Bucket count formulas (used to reconcile results)',
}
# Summary sheets whose cached results are compared with the dashboard's calculations (crosscheck.py).
REFERENCE_SHEETS = ('Summ', 'Day wise Trend')
# Monthly history columns, e.g. "Sep-26 Outage Min." or "June-26 Outage Min.".
MONTHLY_OUTAGE_RE = re.compile(r'^([A-Za-z]{3})[A-Za-z]*-(\d{2}) Outage Min\.$')
MONTH_NUMBERS = {name.lower(): i for i, name in enumerate(calendar.month_abbr) if name}


class WorkbookError(RuntimeError):
    """The Master workbook is missing, unreadable or structurally invalid."""

    def __init__(self, message: str, code: str = 'invalid_workbook'):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Dataset:
    sites: pd.DataFrame  # one row per site, positional index 0..n-1
    outage: np.ndarray  # float64 [n_sites, n_dates]; NaN means "not reported"
    dates: tuple[date, ...]  # every date column in the month block
    reported_dates: tuple[date, ...]  # dates with at least one reported value
    month_label: str  # e.g. "Oct-26"
    has_om_start: bool
    workbook_name: str
    modified_at: datetime
    loaded_at: datetime
    warnings: tuple[dict, ...]
    # Monthly history before the current month: ({label, start, days}, ...) and outage [n_sites, n_months].
    months: tuple[dict, ...] = ()
    monthly_outage: np.ndarray | None = None
    outage_columns: tuple[int, int] = (0, 0)  # zero-based [start, end) of the daily block
    # Daily outage of earlier months found in the same sheet: ({key, label, dates, outage[n_sites, n_days]}, ...).
    daily_history: tuple[dict, ...] = field(default=(), repr=False)
    sheets: tuple[str, ...] = ()
    uploaded_at: datetime | None = None
    # (sheet name, raw cells) of the summary sheets, used only to cross-check calculations.
    reference_sheets: tuple[tuple[str, pd.DataFrame], ...] = field(default=(), repr=False)
    # Formula text of those sheets by cell ("K17" -> "1-SUMIFS(...)"), shared formulas resolved.
    reference_formulas: dict[str, dict[str, str]] = field(default_factory=dict, repr=False)
    # Previous month's O&M Start flag (sites column 'om_start_previous'); None when the source has no such column.
    previous_om_label: str | None = None
    _positions: dict = field(default_factory=dict, repr=False)
    _memo: dict = field(default_factory=dict, init=False, repr=False, compare=False)

    def __post_init__(self):
        self._positions.update({day: i for i, day in enumerate(self.dates)})

    def position(self, day: date) -> int | None:
        return self._positions.get(day)

    @property
    def latest_date(self) -> date | None:
        return self.reported_dates[-1] if self.reported_dates else None


def resolve_workbook() -> tuple[Path, str, datetime | None]:
    """Return (path, display name, uploaded at) for the workbook the dashboard should use."""
    record = store.active_record()
    if record:
        return record['path'], record['original_name'], datetime.fromisoformat(record['uploaded_at'])

    configured = settings.MASTER_WORKBOOK_PATH
    if configured:
        path = Path(configured)
        if not path.is_file():
            raise WorkbookError(f"The configured Master workbook '{path.name}' was not found.", 'no_workbook')
        return path, path.name, None

    raise WorkbookError(
        'No Master workbook has been uploaded yet. Upload the consolidated workbook on the Master workbook page.',
        'no_workbook',
    )


_cache_lock = threading.Lock()
_cache: dict = {'key': None, 'dataset': None}


def get_dataset() -> Dataset:
    """Return the parsed Master workbook, re-reading it only when the file changes."""
    path, name, uploaded_at = resolve_workbook()
    key = _cache_key(path)
    with _cache_lock:
        if _cache['key'] != key:
            _cache['dataset'] = load_dataset(path, display_name=name, uploaded_at=uploaded_at)
            _cache['key'] = key
        return _cache['dataset']


def prime_cache(path: Path, dataset: Dataset) -> None:
    """Install an already-parsed dataset (used right after an upload is accepted)."""
    with _cache_lock:
        _cache.update(key=_cache_key(path), dataset=dataset)


def _cache_key(path: Path) -> tuple:
    stat = path.stat()
    return str(path.resolve()), stat.st_mtime_ns, stat.st_size


def clear_cache() -> None:
    with _cache_lock:
        _cache.update(key=None, dataset=None)


def load_dataset(path: Path, *, display_name: str | None = None, uploaded_at: datetime | None = None) -> Dataset:
    started = datetime.now()
    name = display_name or path.name
    raw_names = sheet_names(path, strip=False)
    # Summary sheets are read in the same pass (opening the workbook is the slow part).
    references = [n for n in raw_names if n.strip() in REFERENCE_SHEETS]
    try:
        # keep_default_na=False: text such as "NA" or "-" must be flagged, not silently blanked.
        frames = pd.read_excel(path, sheet_name=[SHEET_NAME, *references], header=None, engine='openpyxl',
                               keep_default_na=False)
        raw = frames[SHEET_NAME]
    except ValueError as exc:
        if 'not found' in str(exc).lower():
            raise WorkbookError(f"The workbook '{name}' has no '{SHEET_NAME}' sheet.") from exc
        logger.exception('Could not parse workbook %s', name)
        raise WorkbookError(f"The workbook '{name}' could not be read.") from exc
    except Exception as exc:
        logger.exception('Could not open workbook %s', name)
        raise WorkbookError(f"The workbook '{name}' could not be opened.") from exc

    dataset = parse_sheet(
        raw,
        workbook_name=name,
        modified_at=datetime.fromtimestamp(path.stat().st_mtime),
    )
    warnings = list(dataset.warnings) + _formula_cache_warnings(path, dataset.outage_columns)
    reference_sheets = tuple((n.strip(), frames[n].replace('', np.nan)) for n in references)
    dataset = replace(dataset, sheets=tuple(n.strip() for n in raw_names), uploaded_at=uploaded_at,
                      warnings=tuple(warnings), reference_sheets=reference_sheets,
                      reference_formulas={n.strip(): sheet_formulas(path, n) for n in references})
    logger.info(
        'Loaded %s: %d sites, %d reported dates in %.1fs',
        name, len(dataset.sites), len(dataset.reported_dates),
        (datetime.now() - started).total_seconds(),
    )
    return dataset


def parse_sheet(raw: pd.DataFrame, *, workbook_name: str, modified_at: datetime) -> Dataset:
    """Validate and normalise the raw Up-Time Report grid (header=None)."""
    if len(raw) <= HEADER_ROW:
        raise WorkbookError(f"The '{SHEET_NAME}' sheet has no header row.")

    headers = [_header(value) for value in raw.iloc[HEADER_ROW]]
    body = raw.iloc[HEADER_ROW + 1:].reset_index(drop=True)
    warnings: list[dict] = []

    def column(name: str) -> int | None:
        return headers.index(name) if name in headers else None

    missing = [name for name in REQUIRED_COLUMNS if column(name) is None]
    if missing:
        raise WorkbookError(f"The '{SHEET_NAME}' sheet is missing required columns: {', '.join(missing)}.")

    blocks = _date_blocks(headers)
    start, end = blocks[-1]  # the latest month is the reporting month
    dates = tuple(headers[start:end])
    month_label = dates[0].strftime('%b-%y')

    def text(name: str) -> pd.Series:
        return body.iloc[:, column(name)].map(_text).astype(object)

    project = text('Project')
    site_id = text('btsIpId')
    keep = site_id != ''
    # Rows with neither a site ID nor a project are trailing blank rows, not data.
    blank_rows_with_data = int(((~keep) & (project != '')).sum())
    if blank_rows_with_data:
        warnings.append(_warning('blank_site_id', 'warning', 'Rows without a btsIpId were excluded.', blank_rows_with_data))

    unknown = keep & ~project.isin(list(REPORT_TYPES))
    if unknown.any():
        values = sorted(set(project[unknown]))
        warnings.append(_warning(
            'unknown_project', 'warning',
            'Rows with an unrecognised Project value were excluded.', int(unknown.sum()), values,
        ))
    keep &= ~unknown

    rows = np.flatnonzero(keep.to_numpy())
    circle_raw = text('Circle').iloc[rows]
    sites = pd.DataFrame({
        'site_id': site_id.iloc[rows].to_numpy(),
        'site_name': text('Site name').iloc[rows].to_numpy(),
        'report_type': project.iloc[rows].map(REPORT_TYPES).to_numpy(),
        'circle': circle_raw.replace(CIRCLE_ALIASES).to_numpy(),
        'circle_raw': circle_raw.to_numpy(),
        'source_row': rows + HEADER_ROW + 2,  # 1-based Excel row number
    })
    for header, key in OPTIONAL_TEXT_COLUMNS.items():
        sites[key] = text(header).iloc[rows].to_numpy() if column(header) is not None else ''

    on_air_raw = text('On-Air').iloc[rows]
    sites['on_air'] = (on_air_raw.str.casefold() == 'yes').to_numpy()
    other_on_air = on_air_raw[(on_air_raw != '') & (on_air_raw.str.casefold() != 'yes')]
    if len(other_on_air):
        warnings.append(_warning(
            'on_air_values', 'info',
            "On-Air values other than 'Yes' or blank are treated as not On-Air.",
            len(other_on_air), sorted(set(other_on_air)),
        ))

    om_header = f'O&M Start - {month_label}'
    has_om_start = column(om_header) is not None
    if has_om_start:
        sites['om_start'] = (text(om_header).iloc[rows].str.casefold() == 'yes').to_numpy()
    else:
        sites['om_start'] = False
        warnings.append(_warning(
            'om_start_missing', 'warning',
            f"Column '{om_header}' was not found, so the O&M Start scope is unavailable.", 0,
        ))

    # The previous month's O&M Start column, for the month-on-month conversion change (never estimated).
    previous_om_label = (dates[0] - timedelta(days=1)).strftime('%b-%y')
    previous_om_header = f'O&M Start - {previous_om_label}'
    if column(previous_om_header) is not None:
        sites['om_start_previous'] = (text(previous_om_header).iloc[rows].str.casefold() == 'yes').to_numpy()
    else:
        previous_om_label = None

    aliased = circle_raw[circle_raw.isin(list(CIRCLE_ALIASES))]
    if len(aliased):
        warnings.append(_warning(
            'circle_alias', 'info',
            'LWE circle names were normalised to circle codes (Madhya Pradesh to MP, Odisha to OD).',
            len(aliased), sorted(set(aliased)),
        ))

    duplicated = sites.duplicated(['report_type', 'site_id'], keep='first').to_numpy()
    if duplicated.any():
        examples = sorted(set(sites.loc[duplicated, 'site_id']))
        warnings.append(_warning(
            'duplicate_site', 'warning',
            'Duplicate (report type, btsIpId) rows were found; only the first row of each is used.',
            int(duplicated.sum()), examples,
        ))
        rows = rows[~duplicated]
        sites = sites.loc[~duplicated]
    sites = sites.reset_index(drop=True)

    block = body.iloc[rows, start:end].map(lambda v: np.nan if isinstance(v, str) and not v.strip() else v)
    outage_frame = block.apply(pd.to_numeric, errors='coerce')
    non_numeric = block.notna().to_numpy() & outage_frame.isna().to_numpy()
    outage = outage_frame.to_numpy(dtype=float)
    if non_numeric.any():
        warnings.append(_warning(
            'non_numeric_outage', 'warning',
            'Non-numeric daily outage values were treated as not reported.',
            int(non_numeric.sum()), _cell_examples(sites, dates, non_numeric, block.to_numpy()),
        ))

    reported_mask = ~np.isnan(outage)
    reported_dates = tuple(day for i, day in enumerate(dates) if reported_mask[:, i].any())
    warnings.extend(_coverage_warnings(sites, dates, outage, reported_dates))

    out_of_range = reported_mask & ((outage < 0) | (outage > MINUTES_PER_DAY))
    if out_of_range.any():
        warnings.append(_warning(
            'outage_out_of_range', 'warning',
            f'Daily outage values outside 0 to {MINUTES_PER_DAY} minutes. They are included in totals '
            'exactly as the workbook does, pending a business rule.',
            int(out_of_range.sum()), _cell_examples(sites, dates, out_of_range, outage),
        ))

    month_total = column(f'{month_label} Outage Min.')
    if month_total is not None:
        expected = pd.to_numeric(body.iloc[rows, month_total].replace('', np.nan), errors='coerce').to_numpy(dtype=float)
        mismatched = ~np.isclose(np.nansum(outage, axis=1), np.nan_to_num(expected), atol=0.01)
        if mismatched.any():
            warnings.append(_warning(
                'month_total_mismatch', 'warning',
                f"'{month_label} Outage Min.' differs from the sum of the daily outage columns.",
                int(mismatched.sum()), list(sites.loc[mismatched, 'site_id'][:MAX_EXAMPLES]),
            ))

    months, monthly_outage = _monthly_history(headers, body, rows, dates[0])
    daily_history = _daily_history(body, rows, headers, blocks[:-1], warnings)

    return Dataset(
        sites=sites,
        outage=outage,
        dates=dates,
        reported_dates=reported_dates,
        month_label=month_label,
        has_om_start=has_om_start,
        previous_om_label=previous_om_label,
        workbook_name=workbook_name,
        modified_at=modified_at,
        loaded_at=datetime.now(),
        warnings=tuple(warnings),
        months=months,
        monthly_outage=monthly_outage,
        outage_columns=(start, end),
        daily_history=daily_history,
    )


def _monthly_history(headers: list, body: pd.DataFrame, rows: np.ndarray, current: date):
    """Monthly outage columns for months before the reporting month, oldest first."""
    found = []
    for index, header in enumerate(headers):
        match = MONTHLY_OUTAGE_RE.match(header) if isinstance(header, str) else None
        if not match or match.group(1).lower() not in MONTH_NUMBERS:
            continue
        start = date(2000 + int(match.group(2)), MONTH_NUMBERS[match.group(1).lower()], 1)
        if start >= current.replace(day=1):
            continue
        found.append((start, index))
    found.sort()
    months = tuple(
        {'label': start.strftime('%b-%y'), 'start': start, 'days': calendar.monthrange(start.year, start.month)[1]}
        for start, _ in found
    )
    if not found:
        return months, np.empty((len(rows), 0))
    block = body.iloc[rows, [index for _, index in found]].replace('', np.nan)
    return months, block.apply(pd.to_numeric, errors='coerce').to_numpy(dtype=float)


def sheet_names(path: Path, *, strip: bool = True) -> list[str]:
    """Worksheet names in workbook order, read from the package without loading cells."""
    try:
        with zipfile.ZipFile(path) as package:
            xml = package.read('xl/workbook.xml').decode('utf-8', errors='replace')
    except (OSError, KeyError, zipfile.BadZipFile):
        return []
    names = [_unescape(name) for name in re.findall(r'<sheet\b[^>]*\bname="([^"]*)"', xml)]
    return [name.strip() for name in names] if strip else names


def _formula_cache_warnings(path: Path, outage_columns: tuple[int, int]) -> list[dict]:
    """Flag formula cells in Up-Time Report that have no cached result.

    Neither pandas nor openpyxl recalculates formulas; a formula without a cached
    value reads as blank. That happens when a workbook is saved by a tool other
    than Excel without recalculation.
    """
    try:
        with zipfile.ZipFile(path) as package:
            xml_path = _sheet_xml_path(package, SHEET_NAME)
            data = package.read(xml_path) if xml_path else b''
    except (OSError, KeyError, zipfile.BadZipFile):
        return []
    uncached = re.findall(rb'<c r="([A-Z]+)\d+"[^>]*>(?:<f[^>]*/>|<f[^>]*>[^<]*</f>)(?!<v>)', data)
    if not uncached:
        return []
    start, end = outage_columns
    block_letters = {get_column_letter(i + 1).encode() for i in range(start, end)}
    in_block = sum(1 for letters in uncached if letters in block_letters)
    warnings = [_warning(
        'formula_not_cached', 'warning',
        f"{len(uncached)} formula cells in '{SHEET_NAME}' have no cached result, so they read as blank. "
        'Open the workbook in Excel, let it recalculate, save, and upload again.',
        len(uncached),
    )]
    if in_block:
        warnings.append(_warning(
            'outage_formula_not_cached', 'warning',
            f'{in_block} daily outage cells are uncalculated formulas and are treated as not reported.',
            in_block,
        ))
    return warnings


_CELL_RE = re.compile(r'<c r="([A-Z]+)(\d+)"[^>]*>(?:<f([^>]*)/>|<f([^>]*)>([^<]*)</f>)')
_REF_RE = re.compile(r'(\$?)([A-Z]{1,3})(\$?)(\d+)(?![\d(])')


def sheet_formulas(path: Path, name: str) -> dict[str, str]:
    """Formula text of every formula cell in a sheet, read from the package XML.

    Excel stores a block of copied formulas once ("shared"); the other cells only point
    to it. Those are expanded here by shifting relative row references, which covers
    formulas copied down a column. Formulas copied across columns are left out.
    """
    try:
        with zipfile.ZipFile(path) as package:
            xml_path = _sheet_xml_path(package, name)
            xml = package.read(xml_path).decode('utf-8', errors='replace') if xml_path else ''
    except (OSError, KeyError, zipfile.BadZipFile):
        return {}
    formulas, masters, children = {}, {}, []
    for col, row, empty_attrs, attrs, text in _CELL_RE.findall(xml):
        attrs = attrs or empty_attrs
        shared = re.search(r'\bsi="(\d+)"', attrs) if 't="shared"' in attrs else None
        if text:
            formulas[f'{col}{row}'] = _unescape(text)
            if shared:
                masters[shared.group(1)] = (col, int(row), _unescape(text))
        elif shared:
            children.append((col, int(row), shared.group(1)))
    for col, row, si in children:
        if si in masters and masters[si][0] == col:
            _, master_row, text = masters[si]
            formulas[f'{col}{row}'] = _shift_rows(text, row - master_row)
    return formulas


def _shift_rows(formula: str, offset: int) -> str:
    """Move relative row references (A1, $A1) down by ``offset``; quoted sheet names are kept."""
    def shift(match):
        col_abs, col, row_abs, row = match.groups()
        return f'{col_abs}{col}{row_abs}{row if row_abs else int(row) + offset}'
    parts = re.split(r"('[^']*'!)", formula)
    return ''.join(part if part.endswith("'!") else _REF_RE.sub(shift, part) for part in parts)


def _sheet_xml_path(package: zipfile.ZipFile, name: str) -> str | None:
    workbook = package.read('xl/workbook.xml').decode('utf-8', errors='replace')
    rels = package.read('xl/_rels/workbook.xml.rels').decode('utf-8', errors='replace')
    targets = {}
    for rel in re.finditer(r'<Relationship\b[^>]*>', rels):
        rel_id = re.search(r'\bId="([^"]*)"', rel.group(0))
        target = re.search(r'\bTarget="([^"]*)"', rel.group(0))
        if rel_id and target:
            targets[rel_id.group(1)] = target.group(1)
    for sheet in re.finditer(r'<sheet\b[^>]*>', workbook):
        tag = sheet.group(0)
        sheet_name = re.search(r'\bname="([^"]*)"', tag)
        rel_id = re.search(r'\br:id="([^"]*)"', tag)
        if sheet_name and rel_id and _unescape(sheet_name.group(1)).strip() == name and rel_id.group(1) in targets:
            value = targets[rel_id.group(1)]
            return value.lstrip('/') if value.startswith('/') else f'xl/{value}'
    return None


def _unescape(value: str) -> str:
    return (value.replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"')
            .replace('&apos;', "'").replace('&amp;', '&'))


def _date_blocks(headers: list) -> list[tuple[int, int]]:
    """The daily outage block of every calendar month in the header row, oldest month first.

    A month's dates appear twice: daily outage minutes first, then the derived uptime %
    (100% for unreported days). Only the first run of consecutive dates of each month is
    the outage block; later runs are ignored. The latest month is the reporting month;
    earlier months (e.g. September added next to October) are daily history.
    """
    blocks: dict[tuple[int, int], tuple[int, int]] = {}
    i = 0
    while i < len(headers):
        if not isinstance(headers[i], date):
            i += 1
            continue
        start = i
        i += 1
        while (i < len(headers) and isinstance(headers[i], date) and headers[i] == headers[i - 1] + timedelta(days=1)
               and headers[i].month == headers[start].month):
            i += 1
        blocks.setdefault((headers[start].year, headers[start].month), (start, i))
    if not blocks:
        raise WorkbookError(f"No daily date columns were found in the '{SHEET_NAME}' header row.")
    return [blocks[key] for key in sorted(blocks)]


def _daily_history(body: pd.DataFrame, rows: np.ndarray, headers: list, blocks: list[tuple[int, int]],
                   warnings: list) -> tuple[dict, ...]:
    """Daily outage of months before the reporting month, aligned with the site rows."""
    history = []
    for start, end in blocks:
        dates = tuple(headers[start:end])
        label = dates[0].strftime('%b-%y')
        values = (body.iloc[rows, start:end].map(lambda v: np.nan if isinstance(v, str) and not v.strip() else v)
                  .apply(pd.to_numeric, errors='coerce').to_numpy(dtype=float))
        reported = values[~np.isnan(values)]
        if reported.size and reported.max() <= 1.0 and reported.min() >= 0:
            # Fractions between 0 and 1 are uptime, not outage minutes: do not misread them.
            warnings.append(_warning(
                'history_not_minutes', 'warning',
                f'The {label} daily columns hold values between 0 and 1 (uptime fractions, not outage minutes), '
                'so they are not used for the same-days comparison.', int(reported.size),
            ))
            continue
        reported_days = int((~np.isnan(values)).any(axis=0).sum())
        warnings.append(_warning(
            'daily_history', 'info',
            f'{label} daily outage found ({reported_days} reported days); used to compare the current month '
            'to date with the same days of that month.', reported_days,
        ))
        history.append({'key': dates[0].strftime('%Y-%m'), 'label': label, 'dates': dates, 'outage': values})
    return tuple(history)


def _coverage_warnings(sites: pd.DataFrame, dates, outage: np.ndarray, reported_dates) -> list[dict]:
    warnings = []
    if not reported_dates:
        return [_warning('no_reported_dates', 'warning', 'No daily outage values have been reported yet.', 0)]
    latest = reported_dates[-1]
    gaps = [day for day in dates if day < latest and day not in reported_dates]
    if gaps:
        warnings.append(_warning(
            'missing_dates', 'warning',
            'Dates before the latest reporting date have no values for any site.',
            len(gaps), [day.isoformat() for day in gaps],
        ))
    partial = []
    for i, day in enumerate(dates):
        if day in reported_dates:
            missing = int(np.isnan(outage[:, i]).sum())
            if missing:
                partial.append(f'{day.isoformat()} ({missing} sites)')
    if partial:
        warnings.append(_warning(
            'partial_dates', 'warning',
            'Some sites have no outage value on a reported date. They are excluded from that '
            "date's uptime and shown as missing.",
            len(partial), partial,
        ))
    return warnings


def _cell_examples(sites: pd.DataFrame, dates, mask: np.ndarray, values: np.ndarray) -> list[str]:
    examples = []
    for row, col in zip(*np.nonzero(mask)):
        value = values[row, col]
        shown = f'{value:.2f}' if isinstance(value, (float, np.floating)) else value
        examples.append(f'{sites.at[row, "site_id"]} on {dates[col].isoformat()}: {shown}')
        if len(examples) == MAX_EXAMPLES:
            break
    return examples


def _warning(code: str, severity: str, message: str, count: int, examples=None) -> dict:
    return {
        'code': code,
        'severity': severity,
        'message': message,
        'count': count,
        'examples': [str(e) for e in (examples or [])][:MAX_EXAMPLES],
    }


def _header(value):
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    return str(value).strip()


def _text(value) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)) or value is pd.NA:
        return ''
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()
