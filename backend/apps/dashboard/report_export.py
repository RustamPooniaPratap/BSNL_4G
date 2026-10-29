"""Excel downloads built from the dataset of the active source (Excel workbook or PostgreSQL, ``current_dataset()``).

- Daily Uptime Report: one sheet, one reporting date, one row per site of the selected project/circle: site ID, name,
  project, circle, date, outage minutes, availability and uptime bucket. A site without a value on the date is listed
  as "Not reported", never as zero.
- Full Consolidated Report: the 13 sheets of the consolidated workbook, in its order, from the application-managed
  template (report_templates/consolidated_template.xlsx, built once by ``manage.py build_report_template``; it holds
  styles and headers only). "Up-Time Report" gets one row per site in scope; its daily, weekly and month-to-date
  uptime and buckets are formulas over that row's daily cells, counting only reported days. The summary sheets are
  calculated here for the same sites with the dashboard's rules (``metrics``): pooled uptime over reported site-days,
  the workbook's bucket thresholds, On-Air or O&M Start populations as each sheet's title says. Sheets the application
  has no data for (maintained by hand in the workbook) keep their headers and say so; nothing is filled in.

Every figure respects the selected project and circles (already limited to the user's circles by the view).
"""
from __future__ import annotations

import calendar
import io
import re
import threading
from copy import copy
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import numpy as np
from openpyxl import Workbook, load_workbook
from openpyxl.formatting.rule import ColorScaleRule, Rule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.styles.differential import DifferentialStyle
from openpyxl.utils import get_column_letter

from .metrics import BUCKETS, WEEKS, bucket_ids, site_uptime, uptime_pct
from .workbook import MINUTES_PER_DAY, REPORT_TYPES, Dataset

TEMPLATE_PATH = Path(__file__).resolve().parent / 'report_templates' / 'consolidated_template.xlsx'
UPTIME_SHEET = 'Up-Time Report'
SHEET_ORDER = ('Repeated Sites', 'Summ', 'Uptime Bucketization ', 'Up-Time Report', 'Day wise Trend', 'All Circle - 98.5',
               'All Circle - Below 60', 'OD - EB & NEB', 'Signoff status', 'Bucketization', "CI's Performance",
               "IE's Performance", 'One Pager Summary')
MANUAL_NOTE = ('Not generated: this sheet is maintained by hand in the workbook and the application holds no data for it. '
               'Nothing has been filled in.')
PROJECT_LABEL = {canonical: raw for raw, canonical in REPORT_TYPES.items()}  # "4G Saturation" -> "4G Satu."
BUCKET_LABEL = {bucket_id: label for bucket_id, _, label, _ in BUCKETS}     # workbook labels, e.g. ">98.5"
BUCKET_ORDER = [bucket_id for bucket_id, *_ in BUCKETS]
NOT_REPORTED = 'Not reported'
XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


class ExportError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


@dataclass
class Scope:
    report_type: str | None          # None: all projects
    circles: list[str] | None        # None: every circle (the user may use all)
    circle: str | None = None        # the circle the user chose, for labels
    rows: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=int))

    @property
    def project_label(self) -> str:
        return self.report_type or 'All Projects'

    @property
    def circle_label(self) -> str:
        return self.circle or 'All Circles'


def resolve_scope(ds: Dataset, report_type: str | None, circle: str | None, allowed: set[str] | None) -> Scope:
    """Sites of the project and circle, within the user's circles. Raises ExportError when there are none."""
    circles = None if allowed is None else sorted(allowed)
    if circle:
        if allowed is not None and circle not in allowed:
            raise ExportError(f'You are not assigned to circle {circle}.', 403)
        circles = [circle]
    if circles == []:
        raise ExportError('No circle is assigned to your account.', 403)
    mask = np.ones(len(ds.sites), dtype=bool)
    if report_type:
        mask &= (ds.sites['report_type'] == report_type).to_numpy()
    if circles is not None:
        mask &= ds.sites['circle'].isin(circles).to_numpy()
    scope = Scope(report_type, circles, circle, np.flatnonzero(mask))
    if not len(scope.rows):
        raise ExportError(f'No {scope.project_label} sites in {scope.circle_label} in the selected data source.', 404)
    return scope


def _slug(text: str) -> str:
    return re.sub(r'[^A-Za-z0-9]+', '_', text).strip('_')


def day_outage(ds: Dataset, day: date) -> np.ndarray | None:
    """Every site's outage on ``day`` from the current month or an earlier month's daily columns; None if absent."""
    position = ds.position(day)
    if position is not None:
        return ds.outage[:, position]
    for entry in ds.daily_history:
        if day in entry['dates']:
            return entry['outage'][:, list(entry['dates']).index(day)]
    return None


def _to_bytes(wb) -> bytes:
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


# --- Daily Uptime Report -----------------------------------------------------------------------------------------

DAILY_HEADER = ('Site ID', 'Site Name', 'Project', 'Circle', 'Reporting Date', 'Outage Minutes', 'Availability (%)', 'Uptime Bucket')


def daily_report(ds: Dataset, scope: Scope, day: date, source_label: str) -> tuple[str, bytes]:
    values = day_outage(ds, day)
    if values is None or np.isnan(values[scope.rows]).all():
        raise ExportError(f'The selected data source has no daily values for {day:%d %b %Y} '
                          f'({scope.project_label}, {scope.circle_label}).', 404)
    sites = ds.sites.iloc[scope.rows]
    outage = values[scope.rows]
    uptime = site_uptime(outage[:, None])  # % per site, NaN when not reported
    buckets = bucket_ids(uptime)
    order = np.lexsort((sites['site_id'].to_numpy(), sites['circle'].to_numpy(), sites['report_type'].to_numpy()))

    wb = Workbook()
    ws = wb.active
    ws.title = 'Daily Uptime Report'
    ws['A1'] = f'Daily Uptime Report · {day:%d %b %Y} · {scope.project_label} · {scope.circle_label}'
    ws['A1'].font = Font(bold=True, size=13)
    ws['A2'] = (f'Source: {source_label}. Availability = 1 − outage minutes ÷ 1,440; buckets use the workbook thresholds. '
                f'"{NOT_REPORTED}" = no value for the date (never counted as zero).')
    ws['A2'].font = Font(italic=True, size=9, color='666666')
    ws.append([])
    ws.append(list(DAILY_HEADER))
    header_fill = PatternFill('solid', fgColor='1F4E78')
    for cell in ws[4]:
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
    for i in order:
        site = sites.iloc[i]
        reported = not np.isnan(outage[i])
        ws.append([site['site_id'], site['site_name'], site['report_type'], site['circle'], day,
                   float(outage[i]) if reported else None, float(uptime[i]) / 100 if reported else None,
                   BUCKET_LABEL[buckets[i]] if reported else NOT_REPORTED])
    last = ws.max_row
    for row in ws.iter_rows(min_row=5, max_row=last):
        row[4].number_format = 'DD-MMM-YYYY'
        row[5].number_format = '#,##0.00'
        row[6].number_format = '0.00%'
    for col, width in zip('ABCDEFGH', (18, 30, 15, 9, 14, 15, 15, 16)):
        ws.column_dimensions[col].width = width
    ws.freeze_panes = 'A5'
    ws.auto_filter.ref = f'A4:H{last}'
    name = f'Daily_Uptime_{_slug(scope.project_label)}_{_slug(scope.circle_label)}_{day.isoformat()}.xlsx'
    return name, _to_bytes(wb)


# --- Source details (Up-Time Report columns the Dataset does not carry) -------------------------------------------

_details_lock = threading.Lock()
_details_cache: dict = {'key': None, 'value': None}


def source_details(ds: Dataset) -> dict:
    """{(project, circle, site key): {'site': {...}, 'monthly': {month: {...}}}} from the active source.

    PostgreSQL: the imported site master and monthly records. Excel: the active workbook read with the importer's
    parser (no database access). Used only for descriptive columns (contacts, O&M Start by month, FF counts…).
    """
    from apps.uptimedb.datasource import DATABASE, active_source
    if active_source() == DATABASE:
        return _database_details()
    from apps.uptimedb.parser import parse_workbook
    from .workbook import resolve_workbook
    path = resolve_workbook()[0]
    key = (str(path), Path(path).stat().st_mtime)
    with _details_lock:
        if _details_cache['key'] != key:
            parsed = parse_workbook(Path(path))
            _details_cache.update(key=key, value={k: {'site': s, 'monthly': parsed.monthly.get(k, {})} for k, s in parsed.sites.items()})
        return _details_cache['value']


def _database_details() -> dict:
    from apps.uptimedb.models import SiteMonthlyPerformance, UptimeSite
    from apps.uptimedb.parser import SITE_FIELDS
    sites = {s['id']: s for s in UptimeSite.objects.values('id', 'site_key', *SITE_FIELDS)}
    out = {(s['project'], s['circle'], s['site_key']): {'site': s, 'monthly': {}} for s in sites.values()}
    by_id = {s['id']: out[(s['project'], s['circle'], s['site_key'])] for s in sites.values()}
    for m in SiteMonthlyPerformance.objects.values('site_id', 'month', 'ff_count', 'om_start_raw', 'om_start'):
        by_id[m['site_id']]['monthly'][m['month']] = m
    return out


def _site_key(site_id: str) -> str:
    return re.sub(r'\s+', ' ', str(site_id).strip()).upper()


# --- Full Consolidated Report ------------------------------------------------------------------------------------

def _style(cell) -> dict:
    return {'_style': copy(cell._style), 'number_format': cell.number_format}


def _put(ws, row: int, col: int, value, proto: dict | None = None, number_format: str | None = None):
    cell = ws.cell(row=row, column=col, value=value)
    if proto:
        cell._style = copy(proto['_style'])
    if number_format:
        cell.number_format = number_format
    return cell


def _clear_sheet(ws, keep_rows: int = 0) -> None:
    """Remove merges and every cell below ``keep_rows`` (values and styles); column widths stay."""
    for merged in list(ws.merged_cells.ranges):
        if merged.min_row > keep_rows:
            ws.unmerge_cells(str(merged))
    for row in ws.iter_rows(min_row=keep_rows + 1, max_row=ws.max_row):
        for cell in row:
            cell.value = None
            cell.style = 'Normal'
    ws.conditional_formatting = type(ws.conditional_formatting)()


@dataclass
class Period:
    day: date                 # the reporting date (end of the month to date)
    month: date               # first day of the current month
    label: str                # "Oct-26"
    mtd_cols: list[int]       # reported date positions up to ``day``
    dates: list[date]         # every date of the current month


def _period(ds: Dataset, day: date) -> Period:
    cols = [ds.position(d) for d in ds.reported_dates if d <= day]
    return Period(day, ds.dates[0], ds.month_label, cols, list(ds.dates))


class ConsolidatedReport:
    """Fills the template for ``scope``; values for summaries, row formulas in "Up-Time Report"."""

    def __init__(self, ds: Dataset, scope: Scope, day: date, source_label: str, details: dict):
        if not TEMPLATE_PATH.is_file():
            raise ExportError('The consolidated report template is missing from the application.', 500)
        if day not in ds.reported_dates:
            raise ExportError(f'{day:%d %b %Y} is not a reported date of {ds.month_label} in the selected data source.', 404)
        self.ds, self.scope, self.source_label, self.details = ds, scope, source_label, details
        self.p = _period(ds, day)
        self.wb = load_workbook(TEMPLATE_PATH)
        self.sites = ds.sites.iloc[scope.rows]
        self.on_air = self.sites['on_air'].to_numpy(dtype=bool)
        self.om = self.sites['om_start'].to_numpy(dtype=bool)
        self.groups = [(p, c) for p, c in sorted(set(zip(self.sites['report_type'], self.sites['circle'])),
                                                 key=lambda pc: (pc[0] != '4G Saturation', pc[0], pc[1]))]

    # -- helpers over the scoped rows ------------------------------------------------------------------------------
    def rows_for(self, project=None, circle=None, population='all') -> np.ndarray:
        mask = np.ones(len(self.scope.rows), dtype=bool)
        if project:
            mask &= (self.sites['report_type'] == project).to_numpy()
        if circle:
            mask &= (self.sites['circle'] == circle).to_numpy()
        if population == 'on_air':
            mask &= self.on_air
        elif population == 'om_start':
            mask &= self.om
        return self.scope.rows[mask]

    def month_block(self, rows: np.ndarray, month_index: int | None) -> tuple[np.ndarray, int]:
        """(outage block, days per site-month) for a history month index, or the current month to date (None)."""
        if month_index is None:
            return self.ds.outage[np.ix_(rows, self.p.mtd_cols)], 1
        return self.ds.monthly_outage[rows, month_index][:, None], self.ds.months[month_index]['days']

    def uptime(self, rows: np.ndarray, month_index: int | None) -> float | None:
        block, days = self.month_block(rows, month_index)
        reported = int((~np.isnan(block)).sum())
        value = uptime_pct(float(np.nansum(block)), reported * days)
        return None if value is None else value / 100

    def site_uptimes(self, rows: np.ndarray, month_index: int | None) -> np.ndarray:
        block, days = self.month_block(rows, month_index)
        if month_index is None:
            return site_uptime(block)
        with np.errstate(invalid='ignore'):
            return 100.0 * (1.0 - block[:, 0] / (MINUTES_PER_DAY * days))

    def outage(self, rows: np.ndarray, month_index: int | None) -> float | None:
        block, _ = self.month_block(rows, month_index)
        return None if np.isnan(block).all() else round(float(np.nansum(block)), 2)

    @property
    def months(self) -> list[tuple[str, int | None]]:
        """(label, index) of every history month, then the current month to date."""
        return [(m['label'], i) for i, m in enumerate(self.ds.months)] + [(f'{self.p.label} MTD', None)]

    def windows(self) -> list[tuple[str, list[int]]]:
        """Week 1-4 of the current month (the workbook's day ranges), then each date, as reported positions."""
        out = []
        for name, first, last in WEEKS:
            out.append((f'Wk-{name.split()[-1]}', [c for c in self.p.mtd_cols if first <= self.ds.dates[c].day <= last]))
        return out

    # -- build -------------------------------------------------------------------------------------------------------
    def build(self) -> tuple[str, bytes]:
        self.uptime_report()
        self.summ()
        self.bucketization()
        self.day_wise()
        self.threshold_sheet('All Circle - 98.5', 'gte_98_5', 'Monthly & Daily >98.5% Trend')
        self.threshold_sheet('All Circle - Below 60', 'lt_60', 'Monthly & Daily - Below 60% Trend')
        self.od_eb()
        self.people("CI's Performance", 'ci_name', "CI's Name")
        self.people("IE's Performance", 'ie_name', 'IE name')
        for name in ('Repeated Sites', 'Signoff status', 'Bucketization', 'One Pager Summary'):
            ws = self.wb[name]
            ws.cell(row=ws.max_row + 2, column=2, value=MANUAL_NOTE).font = Font(italic=True, color='9C0006')
        self.wb.active = self.wb.sheetnames.index('Summ')
        month = datetime(self.p.month.year, self.p.month.month, 1)
        name = (f'4G_LWE_Consolidated_Report_{_slug(self.scope.project_label)}_{_slug(self.scope.circle_label)}_'
                f'{month:%b-%Y}_to_{self.p.day.isoformat()}.xlsx')
        return name, _to_bytes(self.wb)

    # -- Up-Time Report ------------------------------------------------------------------------------------------------
    def uptime_report(self):
        ws = self.wb[UPTIME_SHEET]
        proto = {key: (_style(ws[f'{col}2']), _style(ws[f'{col}3']), _style(ws[f'{col}1']), ws.column_dimensions[col].width)
                 for key, col in (('ff', 'BL'), ('outage', 'BM'), ('uptime', 'BN'), ('bucket', 'BO'), ('daily', 'BT'),
                                  ('week_sum', 'CY'), ('week_up', 'DC'), ('daily_up', 'DG'), ('text', 'C'))}
        attr = {col: (_style(ws.cell(row=2, column=col)), _style(ws.cell(row=3, column=col))) for col in range(1, 22)}
        for row in ws.iter_rows(min_row=1, max_row=3, min_col=22, max_col=ws.max_column):
            for cell in row:
                cell.value = None
                cell.style = 'Normal'

        om_months = sorted({m for d in self.details.values() for m, v in d['monthly'].items() if v.get('om_start_raw')}, reverse=True)[:7]
        headers = [('Project', 'text'), ('Circle', 'text'), ('btsIpId', 'text'), ('Site name', 'text'), ('OA', 'text'), ('BA', 'text'),
                   ('On-Air', 'text'), ('EB', 'text'), ('OD EB Working status', 'text'), ('Solar Logic Done Date', 'text')]
        headers += [(f'O&M Start - {m:%b-%y}', 'text') for m in om_months] + [('', 'text')] * (7 - len(om_months))
        headers += [('IE Name', 'text'), ('IE Contact No', 'text'), ('CI Name', 'text'), ('CI Contact NO', 'text')]
        columns = []  # (header, kind, getter)
        for i, m in enumerate(self.ds.months):
            label = m['label']
            columns += [(f'FF Count - {label}', 'ff', ('ff', m['start'])), (f'{label} Outage Min.', 'outage', ('m_outage', i)),
                        (f'{label} UpTime', 'uptime', ('m_uptime', i)), ('Bucket', 'bucket', ('m_bucket', i))]
        first_daily = 22 + len(columns) + 4
        d0, d1 = get_column_letter(first_daily), get_column_letter(first_daily + len(self.p.dates) - 1)
        label = self.p.label
        columns += [(f'FF Count - {label}', 'ff', ('f_ff',)), (f'{label} Outage Min.', 'outage', ('f_sum',)),
                    (f'{label} UpTime', 'uptime', ('f_uptime',)), ('Bucket', 'bucket', ('f_bucket',))]
        columns += [(d, 'daily', ('day', i)) for i, d in enumerate(self.p.dates)]
        week_ranges = []
        for name, first, last in WEEKS:
            idx = [i for i, d in enumerate(self.p.dates) if first <= d.day <= last]
            week_ranges.append((f'Wk-{name.split()[-1]}', get_column_letter(first_daily + idx[0]), get_column_letter(first_daily + idx[-1])))
        columns += [(w, 'week_sum', ('w_sum', a, b)) for w, a, b in week_ranges]
        columns += [(w, 'week_up', ('w_up', a, b)) for w, a, b in week_ranges]
        columns += [(d, 'daily_up', ('d_up', get_column_letter(first_daily + i))) for i, d in enumerate(self.p.dates)]

        for col, (text, _) in enumerate(headers, start=1):
            _put(ws, 2, col, text or None, attr[col][0])
        for offset, (text, kind, _) in enumerate(columns):
            col = 22 + offset
            head, _, top, width = proto[kind]
            _put(ws, 2, col, datetime(text.year, text.month, text.day) if isinstance(text, date) else text, head,
                 'DD-MMM' if isinstance(text, date) else None)
            ws.column_dimensions[get_column_letter(col)].width = width
        cur_bucket_col = get_column_letter(22 + len(self.ds.months) * 4 + 3)  # FF, outage, uptime, bucket of the month

        mtd_dates = {self.ds.dates[c] for c in self.p.mtd_cols}
        for r, i in enumerate(self.scope.rows, start=3):
            site = self.ds.sites.iloc[i]
            detail = self.details.get((site['report_type'], site['circle'], _site_key(site['site_id'])), {'site': {}, 'monthly': {}})
            s, monthly = detail['site'], detail['monthly']
            values = [PROJECT_LABEL.get(site['report_type'], site['report_type']), s.get('circle_raw') or site['circle'], site['site_id'],
                      site['site_name'], site['oa'], site['ba'], s.get('on_air_raw') or ('Yes' if site['on_air'] else ''), site['eb'],
                      s.get('od_eb_working_status'), s.get('solar_logic_done')]
            values += [(monthly.get(m) or {}).get('om_start_raw') for m in om_months] + [None] * (7 - len(om_months))
            values += [site['ie_name'], s.get('ie_contact'), site['ci_name'], s.get('ci_contact')]
            for col, value in enumerate(values, start=1):
                _put(ws, r, col, value if value not in ('', None) else None, attr[col][1])
            for offset, (_, kind, how) in enumerate(columns):
                col = 22 + offset
                ws.cell(row=r, column=col)._style = copy(proto[kind][1]['_style'])
                value = self._uptime_cell(i, how, r, d0, d1, cur_bucket_col, monthly, mtd_dates)
                if value is not None:
                    ws.cell(row=r, column=col, value=value)
        last = max(3, 2 + len(self.scope.rows))
        for offset, (_, kind, _) in enumerate(columns):
            letter = get_column_letter(22 + offset)
            fn = 9 if kind in ('ff', 'outage', 'daily', 'week_sum') else 1 if kind in ('uptime', 'week_up', 'daily_up') else 3
            _put(ws, 1, 22 + offset, f'=SUBTOTAL({fn},{letter}3:{letter}{last})', proto[kind][2])
        for col in range(2, 22):
            letter = get_column_letter(col)
            ws.cell(row=1, column=col, value=f'=SUBTOTAL(3,{letter}3:{letter}{last})')
        ws.freeze_panes = 'A3'
        ws.auto_filter.ref = f'A2:{get_column_letter(21 + len(columns))}{last}'
        red = DifferentialStyle(font=Font(color='9C0006'), fill=PatternFill('solid', bgColor='FFC7CE'))
        ws.conditional_formatting.add(f'C3:C{last}', Rule(type='duplicateValues', dxf=red))

    def _uptime_cell(self, i, how, r, d0, d1, bucket_col, monthly, mtd_dates):
        kind = how[0]
        if kind == 'ff':
            return (monthly.get(how[1]) or {}).get('ff_count')
        if kind in ('m_outage', 'm_uptime', 'm_bucket'):
            value = self.ds.monthly_outage[i, how[1]]
            if np.isnan(value):
                return None
            if kind == 'm_outage':
                return float(value)
            up = 1 - value / (MINUTES_PER_DAY * self.ds.months[how[1]]['days'])
            return up if kind == 'm_uptime' else BUCKET_LABEL[bucket_ids(np.array([up * 100]))[0]]
        rng = f'{d0}{r}:{d1}{r}'
        if kind == 'f_ff':
            return f'=COUNTIF({rng},">0")'
        if kind == 'f_sum':
            return f'=IF(COUNT({rng})=0,"",SUM({rng}))'
        if kind == 'f_uptime':
            return f'=IF(COUNT({rng})=0,"",1-SUM({rng})/(1440*COUNT({rng})))'
        if kind == 'f_bucket':
            return _bucket_formula(f'{get_column_letter(_col_index(bucket_col) - 1)}{r}')
        if kind == 'day':
            day = self.p.dates[how[1]]
            value = self.ds.outage[i, self.ds.position(day)]
            return None if day not in mtd_dates or np.isnan(value) else float(value)
        if kind == 'w_sum':
            span = f'{how[1]}{r}:{how[2]}{r}'
            return f'=IF(COUNT({span})=0,"",SUM({span}))'
        if kind == 'w_up':
            span = f'{how[1]}{r}:{how[2]}{r}'
            return f'=IF(COUNT({span})=0,"",1-SUM({span})/(1440*COUNT({span})))'
        if kind == 'd_up':
            return f'=IF({how[1]}{r}="","",1-{how[1]}{r}/1440)'
        return None

    # -- summary sheets (calculated) ---------------------------------------------------------------------------------
    def _protos(self, ws, title, header, text, number, pct, total_text, total_number, total_pct):
        get = lambda ref: _style(ws[ref])  # noqa: E731
        return {'title': get(title), 'header': get(header), 'text': get(text), 'number': get(number), 'pct': get(pct),
                'total_text': get(total_text), 'total_number': get(total_number), 'total_pct': get(total_pct)}

    def _table(self, ws, top: int, left: int, title: str, header: list, rows: list[list], kinds: list[str], styles: dict,
               total: list | None = None) -> int:
        """Write a titled table; ``kinds`` per column: text / number / pct. Returns the next free row."""
        _put(ws, top, left, title, styles['title'])
        if len(header) > 1:
            ws.merge_cells(start_row=top, start_column=left, end_row=top, end_column=left + len(header) - 1)
        for c, value in enumerate(header):
            fmt = 'mmm-yy' if isinstance(value, datetime) else ('DD-MMM' if isinstance(value, date) else None)
            _put(ws, top + 1, left + c, value, styles['header'], fmt)
        r = top + 2
        for values in rows + ([total] if total else []):
            is_total = total is not None and values is total
            for c, value in enumerate(values):
                kind = kinds[c]
                proto = styles[('total_' if is_total else '') + kind]
                _put(ws, r, left + c, value, proto, '0.00%' if kind == 'pct' else ('#,##0' if kind == 'number' else None))
            r += 1
        if any(k == 'pct' for k in kinds) and rows:
            first = next(i for i, k in enumerate(kinds) if k == 'pct')
            ws.conditional_formatting.add(
                f'{get_column_letter(left + first)}{top + 2}:{get_column_letter(left + len(kinds) - 1)}{top + 1 + len(rows)}',
                ColorScaleRule(start_type='min', start_color='F8696B', mid_type='percentile', mid_value=50, mid_color='FFEB84',
                               end_type='max', end_color='63BE7B'))
        return r + 1

    def _label(self, project, circle) -> str:
        return circle if self.scope.report_type else f'{PROJECT_LABEL.get(project, project)} {circle}'

    def summ(self):
        ws = self.wb['Summ']
        styles = self._protos(ws, 'B3', 'B4', 'B5', 'C5', 'E5', 'B8', 'C8', 'E8')
        _clear_sheet(ws, keep_rows=1)
        months = self.months
        heads = [datetime(m['start'].year, m['start'].month, 1) for m in self.ds.months] + [f'{self.p.label} MTD']
        r = 3
        for project in [p for p in ('4G Saturation', 'LWE') if any(g[0] == p for g in self.groups)]:
            circles = [c for p, c in self.groups if p == project]
            name = PROJECT_LABEL.get(project, project)
            for title, population, count_label in ((f'{name} - Overall Up-Time (On-Air sites)', 'on_air', 'On-Air Done'),
                                                  (f'{name} - O&M Start - Up-Time', 'om_start', 'O&M Start Site count')):
                rows = []
                for c in circles + [None]:
                    sel = self.rows_for(project, c, population)
                    rows.append([c or 'Grand Total', len(self.rows_for(project, c)), len(sel)] + [self.uptime(sel, i) for _, i in months])
                r = self._table(ws, r, 2, title, ['Circle', 'Total Site count', count_label] + heads, rows[:-1],
                                ['text', 'number', 'number'] + ['pct'] * len(months), styles, rows[-1])
            for title, population, metric in ((f'{name} - Less than 60% Trend (On-Air sites)', 'on_air', 'lt60'),
                                              (f'{name} - Overall Outage Min. (On-Air sites)', 'on_air', 'outage'),
                                              (f'{name} - O&M Start Outage Min.', 'om_start', 'outage')):
                rows = []
                for c in circles + [None]:
                    sel = self.rows_for(project, c, population)
                    if metric == 'lt60':
                        rows.append([c or 'Grand Total'] + [_count(self.site_uptimes(sel, i), 'lt_60') for _, i in months])
                    else:
                        rows.append([c or 'Grand Total'] + [self.outage(sel, i) for _, i in months])
                r = self._table(ws, r, 2, title, ['Circle'] + heads, rows[:-1], ['text'] + ['number'] * len(months), styles, rows[-1])
        self._footnote(ws, r)

    def bucketization(self):
        ws = self.wb['Uptime Bucketization ']
        styles = self._protos(ws, 'B2', 'B3', 'B4', 'K4', 'K4', 'J4', 'P4', 'P4')
        _clear_sheet(ws, keep_rows=1)
        header = ['Month'] + [BUCKET_LABEL[b] for b in BUCKET_ORDER] + ['Grand Total']
        kinds = ['text'] + ['number'] * (len(BUCKET_ORDER) + 1)

        def table(rows_sel):
            out = []
            for label, i in self.months:
                ups = self.site_uptimes(rows_sel, i)
                counts = [_count(ups, b) for b in BUCKET_ORDER]
                out.append([label] + counts + [None if counts[0] is None else sum(counts)])  # blank month: no values
            return out
        r = self._table(ws, 2, 2, 'Uptime Bucketization Monthly Summary - O&M Start sites (selected scope)', header,
                        table(self.rows_for(population='om_start')), kinds, styles)
        for project, circle in self.groups:
            name = PROJECT_LABEL.get(project, project)
            r = self._table(ws, r, 2, f'Up-Time Bucketization - O&M Start sites - {name} {circle} Circle', header,
                            table(self.rows_for(project, circle, 'om_start')), kinds, styles)
        self._footnote(ws, r)

    def day_wise(self):
        ws = self.wb['Day wise Trend']
        styles = self._protos(ws, 'B2', 'B3', 'B4', 'C4', 'H4', 'B7', 'C7', 'H7')
        _clear_sheet(ws, keep_rows=1)
        windows = self.windows()
        dates = [self.ds.dates[c] for c in self.p.mtd_cols]
        header_tail = [f'{w} ({self.p.label})' for w, _ in windows] + list(dates)
        r = 2
        for title, population in (('Day wise Uptime Trend - Over On-Air Sites', 'on_air'), ('Day wise Uptime Trend - O&M Start Sites', 'om_start')):
            rows = []
            for project, circle in self.groups + [(None, None)]:
                sel = self.rows_for(project, circle, population)
                values = []
                for _, cols in windows:
                    block = self.ds.outage[np.ix_(sel, cols)]
                    value = uptime_pct(float(np.nansum(block)), int((~np.isnan(block)).sum()))
                    values.append(None if value is None else value / 100)
                for c in self.p.mtd_cols:
                    block = self.ds.outage[sel, c]
                    value = uptime_pct(float(np.nansum(block)), int((~np.isnan(block)).sum()))
                    values.append(None if value is None else value / 100)
                rows.append([self._label(project, circle) if project else 'Grand Total', len(sel)] + values)
            r = self._table(ws, r, 2, title, ['Circle', 'Sites'] + header_tail, rows[:-1],
                            ['text', 'number'] + ['pct'] * len(header_tail), styles, rows[-1])
        self._footnote(ws, r)

    def threshold_sheet(self, name: str, bucket: str, title: str):
        ws = self.wb[name]
        styles = self._protos(ws, 'B2', 'B3', 'B4', 'D4', 'E30', 'B17', 'D17', 'E33')
        _clear_sheet(ws, keep_rows=1)
        recent = self.months[-4:]  # the last three months and the month to date
        windows = self.windows()
        periods = [(lbl, ('month', i)) for lbl, i in recent] + [(w, ('cols', cols)) for w, cols in windows] + \
                  [(self.ds.dates[c], ('cols', [c])) for c in self.p.mtd_cols]
        heads = [h if isinstance(h, (date, str)) else h for h, _ in periods]
        counts, shares = [], []
        for project, circle in self.groups + [(None, None)]:
            sel = self.rows_for(project, circle, 'om_start')
            values = []
            for _, (kind, what) in periods:
                ups = self.site_uptimes(sel, what) if kind == 'month' else site_uptime(self.ds.outage[np.ix_(sel, what)])
                values.append(_count(ups, bucket))
            entity = PROJECT_LABEL.get(project, project) if project else 'Grand Total'
            counts.append([entity, circle or '', len(sel)] + values)
            shares.append([entity, circle or '', len(sel)] + [v / len(sel) if len(sel) and v is not None else None for v in values])
        kinds = ['text', 'text', 'number']
        r = self._table(ws, 2, 2, f'{title} - O&M Start sites (site count)', ['Entity', 'Circle', 'O&M Start'] + heads,
                        counts[:-1], kinds + ['number'] * len(periods), styles, counts[-1])
        r = self._table(ws, r, 2, f'{title} - O&M Start sites (% of O&M Start sites)', ['Entity', 'Circle', 'O&M Start'] + heads,
                        shares[:-1], kinds + ['pct'] * len(periods), styles, shares[-1])
        self._footnote(ws, r)

    def od_eb(self):
        ws = self.wb['OD - EB & NEB']
        styles = self._protos(ws, 'B2', 'G2', 'B6', 'G6', 'J6', 'B6', 'G6', 'J6')
        _clear_sheet(ws, keep_rows=1)
        if ('4G Saturation', 'OD') not in self.groups:
            ws.cell(row=2, column=2, value='OD 4G Saturation sites are not in the selected scope.').font = Font(italic=True)
            return
        base = self.rows_for('4G Saturation', 'OD', 'on_air')
        eb = self.ds.sites['eb'].astype(str).str.strip().str.upper().to_numpy()
        rows = []
        for label, flag in (('EB Site Uptime', 'EB'), ('Non EB Site Uptime', 'N-EB')):
            sel = base[eb[base] == flag]
            values = [self.uptime(sel, i) for _, i in self.months[-3:]]
            for c in self.p.mtd_cols:
                block = self.ds.outage[sel, c]
                value = uptime_pct(float(np.nansum(block)), int((~np.isnan(block)).sum()))
                values.append(None if value is None else value / 100)
            rows.append([label, len(sel)] + values)
        heads = [lbl for lbl, _ in self.months[-3:]] + [self.ds.dates[c] for c in self.p.mtd_cols]
        r = self._table(ws, 2, 2, f'OD - 4G Satu. - EB / Non EB Uptime (On-Air sites, EB column)', ['', 'Site count'] + heads,
                        rows, ['text', 'number'] + ['pct'] * len(heads), styles)
        ws.cell(row=r, column=2, value='"Unique site down" counts are not calculated: their definition is not part of the '
                                       'application data.').font = Font(italic=True, color='666666')
        self._footnote(ws, r + 1)

    def people(self, name: str, column: str, label: str):
        from .metrics import team_names
        ws = self.wb[name]
        header_cell = next((c for row in ws.iter_rows(max_row=4) for c in row if c.value in ('Circle',)), ws['B3'])
        styles = self._protos(ws, header_cell.coordinate, header_cell.coordinate, header_cell.coordinate, header_cell.coordinate,
                              header_cell.coordinate, header_cell.coordinate, header_cell.coordinate, header_cell.coordinate)
        styles['text'] = styles['number'] = styles['pct'] = {'_style': copy(ws['A1']._style), 'number_format': 'General'}
        _clear_sheet(ws, keep_rows=0)
        r = 2
        names = team_names(self.ds.sites[column]).to_numpy()
        for project, circle in self.groups:
            sel = self.rows_for(project, circle)
            rows = []
            for person in sorted(set(names[sel])):
                mine = sel[names[sel] == person]
                om = mine[self.om[np.searchsorted(self.scope.rows, mine)]]
                rows.append([circle, person, len(mine), len(om), self.uptime(om, None), self.outage(om, None)])
            sel_om = sel[self.om[np.searchsorted(self.scope.rows, sel)]]
            total = ['Total', '', len(sel), len(sel_om), self.uptime(sel_om, None), self.outage(sel_om, None)]
            r = self._table(ws, r, 2, f'{PROJECT_LABEL.get(project, project)} {circle} - {label.replace(" name", "")} performance '
                            f'({self.p.label} MTD, O&M Start sites)', ['Circle', label, 'Site Count', 'O&M Start ', 'Up-Time', 'Outage Min.'],
                            rows, ['text', 'text', 'number', 'number', 'pct', 'number'], styles, total)
        self._footnote(ws, r)

    def _footnote(self, ws, row: int):
        ws.cell(row=row, column=2, value=(f'Source: {self.source_label}. Scope: {self.scope.project_label}, {self.scope.circle_label}. '
                                         f'Month to date: {self.p.month:%d %b} to {self.p.day:%d %b %Y}. Uptime pools outage over '
                                         f'reported site-days; unreported days are excluded, never counted as zero.')
                ).font = Font(italic=True, size=9, color='666666')


def _count(uptimes: np.ndarray, bucket: str) -> int | None:
    """Sites in ``bucket``; None (blank) when no site has a value for the period, never 0."""
    if not len(uptimes) or np.isnan(uptimes).all():
        return None
    return int((bucket_ids(uptimes) == bucket).sum())


def _col_index(letter: str) -> int:
    from openpyxl.utils import column_index_from_string
    return column_index_from_string(letter)


def _bucket_formula(ref: str) -> str:
    """The workbook's bucket formula (thresholds from metrics.BUCKETS), blank when the uptime is blank."""
    expr = f'"{BUCKET_LABEL[BUCKET_ORDER[0]]}"'
    for bucket_id, _, label, bound in BUCKETS[1:]:
        expr = f'IF({ref}>={bound}%,"{label}",{expr})'
    return f'=IF({ref}="","",{expr})'


def consolidated_report(ds: Dataset, scope: Scope, day: date, source_label: str) -> tuple[str, bytes]:
    return ConsolidatedReport(ds, scope, day, source_label, source_details(ds)).build()
