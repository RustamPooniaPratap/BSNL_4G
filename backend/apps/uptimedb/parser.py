"""Read an Up-Time Report sheet into site, monthly and daily records (no database access).

Columns are found by their header text, never by position, so workbooks with extra or
missing columns (e.g. the RJ, MP & OD report has no Project column) are read correctly.
Each month's dates appear in two runs: the first holds daily outage minutes, the second
the daily uptime fraction. Blank cells and placeholders ("-", "NA") become None, never 0.
Rules for which rows are sites follow apps.dashboard.workbook (the Excel source), so both
sources describe the same sites.
"""
from __future__ import annotations

import calendar
import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl.utils import get_column_letter

from apps.dashboard.workbook import CIRCLE_ALIASES, HEADER_ROW, REPORT_TYPES, SHEET_NAME

PLACEHOLDERS = {'', '-', '--', 'na', 'n/a', '#n/a', 'nil', 'null', 'none'}
MONTH_NUMBERS = {name.lower(): i for i, name in enumerate(calendar.month_abbr) if name}
MONTH_RE = r'([A-Za-z]{3})[A-Za-z]*-(\d{2})'
OUTAGE_RE = re.compile(rf'^{MONTH_RE} Outage Min\.?$', re.I)
UPTIME_RE = re.compile(rf'^{MONTH_RE} Up-?Time$', re.I)
FF_RE = re.compile(rf'^FF Count\s*-\s*{MONTH_RE}$', re.I)
OM_RE = re.compile(rf'^O&M Start\s*-\s*{MONTH_RE}$', re.I)
SUMMARY_RE = re.compile(r'\b(grand\s*total|sub\s*total|total)\b', re.I)
MAX_EXAMPLES = 20

# Site attributes by header (case-insensitive) -> model field.
ATTRIBUTES = {
    'project': 'project_raw', 'circle': 'circle_raw', 'btsipid': 'site_id', 'site name': 'site_name',
    'oa': 'oa', 'ba': 'ba', 'on-air': 'on_air_raw', 'eb': 'eb', 'od eb working status': 'od_eb_working_status',
    'solar logic done date': 'solar_logic_done', 'ie name': 'ie_name', 'ie contact no': 'ie_contact',
    'ci name': 'ci_name', 'ci contact no': 'ci_contact',
}
SITE_FIELDS = ('project', 'project_raw', 'circle', 'circle_raw', 'site_id', 'site_name', 'oa', 'ba', 'on_air_raw', 'on_air',
               'eb', 'od_eb_working_status', 'solar_logic_done', 'ie_name', 'ie_contact', 'ci_name', 'ci_contact', 'extra')
MONTH_FIELDS = ('ff_count', 'outage_minutes', 'uptime_pct', 'bucket', 'om_start_raw', 'om_start')


class ParseError(ValueError):
    """The file cannot be read as an Up-Time Report (wrong sheet or missing key columns)."""


def site_key(site_id: str) -> str:
    """Matching key: the ID trimmed, upper case, with inner whitespace collapsed. The original is kept separately."""
    return re.sub(r'\s+', ' ', site_id.strip()).upper()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _month(match: re.Match) -> date | None:
    number = MONTH_NUMBERS.get(match.group(1).lower())
    return date(2000 + int(match.group(2)), number, 1) if number else None


def _header(value):
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool) and 30000 < value < 80000 and float(value).is_integer():
        return (datetime(1899, 12, 30) + timedelta(days=int(value))).date()  # Excel date serial
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    return str(value).strip()


def _text(value) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return ''
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _number(value):
    """(number or None, problem text or None). Blanks and placeholders are None without a problem."""
    if value is None or isinstance(value, bool):
        return None, None
    if isinstance(value, (int, float, np.integer, np.floating)):
        return (None, None) if np.isnan(value) else (float(value), None)
    text = str(value).strip()
    if text.lower() in PLACEHOLDERS:
        return None, None
    try:
        return float(text.replace(',', '').rstrip('%')) / (100 if text.endswith('%') else 1), None
    except ValueError:
        return None, text


def _pct(fraction):
    """Source uptime is a fraction (0.98 shown as 98%); stored as a percentage."""
    return None if fraction is None else round(fraction * 100, 6)


@dataclass
class ParsedWorkbook:
    filename: str
    checksum: str
    sheet: str
    data_rows: int = 0
    sites: dict = field(default_factory=dict)        # key -> site fields (+ source_row)
    monthly: dict = field(default_factory=dict)      # key -> {month: {fields}}
    daily: dict = field(default_factory=dict)        # key -> {date: (outage, uptime_pct)}
    months: list = field(default_factory=list)       # months with monthly columns
    daily_months: dict = field(default_factory=dict)  # 'YYYY-MM' -> columns, dates, reported dates, missing values
    issues: list = field(default_factory=list)       # rejected or flagged rows
    skipped: dict = field(default_factory=dict)      # reason -> count (blank and summary rows)
    has_project_column: bool = True

    def issue(self, code: str, severity: str, row: int | None, site_id: str, message: str):
        self.issues.append({'code': code, 'severity': severity, 'row': row, 'site_id': site_id, 'message': message})

    @property
    def rejected(self) -> int:
        return sum(1 for i in self.issues if i['severity'] == 'rejected')


def parse_workbook(path: Path, *, filename: str | None = None, default_project: str | None = None) -> ParsedWorkbook:
    """Parse the Up-Time Report sheet. ``default_project`` is used only when the sheet has no Project column."""
    try:
        raw = pd.read_excel(path, sheet_name=SHEET_NAME, header=None, engine='openpyxl', keep_default_na=False)
    except ValueError as exc:
        raise ParseError(f"The workbook has no '{SHEET_NAME}' sheet.") from exc
    except Exception as exc:  # unreadable file
        raise ParseError('The file could not be opened as an Excel workbook (.xlsx).') from exc
    result = ParsedWorkbook(filename=filename or path.name, checksum=sha256(path), sheet=SHEET_NAME)
    if len(raw) <= HEADER_ROW:
        raise ParseError(f"The '{SHEET_NAME}' sheet has no header row (expected on row {HEADER_ROW + 1}).")
    headers = [_header(v) for v in raw.iloc[HEADER_ROW]]
    body = raw.iloc[HEADER_ROW + 1:].reset_index(drop=True)

    def letter(i: int) -> str:
        return get_column_letter(i + 1)

    # --- Classify columns by header -----------------------------------------------------------
    attributes: dict[str, int] = {}
    om: dict[date, int] = {}
    monthly_cols: dict[date, dict[str, int]] = {}
    extra: dict[int, str] = {}
    last_uptime_month = None
    for i, h in enumerate(headers):
        if h is None or isinstance(h, date):
            continue
        name = h.casefold()
        uptime_match = UPTIME_RE.match(h)
        if name in ATTRIBUTES and ATTRIBUTES[name] not in attributes:
            attributes[ATTRIBUTES[name]] = i
        elif (m := OM_RE.match(h)) and _month(m):
            om[_month(m)] = i
        elif (m := OUTAGE_RE.match(h)) and _month(m):
            monthly_cols.setdefault(_month(m), {})['outage_minutes'] = i
        elif uptime_match and _month(uptime_match):
            monthly_cols.setdefault(_month(uptime_match), {})['uptime_pct'] = i
        elif (m := FF_RE.match(h)) and _month(m):
            monthly_cols.setdefault(_month(m), {})['ff_count'] = i
        elif name == 'bucket' and last_uptime_month and 'bucket' not in monthly_cols[last_uptime_month]:
            monthly_cols[last_uptime_month]['bucket'] = i  # the Bucket column follows its month's UpTime
        else:
            extra[i] = f'{h} [{letter(i)}]'
        last_uptime_month = _month(uptime_match) if uptime_match else None

    for required, label in (('circle_raw', 'Circle'), ('site_id', 'btsIpId')):
        if required not in attributes:
            raise ParseError(f"The '{SHEET_NAME}' sheet has no '{label}' column on row {HEADER_ROW + 1}.")
    result.has_project_column = 'project_raw' in attributes
    if not result.has_project_column and not default_project:
        raise ParseError(f"The '{SHEET_NAME}' sheet has no 'Project' column, so sites cannot be assigned to 4G Saturation or LWE.")

    # Daily date runs: per month, the first run is outage minutes and the second the uptime fraction.
    runs: list[tuple[int, int]] = []
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
        runs.append((start, i))
    per_month: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for start, end in runs:
        per_month.setdefault((headers[start].year, headers[start].month), []).append((start, end))
    daily_blocks = []  # (month key, outage run, uptime run or None)
    for (y, mo), month_runs in sorted(per_month.items()):
        outage_run = month_runs[0]
        uptime_run = month_runs[1] if len(month_runs) > 1 else None
        if uptime_run and [headers[c] for c in range(*uptime_run)] != [headers[c] for c in range(*outage_run)]:
            uptime_run = None  # different dates: never pair by position
        for extra_run in month_runs[2:]:
            for c in range(*extra_run):
                extra[c] = f'{headers[c].isoformat()} [{letter(c)}]'
        daily_blocks.append((f'{y}-{mo:02d}', outage_run, uptime_run))
    if not daily_blocks:
        raise ParseError(f"No daily date columns were found on row {HEADER_ROW + 1} of '{SHEET_NAME}'.")
    result.months = sorted(set(monthly_cols) | set(om))

    # --- Rows ---------------------------------------------------------------------------------
    values = body.to_numpy(dtype=object)
    seen: dict[tuple, int] = {}
    ids_by_project: dict[tuple, set] = {}
    for r, row in enumerate(values):
        excel_row = r + HEADER_ROW + 2

        def get(key: str) -> str:
            return _text(row[attributes[key]]) if key in attributes else ''

        site_id, circle_raw = get('site_id'), get('circle_raw')
        project_raw = get('project_raw') if result.has_project_column else ''
        if not any(_text(v) for v in row):
            result.skipped['blank'] = result.skipped.get('blank', 0) + 1
            continue
        if SUMMARY_RE.search(site_id) or SUMMARY_RE.search(circle_raw) or SUMMARY_RE.search(project_raw):
            result.skipped['summary'] = result.skipped.get('summary', 0) + 1
            continue
        result.data_rows += 1
        if not site_id:
            result.issue('missing_site_id', 'rejected', excel_row, '', 'No btsIpId on a row with data.')
            continue
        if result.has_project_column:
            if project_raw not in REPORT_TYPES:
                result.issue('unknown_project', 'rejected', excel_row, site_id, f"Unrecognised Project value '{project_raw}'.")
                continue
            project = REPORT_TYPES[project_raw]
        else:
            project = default_project
        if not circle_raw:
            result.issue('missing_circle', 'rejected', excel_row, site_id, 'No Circle on the row.')
            continue
        circle = CIRCLE_ALIASES.get(circle_raw, circle_raw)
        key = (project, circle, site_key(site_id))
        if key in seen:
            result.issue('duplicate_key', 'rejected', excel_row, site_id, f'Same project, circle and site ID as row {seen[key]}; the first row is kept.')
            continue
        seen[key] = excel_row
        ids_by_project.setdefault((project, site_key(site_id)), set()).add(circle)
        written = row[attributes['site_id']]
        spaced = isinstance(written, str) and (written != written.strip() or '  ' in written)
        if spaced:
            result.issue('site_id_spacing', 'flagged', excel_row, site_id,
                         'The site ID has extra spaces; it is matched and stored trimmed (as the dashboard does), and kept as written in extra.')

        site = {name: get(name) for name in ATTRIBUTES.values()}
        site.update(project=project, project_raw=project_raw, circle=circle, site_id=site_id, source_row=excel_row,
                    on_air=site['on_air_raw'].casefold() == 'yes',
                    extra={label: _text(row[c]) for c, label in extra.items() if _text(row[c])})
        if spaced:
            site['extra']['btsIpId (as written)'] = written
        result.sites[key] = site

        months = {}
        for month in result.months:
            cols = monthly_cols.get(month, {})
            record = {}
            for name in ('ff_count', 'outage_minutes', 'uptime_pct'):
                number, problem = _number(row[cols[name]]) if name in cols else (None, None)
                if problem:
                    result.issue('non_numeric', 'flagged', excel_row, site_id, f"{headers[cols[name]]}: '{problem}' is not a number and was stored as empty.")
                record[name] = _pct(number) if name == 'uptime_pct' else number
            record['bucket'] = _text(row[cols['bucket']]) if 'bucket' in cols else ''
            if month in om:
                raw_om = _text(row[om[month]])
                record['om_start_raw'], record['om_start'] = raw_om, raw_om.casefold() == 'yes'
            else:
                record['om_start_raw'], record['om_start'] = None, None
            months[month] = record
        result.monthly[key] = months

        days = {}
        for _, (o_start, o_end), uptime_run in daily_blocks:
            for offset, c in enumerate(range(o_start, o_end)):
                outage, problem = _number(row[c])
                if problem:
                    result.issue('non_numeric', 'flagged', excel_row, site_id, f"{headers[c].isoformat()}: '{problem}' is not a number and was stored as empty.")
                uptime = _number(row[uptime_run[0] + offset])[0] if uptime_run else None
                days[headers[c]] = (outage, _pct(uptime))
        result.daily[key] = days

    for (project, key), circles in ids_by_project.items():
        if len(circles) > 1:
            result.issue('id_in_several_circles', 'flagged', None, key,
                         f'{project}: the same site ID appears in circles {", ".join(sorted(circles))}; kept as separate sites.')

    # Daily coverage per month: a date is reported when any site has an outage value.
    for month_key, (o_start, o_end), uptime_run in daily_blocks:
        dates = [headers[c] for c in range(o_start, o_end)]
        reported = [d for d in dates if any(days[d][0] is not None for days in result.daily.values())]
        missing = {d.isoformat(): sum(1 for days in result.daily.values() if days[d][0] is None) for d in reported}
        result.daily_months[month_key] = {
            'outage_columns': f'{letter(o_start)}:{letter(o_end - 1)}',
            'uptime_columns': f'{letter(uptime_run[0])}:{letter(uptime_run[1] - 1)}' if uptime_run else None,
            'dates': [d.isoformat() for d in dates],
            'reported_dates': [d.isoformat() for d in reported],
            'missing_values': {d: n for d, n in missing.items() if n},
        }
    return result


def summary(parsed: ParsedWorkbook) -> dict:
    """The validation preview for one file."""
    by_project: dict[str, int] = {}
    by_circle: dict[str, int] = {}
    for s in parsed.sites.values():
        by_project[s['project']] = by_project.get(s['project'], 0) + 1
        label = f"{s['project']}|{s['circle']}"
        by_circle[label] = by_circle.get(label, 0) + 1
    month_counts = {}
    for month in parsed.months:
        filled = sum(1 for months in parsed.monthly.values()
                     if months[month]['outage_minutes'] is not None or months[month]['uptime_pct'] is not None)
        month_counts[month.strftime('%Y-%m')] = {'label': month.strftime('%b-%y'), 'sites_with_values': filled}
    codes: dict[str, dict] = {}
    for issue in parsed.issues:
        entry = codes.setdefault(issue['code'], {'severity': issue['severity'], 'count': 0, 'examples': []})
        entry['count'] += 1
        if len(entry['examples']) < MAX_EXAMPLES:
            entry['examples'].append(issue)
    daily = {}
    for key, info in parsed.daily_months.items():
        values = sum(1 for d in parsed.daily.values() for day, (o, _) in d.items() if o is not None and day.isoformat()[:7] == key)
        daily[key] = {**info, 'site_day_values': values}
    return {
        'filename': parsed.filename,
        'checksum': parsed.checksum,
        'sheet': parsed.sheet,
        'has_project_column': parsed.has_project_column,
        'data_rows': parsed.data_rows,
        'sites': len(parsed.sites),
        'distinct_site_ids': len({k[2] for k in parsed.sites}),
        'by_project': by_project,
        'by_circle': dict(sorted(by_circle.items())),
        'months': month_counts,
        'daily': daily,
        'skipped': parsed.skipped,
        'rejected': parsed.rejected,
        'flagged': sum(1 for i in parsed.issues if i['severity'] == 'flagged'),
        'issues': codes,
    }
