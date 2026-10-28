"""Compare the dashboard's own calculations with the figures cached in the workbook's summary sheets.

The dashboard never copies these figures; it recalculates everything from the
daily outage minutes in Up-Time Report. This module reads the workbook's
current-month results (Summ site counts and MTD uptime, Day wise Trend daily
and weekly uptime), recomputes each one, and reports major differences.

Tables are found by their labels ("Circle", "Total Site count", "Oct-26 MTD",
"Week-1 (1-7) Oct-26", ...), not by fixed cell addresses, so a re-arranged
sheet is still checked. Figures for earlier months are not compared: Summ's
monthly totals are frozen pasted values (docs/business-rules.md).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

import numpy as np
import pandas as pd
from openpyxl.utils import get_column_letter

from .metrics import Selection, _window, mtd_positions, scope_mask, uptime_pct
from .workbook import CIRCLE_ALIASES, Dataset

# A difference at or above these limits is "major" and raised as an alert.
UPTIME_TOLERANCE_PTS = 0.5
COUNT_TOLERANCE = 0  # site counts are exact definitions

REPORT_TYPE_LABELS = {'4G Saturation': '4G', 'LWE': 'LWE'}
SCOPE_LABELS = {'on_air': 'On-Air', 'om_start': 'O&M Start', 'all': 'all sites'}
WEEK_RE = re.compile(r'^Week-\d+\s*\((\d+)-(\d+)\)\s*(\S+)$')
MAX_LISTED = 50


@dataclass(frozen=True)
class Figure:
    sheet: str
    cell: str
    report_type: str
    circle: str | None
    scope: str
    metric: str  # sites_total | sites_in_scope | mtd | day | week
    value: float
    start: date | None = None
    end: date | None = None
    formula: str | None = None

    @property
    def is_count(self) -> bool:
        return self.metric in ('sites_total', 'sites_in_scope')

    def describe(self) -> str:
        where = f"{self.circle or 'All circles'} · {REPORT_TYPE_LABELS.get(self.report_type, self.report_type)}"
        scope = SCOPE_LABELS[self.scope]
        if self.metric == 'sites_total':
            return f'{where} total sites'
        if self.metric == 'sites_in_scope':
            return f'{where} {scope} sites'
        if self.metric == 'mtd':
            return f'{where} {scope} MTD uptime'
        if self.metric == 'day':
            return f"{where} {scope} uptime on {self.start.strftime('%d %b')}"
        return f"{where} {scope} uptime {self.start.strftime('%d')}–{self.end.strftime('%d %b')}"


def calculation_check(ds: Dataset) -> dict:
    """Recompute every workbook figure found and list the major differences, largest first."""
    cached = ds._memo.get('calculation_check')
    if cached is None:
        cached = ds._memo['calculation_check'] = _check(ds)
    return cached


def _check(ds: Dataset) -> dict:
    figures = find_figures(ds)
    differences = []
    for figure in figures:
        ours = dashboard_value(ds, figure)
        if ours is None:
            continue
        gap = ours - figure.value
        limit = COUNT_TOLERANCE if figure.is_count else UPTIME_TOLERANCE_PTS
        if (abs(gap) > limit) if figure.is_count else (abs(gap) >= limit):
            differences.append({
                'sheet': figure.sheet,
                'cell': figure.cell,
                'description': figure.describe(),
                'unit': 'sites' if figure.is_count else 'pct',
                'workbook': round(figure.value, 2),
                'dashboard': round(ours, 2),
                'difference': round(gap, 2),
                'formula': f'={figure.formula}' if figure.formula else None,
            })
    # Count mismatches first (definitions disagree), then the biggest uptime gaps.
    differences.sort(key=lambda d: (d['unit'] != 'sites', -abs(d['difference'])))
    return {
        'checked': len(figures),
        'sheets': sorted({f.sheet for f in figures}),
        'tolerance_pts': UPTIME_TOLERANCE_PTS,
        'difference_count': len(differences),
        'differences': differences[:MAX_LISTED],
    }


def dashboard_value(ds: Dataset, figure: Figure) -> float | None:
    selection = Selection(figure.report_type, figure.circle, figure.scope)
    rows = np.flatnonzero(scope_mask(ds, selection))
    if figure.metric in ('sites_total', 'sites_in_scope'):
        return float(len(rows))
    if figure.metric == 'mtd':
        if not ds.latest_date:
            return None
        cols, _ = mtd_positions(ds, ds.latest_date)
    else:
        cols = [i for i, d in enumerate(ds.dates) if figure.start <= d <= figure.end]
    return uptime_pct(*_window(ds.outage[np.ix_(rows, cols)]))


# --- Reading the workbook's figures ------------------------------------------------------------

def find_figures(ds: Dataset) -> list[Figure]:
    figures: list[Figure] = []
    for name, frame in ds.reference_sheets:
        grid = frame.to_numpy(dtype=object)
        formulas = ds.reference_formulas.get(name, {})
        for r, c in _header_cells(grid):
            title = _title_above(grid, r, c)
            if 'Total Site count' in _row_labels(grid, r, c):
                figures += _summ_table(ds, name, grid, r, c, title, formulas)
            elif 'day wise' in title.lower():
                figures += _trend_table(ds, name, grid, r, c, title, formulas)
    return figures


COUNT_COLUMN_SCOPES = {'Total Site count': 'all', 'On-Air Done': 'on_air', 'O&M Start Site count': 'om_start'}
_FORMULA_REF_RE = re.compile(r"\$?([A-Z]{1,3})\$?(\d+)(?![\d(])")


def _summ_table(ds, sheet, grid, r, c, title, formulas=None) -> list[Figure]:
    """Summ: Circle | Total Site count | On-Air Done | months... | <month> MTD | O&M Start Site count | ...

    An MTD cell's population is read from its formula: the site-count column it divides
    by (e.g. ``/(1440*14*$C17)`` is Total Site count, so all sites). Without a formula,
    the column position decides (On-Air, or O&M Start after the O&M count column).
    """
    formulas = formulas or {}
    count_columns = {get_column_letter(col + 1): COUNT_COLUMN_SCOPES[label]
                     for col, label in _header_columns(grid, r, c) if label in COUNT_COLUMN_SCOPES}
    report_type = _report_type(title)
    mtd_label = f'{ds.month_label} MTD'
    columns = []
    seen_om_count = False
    for col, label in _header_columns(grid, r, c):
        if label == 'Total Site count':
            columns.append((col, 'sites_total', 'all'))
        elif label == 'On-Air Done':
            columns.append((col, 'sites_in_scope', 'on_air'))
        elif label == 'O&M Start Site count':
            seen_om_count = True
            if ds.has_om_start:
                columns.append((col, 'sites_in_scope', 'om_start'))
        elif label == mtd_label and (ds.has_om_start or not seen_om_count):
            columns.append((col, 'mtd', 'om_start' if seen_om_count else 'on_air'))
    figures = []
    for row, circle in _circle_rows(grid, r, c):
        for col, metric, scope in columns:
            value = _number(grid[row, col])
            if value is None:
                continue
            cell = _cell(row, col)
            formula = formulas.get(cell)
            if metric == 'mtd':
                scope = _denominator_scope(formula, count_columns, row + 1) or scope
            figures.append(Figure(sheet, cell, report_type, circle, scope, metric,
                                  value if metric != 'mtd' else 100 * value, formula=formula))
    return figures


def _denominator_scope(formula: str | None, count_columns: dict[str, str], row: int) -> str | None:
    """Scope of the site-count cell in the same row that the formula divides by, if exactly one."""
    if not formula or '/' not in formula:
        return None
    denominator = formula[formula.rindex('/'):]
    scopes = {count_columns[col] for col, ref_row in _FORMULA_REF_RE.findall(denominator)
              if col in count_columns and int(ref_row) == row}
    return scopes.pop() if len(scopes) == 1 else None


def _trend_table(ds, sheet, grid, r, c, title, formulas=None) -> list[Figure]:
    """Day wise Trend: Circle | <scope> count | Week-1 (1-7) Oct-26 ... | 2026-10-01 | 2026-10-02 ..."""
    lowered = title.lower()
    if 'o&m start' in lowered:
        scope = 'om_start'
    elif 'on-air' in lowered:
        scope = 'on_air'
    else:
        return []
    if scope == 'om_start' and not ds.has_om_start:
        return []
    report_type = _report_type(title)
    month_end = ds.dates[-1]
    columns = []
    for col, label in _header_columns(grid, r, c):
        if isinstance(label, (datetime, pd.Timestamp)):
            day = pd.Timestamp(label).date()
            if day in ds.reported_dates:
                columns.append((col, 'day', day, day))
            continue
        match = WEEK_RE.match(str(label))
        if not match or match.group(3) != ds.month_label:
            continue
        first, last = int(match.group(1)), min(int(match.group(2)), month_end.day)
        start, end = month_end.replace(day=first), month_end.replace(day=last)
        # The workbook shows 100% for unreported days, so only fully reported weeks are comparable.
        if all(d in ds.reported_dates for d in ds.dates if start <= d <= end):
            columns.append((col, 'week', start, end))
    figures = []
    for row, circle in _circle_rows(grid, r, c):
        for col, metric, start, end in columns:
            value = _number(grid[row, col])
            if value is not None:
                cell = _cell(row, col)
                figures.append(Figure(sheet, cell, report_type, circle, scope, metric,
                                      100 * value, start, end, (formulas or {}).get(cell)))
    return figures


def _header_cells(grid) -> list[tuple[int, int]]:
    return [(r, c) for r in range(grid.shape[0]) for c in range(grid.shape[1])
            if isinstance(grid[r, c], str) and grid[r, c].strip() == 'Circle']


def _header_columns(grid, r, c):
    """(column, label) to the right of the 'Circle' header, up to the first empty header cell."""
    for col in range(c + 1, grid.shape[1]):
        label = grid[r, col]
        if _blank(label):
            return
        yield col, label.strip() if isinstance(label, str) else label


def _row_labels(grid, r, c) -> set:
    return {label for _, label in _header_columns(grid, r, c) if isinstance(label, str)}


def _circle_rows(grid, r, c):
    """(row, circle) below the header until a blank; 'Grand Total' means all circles."""
    for row in range(r + 1, grid.shape[0]):
        label = grid[row, c]
        if _blank(label):
            return
        label = str(label).strip()
        if label.lower() == 'grand total':
            yield row, None
            return
        yield row, CIRCLE_ALIASES.get(label, label)


def _title_above(grid, r, c) -> str:
    for row in range(r - 1, max(r - 3, -1), -1):
        value = grid[row, c]
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ''


def _report_type(title: str) -> str:
    return 'LWE' if 'lwe' in title.lower() else '4G Saturation'


def _number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, np.number)):
        return None
    value = float(value)
    return None if np.isnan(value) else value


def _blank(value) -> bool:
    return value is None or (isinstance(value, float) and np.isnan(value)) or (isinstance(value, str) and not value.strip())


def _cell(row: int, col: int) -> str:
    return f'{get_column_letter(col + 1)}{row + 1}'
