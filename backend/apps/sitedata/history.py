"""Historical monthly Uptime import into MonthlySitePerformance (category historical_import).

For the months before the daily data layer (settings.SITEDATA_DAILY_FROM, September 2026) the Uptime Master workbooks
hold one monthly total per site: "<Mon-YY> Outage Min." with its Up-Time, FF Count, Bucket and O&M flag. These totals
are stored as written, beside (never instead of) the results calculated from daily records:

- category historical_import; reporting_days NULL (the workbook has no day count; never invented); calendar_days the
  days of the month; effective_from the 1st; availability_pct the workbook Up-Time; total_outage_minutes the workbook
  outage; the upload (import_batch), workbook row (source_row) and source values (FF Count, Bucket, O&M flag, column
  labels, the On-Air note) kept on the record.
- Eligibility is never a reason to reject: a value before the site's master On-Air date, for a site without one, or
  for a month the site went On-Air in is imported as written; its On-Air status is noted in source_values for audit.
- Validation (independent of eligibility): the site must be in the master (BSNL Site ID or an approved alternate ID)
  with the same project and circle, in the dashboard scope, on one source row per month; outage 0 to the minutes of the
  month (above that: held for review; negative: rejected); the outage must agree with the Up-Time over the full month
  (otherwise held); a blank cell stays missing (no record, never 0); a zero outage is a value. Months whose column is
  labelled MTD in a source are held unless confirmed as whole months. Months of the daily data layer are refused.
- Preview first (an UploadBatch of kind uptime_history with a staged copy), commit in one transaction under the
  data-layer write lock. Idempotent: an unchanged value is skipped; a changed one adds a revision (the earlier one
  stays, no longer current). retire() withdraws a committed upload's records and restores the earlier revisions;
  nothing is deleted.

Calculated categories never see these records: calculations.py, finalization and the finalized-month checks use
MonthlySitePerformance.DAILY_CATEGORIES, and the dashboard reads daily_derived only.
"""
from __future__ import annotations

import calendar
import csv
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from openpyxl import load_workbook

from apps.accounts.audit import audit

from . import exceptions, uploads
from .identifiers import key_of
from .models import MonthlySitePerformance, Site, UploadBatch

HIST = MonthlySitePerformance.Category.HISTORICAL_IMPORT
UP_TIME_REPORT = 'up_time_report'   # "<Mon-YY> Outage Min." / "<Mon-YY> Up-Time" columns (consolidated, 4G reports)
LWE_MONTHLY = 'lwe_monthly'         # "Outage Min" followed by its month's Up-Time column labelled "Jan'26" (LWE reports)
FORMATS = (UP_TIME_REPORT, LWE_MONTHLY)
CONSISTENCY_MINUTES = 1.0           # outage vs Up-Time over the full month
TOLERANCE = 1e-6
MONTHS = {'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6, 'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12}

# Outcome codes. Imported: new, changed. Not imported: unchanged, blank, and the exceptions below.
NEW, CHANGED, UNCHANGED, BLANK = 'new', 'changed', 'unchanged', 'blank'
REJECTED = {
    'unmatched_site': 'Add the site to the Consolidation Matrix or approve an alternate ID, then import again.',
    'project_mismatch': 'Check the source row and the site master project; correct the source or the master.',
    'circle_mismatch': 'Check the source row and the site master circle; correct the source or the master.',
    'outside_scope': 'The site is outside the dashboard scope; confirm whether it should be reported.',
    'duplicate_row': 'The site is on more than one row for the month; keep one row in the source.',
    'negative_outage': 'Correct the source value (outage cannot be negative).',
    'daily_month': 'Not imported: this month comes from the daily records.',
}
HELD = {
    'over_month_minutes': 'Review: the outage exceeds the minutes of the month (possibly rounding); confirm or correct the value.',
    'uptime_inconsistent': 'Investigate: the outage does not match the Up-Time over the full month.',
    'missing_uptime': 'Review: the outage has no Up-Time; confirm the value.',
    'mtd_unconfirmed': 'Confirm whether the month-to-date column covers the whole month, then import with the month confirmed.',
}
ACTIONS = {**REJECTED, **HELD}


class HistoryError(Exception):
    pass


def daily_from() -> date:
    year, month = (int(x) for x in getattr(settings, 'SITEDATA_DAILY_FROM', '2026-09').split('-'))
    return date(year, month, 1)


def month_minutes(month: date) -> int:
    return 1440 * calendar.monthrange(month.year, month.month)[1]


@dataclass
class Cell:
    """One site-month value of a source row (outage None: blank in the source)."""
    technology: str
    circle: str
    site_id: str
    month: date
    row: int
    outage: float | None
    uptime_pct: float | None
    values: dict = field(default_factory=dict)  # source values as written (FF Count, Bucket, O&M flag, labels)


@dataclass
class Source:
    cells: list[Cell]
    labels: dict  # (technology or '*', month) -> column label(s) as written
    mtd: set      # (technology, month) whose column is labelled MTD


# --- Reading ---------------------------------------------------------------------------------------

def read_up_time_report(path: Path, allocation: dict[str, list[date]], default_project: str | None = None) -> Source:
    """The Up-Time Report sheet (consolidated / 4G report layout), through the existing parser."""
    from .sources.uptime_report import ParseError, parse_workbook
    try:
        parsed = parse_workbook(path, default_project=default_project)
    except ParseError as exc:
        raise HistoryError(str(exc)) from exc
    # A site on several rows: the parser keeps the first row and reports the others; every row of it is refused here.
    repeated = [i for i in parsed.issues if i['code'] == 'duplicate_key']
    repeated_keys = {key_of(i['site_id']) for i in repeated}
    cells = []
    for key, site in parsed.sites.items():
        for month in allocation.get(site['project'], ()):
            rec = parsed.monthly[key].get(month)
            if rec is None:
                continue
            values = {'ff_count': rec['ff_count'], 'bucket': rec['bucket'] or None, 'om_start_flag': rec['om_start_raw'],
                      'uptime_pct': rec['uptime_pct'], 'duplicate_row': True if key_of(site['site_id']) in repeated_keys else None}
            cells.append(Cell(site['project'], site['circle'], site['site_id'], month, site['source_row'], rec['outage_minutes'], rec['uptime_pct'],
                              {k: v for k, v in values.items() if v is not None}))
    kept = {key_of(s['site_id']): s for s in parsed.sites.values()}
    for issue in repeated:
        site = kept.get(key_of(issue['site_id']))
        for month in allocation.get(site['project'], ()) if site else ():
            cells.append(Cell(site['project'], site['circle'], issue['site_id'], month, issue['row'], None, None, {'duplicate_row': True}))
    labels = {('*', m): f'{m:%b-%y} Outage Min.' for m in parsed.months}
    return Source(cells, labels, set())


def read_lwe_monthly(path: Path, allocation: dict[str, list[date]]) -> Source:
    """LWE reports: a header row with "btsIpId" and "Circle"; each "Outage Min" column is followed by its month's Up-Time
    fraction, whose header names the month ("Jan'26", "July'26 MTD"). Circles are state names (day-wise report aliases)."""
    from apps.organization.services import AliasResolver
    circles = AliasResolver('daywise_report')
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = next((book[s] for s in ('Up-Time Report', 'Day Wise Outage') if s in book.sheetnames), None)
        if sheet is None:
            raise HistoryError(f'{path.name}: no "Up-Time Report" or "Day Wise Outage" sheet (sheets: {", ".join(book.sheetnames)}).')
        rows = list(sheet.iter_rows(values_only=True))
    finally:
        book.close()
    header_index = next((i for i, r in enumerate(rows[:10]) if any(isinstance(v, str) and v.strip() in ('btsIpId', 'Site ID as per Nirikshan') for v in r)), None)
    if header_index is None:
        raise HistoryError(f'{path.name}: no header row with a "btsIpId" or "Site ID as per Nirikshan" column.')
    header = [str(v).strip() if v is not None else '' for v in rows[header_index]]
    site_col = next(i for i, h in enumerate(header) if h in ('btsIpId', 'Site ID as per Nirikshan'))
    circle_col = next((i for i, h in enumerate(header) if h.lower() == 'circle'), None)
    if circle_col is None:
        raise HistoryError(f'{path.name}: no "Circle" column on the header row.')
    columns, labels, mtd = {}, {}, set()
    for i, h in enumerate(header[:-1]):
        match = re.match(r"([A-Za-z]{3})[A-Za-z]*'(\d{2})", header[i + 1]) if h.lower().startswith('outage min') else None
        if match and match.group(1).lower() in MONTHS:
            month = date(2000 + int(match.group(2)), MONTHS[match.group(1).lower()], 1)
            columns[month] = i
            labels[('LWE', month)] = header[i + 1]
            if 'mtd' in header[i + 1].lower():
                mtd.add(('LWE', month))
    cells, seen = [], Counter()
    data = rows[header_index + 1:]
    for offset, row in enumerate(data):
        raw_id = row[site_col] if site_col < len(row) else None
        if raw_id is None or not str(raw_id).strip():
            continue
        seen[key_of(str(raw_id))] += 1
    for offset, row in enumerate(data):
        raw_id = row[site_col] if site_col < len(row) else None
        if raw_id is None or not str(raw_id).strip():
            continue
        excel_row = header_index + 2 + offset
        circle_raw = str(row[circle_col]).strip() if row[circle_col] is not None else ''
        circle = circles.resolve(circle_raw, 'LWE') or circle_raw
        for month in allocation.get('LWE', ()):
            if month not in columns:
                continue
            i = columns[month]
            outage, fraction = row[i], row[i + 1] if i + 1 < len(row) else None
            outage = float(outage) if isinstance(outage, (int, float)) else None
            uptime = round(float(fraction) * 100, 6) if isinstance(fraction, (int, float)) else None
            values = {'uptime_pct': uptime, 'column_label': labels[('LWE', month)], 'circle_as_written': circle_raw}
            if seen[key_of(str(raw_id))] > 1:
                values['duplicate_row'] = True
            cells.append(Cell('LWE', circle, str(raw_id).strip(), month, excel_row, outage, uptime, {k: v for k, v in values.items() if v is not None}))
    return Source(cells, labels, mtd)


def read(path: Path, fmt: str, allocation: dict[str, list[date]], default_project: str | None = None) -> Source:
    if not path.is_file():
        raise HistoryError(f'Source file not found: {path}')
    if fmt == UP_TIME_REPORT:
        return read_up_time_report(path, allocation, default_project)
    if fmt == LWE_MONTHLY:
        return read_lwe_monthly(path, allocation)
    raise HistoryError(f'Unknown source format {fmt!r}; use one of {", ".join(FORMATS)}.')


# --- Analysis ------------------------------------------------------------------------------------

def _on_air_note(site: Site, month: date) -> str:
    end = month.replace(day=calendar.monthrange(month.year, month.month)[1])
    if site.on_air_date is None:
        return 'no_on_air_date'
    if site.on_air_date > end:
        return 'before_on_air'
    if site.on_air_date > month:
        return 'on_air_during_month'
    return 'on_air_whole_month'


def analyse(path: Path, fmt: str, allocation: dict[str, list[date]], *, default_project: str | None = None,
            confirmed_full_months: set | frozenset = frozenset(), held_mtd: set | frozenset = frozenset(),
            cross_checks: list[tuple[Path, str, dict]] | None = None) -> dict:
    """Validate a source against the site master and the stored historical records. Reads only.

    ``held_mtd``: (technology, month) labelled MTD in another source (e.g. the LWE report for the months the consolidated
    workbook supplies); held unless in ``confirmed_full_months``. ``cross_checks``: other sources of the same months whose
    values are compared (reported, never imported)."""
    from .unmatched import site_lookup
    source = read(path, fmt, allocation, default_project)
    sites = site_lookup()
    start = daily_from()
    hold_mtd = (set(source.mtd) | set(held_mtd)) - set(confirmed_full_months)
    rows_per_site = Counter((key_of(c.site_id), c.technology, c.month) for c in source.cells)
    current = current_historical({c.month for c in source.cells})

    planned, items = [], []
    by_month: dict = defaultdict(Counter)
    by_circle: dict = defaultdict(Counter)
    totals: dict = defaultdict(float)
    outcome = Counter()
    on_air = Counter()
    for c in source.cells:
        site = sites.get(key_of(c.site_id))
        code = None
        if c.values.get('duplicate_row') or (c.technology and rows_per_site[(key_of(c.site_id), c.technology, c.month)] > 1):
            code = 'duplicate_row'
        elif c.month >= start:
            code = 'daily_month'
        elif site is None:  # reported even when the cell is blank: the site must be resolved before any later import
            code = 'unmatched_site'
        elif site.technology != c.technology:
            code = 'project_mismatch'
        elif site.circle != c.circle:
            code = 'circle_mismatch'
        elif site.reporting_scope != Site.Scope.DASHBOARD:
            code = 'outside_scope'
        elif c.outage is None:
            code = BLANK
        elif c.outage < 0:
            code = 'negative_outage'
        elif c.outage > month_minutes(c.month):
            code = 'over_month_minutes'
        elif c.uptime_pct is None:
            code = 'missing_uptime'
        elif abs(c.outage - month_minutes(c.month) * (1 - c.uptime_pct / 100)) > CONSISTENCY_MINUTES:
            code = 'uptime_inconsistent'
        elif (c.technology, c.month) in hold_mtd:
            code = 'mtd_unconfirmed'
        if code is None:
            note = _on_air_note(site, c.month)
            on_air[note] += 1
            values = {**c.values, 'on_air_note': note}
            old = current.get((site.pk, c.month))
            if old is not None and _same(old, c, values):
                code = UNCHANGED
            else:
                code = CHANGED if old is not None else NEW
                planned.append((site, c, values, old))
                totals[(c.month, c.technology)] += c.outage
        outcome[code] += 1
        by_month[(c.month, c.technology)][code] += 1
        by_circle[(c.technology, c.circle)][code] += 1
        if code in ACTIONS:
            items.append({'code': code, 'status': 'rejected' if code in REJECTED else 'held', 'technology': c.technology or (site.technology if site else ''),
                          'circle': c.circle or (site.circle if site else ''), 'site_id': c.site_id, 'month': c.month, 'outage': c.outage,
                          'uptime_pct': c.uptime_pct, 'source_file': path.name, 'row': c.row, 'issue': _issue(code, c),
                          'action': ACTIONS[code]})
    report = {
        'source_file': path.name, 'format': fmt, 'allocation': {t: [m.isoformat() for m in ms] for t, ms in allocation.items()},
        'source_cells': len(source.cells), 'outcome': dict(outcome), 'ready': outcome[NEW] + outcome[CHANGED],
        'held_mtd_months': sorted(f'{t} {m:%b-%y}' for t, m in hold_mtd),
        'on_air_notes': dict(on_air),
        'by_month': [{'month': m.isoformat(), 'technology': t, **dict(st), 'ready_outage_minutes': round(totals[(m, t)], 2)}
                     for (m, t), st in sorted(by_month.items())],
        'by_circle': [{'technology': t, 'circle': ci, **dict(st)} for (t, ci), st in sorted(by_circle.items())],
        'cross_checks': [cross_check(source, *spec) for spec in cross_checks or ()],
        'source_labels': {f'{t} {m:%b-%y}': label for (t, m), label in sorted(source.labels.items(), key=lambda kv: (kv[0][1], kv[0][0]))},
    }
    return {'report': report, 'planned': planned, 'items': items}


def current_historical(months) -> dict:
    """(site id, month) -> the current historical record of those months."""
    return {(m.site_id, m.month): m for m in MonthlySitePerformance.objects.filter(calculation_category=HIST, is_current=True, month__in=months)}


def _same(old: MonthlySitePerformance, c: Cell, values: dict) -> bool:
    compared = ('ff_count', 'bucket', 'om_start_flag', 'uptime_pct')
    return (abs(old.total_outage_minutes - c.outage) <= TOLERANCE and abs(old.availability_pct - c.uptime_pct) <= TOLERANCE
            and all(old.source_values.get(k) == values.get(k) for k in compared))


def _issue(code: str, c: Cell) -> str:
    limit = month_minutes(c.month)
    if code == 'over_month_minutes':
        return f'Outage {c.outage:,.2f} min exceeds the {limit:,} minutes of {c.month:%b %Y}.'
    if code == 'uptime_inconsistent':
        expected = limit * (1 - c.uptime_pct / 100)
        return f'Outage {c.outage:,.2f} min; the Up-Time {c.uptime_pct:.4f}% over the full month gives {expected:,.2f} min.'
    if code == 'negative_outage':
        return f'Outage {c.outage:,.2f} min is negative.'
    if code == 'mtd_unconfirmed':
        return f'{c.month:%b %Y} is labelled month-to-date (MTD) in a source; not confirmed as the whole month.'
    if code == 'daily_month':
        return f'{c.month:%b %Y} is in the daily data layer (from {daily_from():%b %Y}).'
    return {'unmatched_site': 'Site ID not in the site master or its approved alternate IDs.',
            'project_mismatch': 'Project differs from the site master.', 'circle_mismatch': 'Circle differs from the site master.',
            'outside_scope': 'Site is outside the dashboard scope.', 'duplicate_row': 'More than one source row for the site and month.',
            'missing_uptime': 'Outage given without an Up-Time value.'}.get(code, code)


def cross_check(primary: Source, path: Path, fmt: str, allocation: dict[str, list[date]]) -> dict:
    """Compare the primary source's values with another source of the same months (by technology, site and month)."""
    other = read(path, fmt, allocation, '4G Saturation' if fmt == UP_TIME_REPORT and '4G Saturation' in allocation else None)
    mine = {(c.technology, key_of(c.site_id), c.month): c.outage for c in primary.cells}
    result: dict = defaultdict(Counter)
    for c in other.cells:
        if not c.technology:
            continue
        label = f'{c.technology} {c.month:%b-%y}'
        key = (c.technology, key_of(c.site_id), c.month)
        if key not in mine:
            result[label]['only_in_other'] += 1
        elif mine[key] is None and c.outage is None:
            result[label]['both_blank'] += 1
        elif mine[key] is None or c.outage is None:
            result[label]['blank_in_one'] += 1
        else:
            result[label]['equal' if abs(mine[key] - c.outage) <= 0.5 else 'different'] += 1
    return {'source_file': path.name, 'months': {k: dict(v) for k, v in sorted(result.items())}}


def write_exception_csv(items: list[dict], target: Path) -> Path:
    """The review list: one row per value not imported (blank cells excluded), with the recommended action."""
    columns = ('status', 'code', 'site_id', 'technology', 'circle', 'month', 'outage', 'uptime_pct', 'source_file', 'row', 'issue', 'action')
    with open(target, 'w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for item in sorted(items, key=lambda i: (i['status'], i['code'], i['technology'], i['circle'], i['site_id'], i['month'])):
            writer.writerow({**{k: item.get(k) for k in columns}, 'month': item['month'].strftime('%b %Y')})
    return target


# --- Preview, commit, retire ---------------------------------------------------------------------------

def _options(fmt, allocation, default_project, confirmed_full_months, held_mtd) -> dict:
    return {'format': fmt, 'allocation': {t: [m.isoformat() for m in ms] for t, ms in allocation.items()}, 'default_project': default_project,
            'confirmed_full_months': sorted([t, m.isoformat()] for t, m in confirmed_full_months),
            'held_mtd': sorted([t, m.isoformat()] for t, m in held_mtd)}


def _from_options(options: dict) -> dict:
    return {'fmt': options['format'], 'allocation': {t: [date.fromisoformat(m) for m in ms] for t, ms in options['allocation'].items()},
            'default_project': options.get('default_project'),
            'confirmed_full_months': {(t, date.fromisoformat(m)) for t, m in options.get('confirmed_full_months', [])},
            'held_mtd': {(t, date.fromisoformat(m)) for t, m in options.get('held_mtd', [])}}


def _counts(analysis: dict) -> dict:
    outcome = analysis['report']['outcome']
    return {'received': analysis['report']['source_cells'], 'accepted': outcome.get(NEW, 0) + outcome.get(CHANGED, 0),
            'duplicate': outcome.get(UNCHANGED, 0) + outcome.get('duplicate_row', 0), 'unmatched': outcome.get('unmatched_site', 0),
            'rejected': sum(outcome.get(c, 0) for c in REJECTED if c not in ('unmatched_site', 'duplicate_row')),
            'conflict': sum(outcome.get(c, 0) for c in HELD), 'superseded': outcome.get(CHANGED, 0)}


def _shared_items(analysis: dict) -> list[dict]:
    return [exceptions.record(source_file=i['source_file'], code=i['code'], message=i['issue'], row=i['row'], site_id=i['site_id'],
                              circle=i['circle'], report_date=i['month'], identifier=i['technology'], value=i['outage'],
                              severity=exceptions.REJECTED if i['status'] == 'rejected' else exceptions.REVIEW, related=i['action'])
            for i in analysis['items']]


def preview(path: Path, fmt: str, allocation: dict[str, list[date]], *, user=None, default_project: str | None = None,
            confirmed_full_months: set | frozenset = frozenset(), held_mtd: set | frozenset = frozenset(), cross_checks=None) -> UploadBatch:
    """Stage the source and record its analysis as a previewed uptime_history upload (no monthly record is written)."""
    analysis = analyse(path, fmt, allocation, default_project=default_project, confirmed_full_months=confirmed_full_months,
                       held_mtd=held_mtd, cross_checks=cross_checks)
    batch = uploads.new_batch(UploadBatch.Kind.UPTIME_HISTORY, path, path.name, user)
    earlier = UploadBatch.objects.filter(kind=UploadBatch.Kind.UPTIME_HISTORY, checksum_sha256=batch.checksum_sha256,
                                         processing_status=UploadBatch.Processing.COMMITTED).exclude(pk=batch.pk).values_list('pk', flat=True)
    report = {**analysis['report'], 'options': _options(fmt, allocation, default_project, set(confirmed_full_months), set(held_mtd)),
              'already_imported': list(earlier)}
    uploads.record_preview(batch, _counts(analysis), report, exception_items=_shared_items(analysis))
    audit('sitedata.history_previewed', None, batch=batch.pk, file=path.name, ready=analysis['report']['ready'])
    return batch


def commit(batch: UploadBatch, *, user=None, request=None) -> UploadBatch:
    """Write the previewed upload's new and changed values (analysed again inside the write lock), in one transaction."""
    if batch.kind != UploadBatch.Kind.UPTIME_HISTORY:
        raise HistoryError(f'Upload #{batch.pk} is not a historical monthly import.')
    with uploads.committing(batch) as locked:
        options = _from_options(locked.report['options'])
        analysis = analyse(uploads.staged_file(locked), **options)
        now = timezone.now()
        keys = {(site.pk, c.month) for site, c, _, _ in analysis['planned']}
        latest = {(r['site_id'], r['month']): r['n'] for r in MonthlySitePerformance.objects.filter(
            calculation_category=HIST, month__in={m for _, m in keys}).values('site_id', 'month').annotate(n=Max('revision'))}
        retired, created = [], []
        for site, c, values, old in analysis['planned']:
            if old is not None:
                retired.append(old.pk)
            created.append(MonthlySitePerformance(
                site=site, month=c.month, technology=c.technology, calculation_category=HIST, total_outage_minutes=c.outage,
                availability_pct=c.uptime_pct, reporting_days=None, calendar_days=calendar.monthrange(c.month.year, c.month.month)[1],
                effective_from=c.month, source_batches=[locked.pk], revision=latest.get((site.pk, c.month), 0) + 1, is_current=True,
                import_batch=locked, source_row=c.row, source_values=values))
        MonthlySitePerformance.objects.filter(pk__in=retired).update(is_current=False)
        MonthlySitePerformance.objects.bulk_create(created, batch_size=2000)
        outcome = analysis['report']['outcome']
        uploads.mark_committed(locked, {'committed': {'created': outcome.get(NEW, 0), 'revised': outcome.get(CHANGED, 0),
                                                      'unchanged': outcome.get(UNCHANGED, 0), 'at': now.isoformat()}})
    audit('sitedata.history_committed', request, batch=locked.pk, file=locked.original_filename, created=outcome.get(NEW, 0),
          revised=outcome.get(CHANGED, 0), unchanged=outcome.get(UNCHANGED, 0))
    from . import portfolio
    portfolio.clear_cache()
    return locked


def retire(batch: UploadBatch, *, reason: str, user=None, request=None) -> dict:
    """Withdraw a committed historical upload: its current records stop being current and, for each, the latest earlier
    revision of a non-retired upload becomes current again. Nothing is deleted."""
    if batch.kind != UploadBatch.Kind.UPTIME_HISTORY or batch.processing_status != UploadBatch.Processing.COMMITTED:
        raise HistoryError(f'Upload #{batch.pk} is not a committed historical monthly import.')
    if not (reason or '').strip():
        raise HistoryError('Give the reason for retiring the upload.')
    with transaction.atomic():
        uploads.write_lock()
        locked = UploadBatch.objects.select_for_update().get(pk=batch.pk)
        if locked.processing_status != UploadBatch.Processing.COMMITTED:
            raise HistoryError(f'Upload #{locked.pk} is no longer committed.')
        mine = list(MonthlySitePerformance.objects.filter(import_batch=locked, is_current=True))
        MonthlySitePerformance.objects.filter(pk__in=[r.pk for r in mine]).update(is_current=False)
        restored = 0
        for r in mine:
            earlier = (MonthlySitePerformance.objects.filter(site_id=r.site_id, month=r.month, calculation_category=HIST, revision__lt=r.revision)
                       .exclude(import_batch__processing_status=UploadBatch.Processing.RETIRED).exclude(import_batch=locked)
                       .order_by('-revision').first())
            if earlier is not None:
                earlier.is_current = True
                earlier.save(update_fields=['is_current'])
                restored += 1
        locked.processing_status = UploadBatch.Processing.RETIRED
        locked.report = {**locked.report, 'retired': {'at': timezone.now().isoformat(), 'reason': reason.strip(), 'withdrawn': len(mine),
                                                      'restored': restored, 'by': user.get_username() if user else None}}
        locked.save(update_fields=['processing_status', 'report'])
    audit('sitedata.history_retired', request, batch=locked.pk, withdrawn=len(mine), restored=restored, reason=reason.strip())
    from . import portfolio
    portfolio.clear_cache()
    return {'withdrawn': len(mine), 'restored': restored}


# --- The approved source plan --------------------------------------------------------------------

def _months(first: date, last: date) -> list[date]:
    out, m = [], first
    while m <= last:
        out.append(m)
        m = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
    return out


def default_plan(consolidated: Path | None = None, lwe: Path | None = None, g4_check: Path | None = None) -> list[dict]:
    """The source allocation (no overlap, so no duplicate import): 4G Oct-25 to Aug-26 and LWE Apr-26 to Aug-26 from the
    consolidated workbook (cross-checked against the 4G report and the LWE report); LWE Jan-26 to Mar-26 from the LWE
    report, the only source of those months. Months the LWE report labels MTD are held for both files."""
    data = Path(settings.DATA_DIR)
    consolidated = consolidated or data / 'raw' / "4G_LWE_Consolidated_Oct'26-Last_Changes.xlsx"
    lwe = lwe or data / 'processed' / 'sitedata' / '20261104-182658-uptime_master-5ca7396ce0.xlsx'  # "LWE Uptime Report - Oct'26.xlsx"
    g4_check = g4_check or data / 'raw' / 'RJ, MP & OD - Uptime Report- Oct-26.xlsx'
    missing = [str(p) for p in (consolidated, lwe, g4_check) if not p.is_file()]
    if missing:
        raise HistoryError('Source file(s) not found: ' + '; '.join(missing))
    g4 = _months(date(2025, 10, 1), date(2026, 8, 1))
    lwe_cons, lwe_report = _months(date(2026, 4, 1), date(2026, 8, 1)), _months(date(2026, 1, 1), date(2026, 3, 1))
    held = read_lwe_monthly(lwe, {'LWE': lwe_cons + lwe_report}).mtd
    return [
        {'path': consolidated, 'fmt': UP_TIME_REPORT, 'allocation': {'4G Saturation': g4, 'LWE': lwe_cons}, 'held_mtd': held,
         'cross_checks': [(g4_check, UP_TIME_REPORT, {'4G Saturation': g4}), (lwe, LWE_MONTHLY, {'LWE': lwe_cons})]},
        {'path': lwe, 'fmt': LWE_MONTHLY, 'allocation': {'LWE': lwe_report}, 'held_mtd': held, 'cross_checks': []},
    ]
