"""Historical daily backfill from a day-wise outage workbook (e.g. "LWE Uptime Report day wise - Sept'26", sheet
"Day Wise Outage"): one row per site, a run of date columns with daily outage minutes and, optionally, a second run of
the same dates with the daily uptime fraction.

Only daily values are written, for sites already in the approved master; sites and monthly figures are never touched
and no site is ever created. Rules follow the Master-workbook importer:

- Columns are found by header text. The first run of date headers is outage minutes, the second (only when it repeats
  exactly the same dates) the uptime fraction, stored as a percentage. Blank cells and placeholders are "not reported"
  and are not written; text that is not a number is invalid and not written. Values are stored as in the source
  (outage above 1,440 or below 0 is flagged in the report, as the workbook importer and the dashboard do).
- A row resolves to a master site only when its site ID (normalised as ``parser.site_key``) belongs to one master
  site of the project and the row's circle, mapped with the established state-name aliases, is that site's circle.
  Unknown IDs, other circles, unknown circle names and repeated IDs are rejected and listed.
- Against stored values: identical -> skipped; stored without an outage value -> filled; different -> conflict, left
  unchanged and listed. Rerunning the same file therefore writes nothing.

``analyse`` reads only. ``commit`` repeats the analysis inside one transaction and writes, recording a
``DataImportBatch`` (Master workbook kind, daily values only) with a staged copy of the file.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from django.db import transaction
from django.utils import timezone
from openpyxl import load_workbook

from apps.accounts.audit import audit

from . import datasource
from .importer import PROJECTS, _Actor, _same, _stage
from .models import DataImportBatch, SiteDailyPerformance, UptimeSite
from .parser import _number, _pct, sha256, site_key

SHEET = 'Day Wise Outage'
ID_HEADERS = ('site id as per nirikshan', 'btsipid')  # the master's site ID column, in order of preference
MINUTES_PER_DAY = 1440
MAX_LISTED = 200


class DaywiseError(ValueError):
    """The file cannot be read as a day-wise outage sheet."""


def canonical_circle(name: str, project: str | None = None, resolver=None) -> str | None:
    """Circle code for a circle written as a code or a state name: Organization > Code Mapping, source "Day-wise outage
    report" (only established aliases; None when unknown)."""
    from apps.organization.services import AliasResolver
    return (resolver or AliasResolver('daywise_report')).resolve(name, project)


@dataclass
class Parsed:
    filename: str
    checksum: str
    sheet: str
    header_row: int
    id_column: str
    dates: list[date]
    has_uptime: bool
    rows: list[dict] = field(default_factory=list)  # {'row', 'site_id', 'circle_raw', 'days': {date: (outage, uptime_pct)}, 'invalid': [...]}
    file_totals: dict = field(default_factory=dict)  # row -> the sheet's own outage total for the month, when present


def _header(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return ' '.join(str(value).split()) if value is not None else ''


def _runs(headers: list) -> list[tuple[int, int]]:
    """Consecutive runs of date headers as (start, end) column ranges."""
    runs, start = [], None
    for i, h in enumerate(headers + ['']):
        if isinstance(h, date) and start is None:
            start = i
        elif not isinstance(h, date) and start is not None:
            runs.append((start, i))
            start = None
    return runs


def parse(path: Path, *, filename: str | None = None, sheet: str = SHEET) -> Parsed:
    try:
        wb = load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:  # not an xlsx, damaged, encrypted
        raise DaywiseError(f'The file cannot be opened as an Excel workbook ({type(exc).__name__}).') from exc
    try:
        if sheet not in wb.sheetnames:
            raise DaywiseError(f'No "{sheet}" sheet; found: {", ".join(wb.sheetnames)}.')
        grid = [list(r) for r in wb[sheet].iter_rows(values_only=True)]
    finally:
        wb.close()  # read-only workbooks keep the file open until closed
    for header_index, raw in enumerate(grid[:15]):
        headers = [_header(v) for v in raw]
        lower = [h.lower() if isinstance(h, str) else '' for h in headers]
        id_col = next((lower.index(name) for name in ID_HEADERS if name in lower), None)
        if id_col is not None and 'circle' in lower:
            break
    else:
        raise DaywiseError('No header row with "Circle" and a site ID column ("Site ID as per Nirikshan" or "btsIpId").')
    runs = _runs(headers)
    if not runs:
        raise DaywiseError('No date columns in the header row.')
    o_start, o_end = runs[0]
    dates = headers[o_start:o_end]
    if len(set(dates)) != len(dates):
        raise DaywiseError('The daily date columns repeat a date.')
    u_run = next((r for r in runs[1:] if headers[r[0]:r[1]] == dates), None)
    circle_col = lower.index('circle')
    # The month's own outage total: the "Outage Min" column before the "<Mon>'YY MTD" uptime column of the dates' month.
    month_total_col = None
    for i, h in enumerate(headers[:o_start]):
        if isinstance(h, str) and h.lower() == 'outage min' and i + 1 < len(headers):
            nxt = headers[i + 1]
            if isinstance(nxt, str) and dates[0].strftime('%b').lower() in nxt.lower() and str(dates[0].year)[2:] in nxt:
                month_total_col = i
    parsed = Parsed(filename=filename or path.name, checksum=sha256(path), sheet=sheet, header_row=header_index + 1,
                    id_column=headers[id_col], dates=list(dates), has_uptime=u_run is not None)
    for offset, raw in enumerate(grid[header_index + 1:], start=header_index + 2):
        if not any(v not in (None, '') for v in raw):
            continue
        cells = list(raw) + [None] * (len(headers) - len(raw))
        site_id = '' if cells[id_col] is None else str(cells[id_col]).strip()
        days, invalid = {}, []
        for k, day in enumerate(dates):
            outage, problem = _number(cells[o_start + k])
            if problem is not None:
                invalid.append((day, problem))
                continue
            if outage is None:
                continue  # not reported: nothing is written, never zero
            uptime = _number(cells[u_run[0] + k])[0] if u_run else None
            days[day] = (outage, _pct(uptime))
        parsed.rows.append({'row': offset, 'site_id': site_id, 'circle_raw': '' if cells[circle_col] is None else str(cells[circle_col]).strip(),
                            'days': days, 'invalid': invalid})
        if month_total_col is not None:
            parsed.file_totals[offset] = _number(cells[month_total_col])[0]
    return parsed


def analyse(parsed: Parsed, project: str) -> dict:
    """Classify every row and site/day against the master and the stored values. Reads only."""
    from apps.organization.services import AliasResolver
    circles = AliasResolver('daywise_report')
    if project not in PROJECTS:
        raise DaywiseError(f'Unknown project {project!r}; choose 4G Saturation or LWE.')
    master: dict[str, list[dict]] = {}
    for s in UptimeSite.objects.filter(project=project).values('id', 'circle', 'site_key', 'site_id'):
        master.setdefault(s['site_key'], []).append(s)
    other_projects = set(UptimeSite.objects.exclude(project=project).values_list('site_key', flat=True))
    counts = Counter()
    rejected, resolved, seen = [], {}, {}
    for r in parsed.rows:
        key = site_key(r['site_id']) if r['site_id'] else ''
        circle = canonical_circle(r['circle_raw'], project, circles)
        reason = None
        if not key:
            reason = ('missing_site_id', 'No site ID.')
        elif key in seen:
            reason = ('duplicate_site', f'Same site ID as row {seen[key]}; the first row is kept.')
        elif circle is None:
            reason = ('unknown_circle', f'Circle "{r["circle_raw"]}" is not a known circle name.')
        elif key not in master:
            reason = ('other_project', f'Belongs to another project, not {project}.') if key in other_projects else \
                ('unknown_site', f'Not in the {project} site master.')
        elif len(master[key]) > 1:
            reason = ('ambiguous_site', f'Matches {len(master[key])} {project} sites in different circles.')
        elif master[key][0]['circle'] != circle:
            reason = ('circle_mismatch', f'The master has this site in {master[key][0]["circle"]}, the file in {circle}.')
        if key and key not in seen:
            seen[key] = r['row']
        if reason:
            counts[reason[0]] += 1
            rejected.append({'row': r['row'], 'site_id': r['site_id'], 'circle': r['circle_raw'], 'code': reason[0], 'message': reason[1]})
            continue
        resolved[master[key][0]['id']] = r

    ids = list(resolved)
    stored = {}
    for i in range(0, len(ids), 5000):
        for d in SiteDailyPerformance.objects.filter(site_id__in=ids[i:i + 5000], date__in=parsed.dates).values('site_id', 'date', 'outage_minutes', 'uptime_pct'):
            stored[(d['site_id'], d['date'])] = (d['outage_minutes'], d['uptime_pct'])
    inserts, fills, conflicts, invalid_cells, flagged = [], [], [], [], []
    identical = not_reported = 0
    uptime_mismatch = 0
    for site_id, r in resolved.items():
        for day, problem in r['invalid']:
            invalid_cells.append({'row': r['row'], 'site_id': r['site_id'], 'date': day.isoformat(), 'value': problem})
        not_reported += len(parsed.dates) - len(r['days']) - len(r['invalid'])
        for day, (outage, uptime) in r['days'].items():
            if outage < 0 or outage > MINUTES_PER_DAY:
                flagged.append({'row': r['row'], 'site_id': r['site_id'], 'date': day.isoformat(), 'outage_minutes': outage})
            if uptime is not None and abs(uptime - 100 * (1 - outage / MINUTES_PER_DAY)) > 0.01:
                uptime_mismatch += 1
            old = stored.get((site_id, day))
            if old is None:
                inserts.append((site_id, day, outage, uptime))
            elif _same(old, (outage, uptime)):
                identical += 1
            elif old[0] is None:
                fills.append((site_id, day, outage, uptime))
            else:
                conflicts.append({'row': r['row'], 'site_id': r['site_id'], 'date': day.isoformat(), 'stored': old[0], 'file': outage,
                                  'stored_uptime_pct': old[1], 'file_uptime_pct': uptime})
    total_diff = sum(1 for r in resolved.values() if parsed.file_totals.get(r['row']) is not None
                     and abs(parsed.file_totals[r['row']] - sum(o for o, _ in r['days'].values())) > 0.01)
    by_circle = Counter(r_circle for r_circle in (canonical_circle(r['circle_raw'], project, circles) for r in resolved.values()))
    summary = {
        'project': project, 'file': parsed.filename, 'sheet': parsed.sheet, 'header_row': parsed.header_row, 'id_column': parsed.id_column,
        'dates': {'first': parsed.dates[0].isoformat(), 'last': parsed.dates[-1].isoformat(), 'count': len(parsed.dates)},
        'uptime_columns': parsed.has_uptime,
        'rows': len(parsed.rows), 'rows_resolved': len(resolved), 'rows_rejected': len(rejected), 'rejected_by_code': dict(counts),
        'circles': dict(sorted(by_circle.items())),
        'site_days': {'insert': len(inserts), 'fill_missing': len(fills), 'identical_skipped': identical, 'conflicts_not_changed': len(conflicts),
                      'invalid_not_written': len(invalid_cells), 'not_reported': not_reported},
        'flagged_out_of_range': len(flagged),
        'uptime_differs_from_outage': uptime_mismatch,
        'rows_whose_month_total_differs_from_days': total_diff if parsed.file_totals else None,
        'master_sites_not_in_file': sum(1 for s in master.values() for x in s if x['id'] not in resolved),
    }
    return {'summary': summary, 'rejected': rejected, 'conflicts': conflicts, 'invalid': invalid_cells, 'flagged': flagged,
            '_inserts': inserts, '_fills': fills}


def report(result: dict) -> dict:
    """The analysis without the internal write lists, with long lists shortened (for storage and printing)."""
    return {'summary': result['summary'], **{k: result[k][:MAX_LISTED] for k in ('rejected', 'conflicts', 'invalid', 'flagged')}}


def commit(path: Path, project: str, *, filename: str | None = None, user=None, allow_rejected: bool = False,
           via: str = 'command:import_daywise') -> DataImportBatch:
    """Write the resolved site/days in one transaction. Refuses when rows were rejected unless ``allow_rejected``."""
    name = filename or path.name
    staged, checksum = _stage(path, name)
    parsed = parse(staged, filename=name)
    with transaction.atomic():
        result = analyse(parsed, project)
        summary = result['summary']
        if summary['rows_resolved'] == 0:
            raise DaywiseError(f'No row of the file matches the {project} site master; nothing was written.')
        if summary['rows_rejected'] and not allow_rejected:
            raise DaywiseError(f'{summary["rows_rejected"]} rows could not be matched to the master ({summary["rejected_by_code"]}). '
                               'Review them, then confirm importing only the matched rows.')
        batch = DataImportBatch.objects.create(
            kind=DataImportBatch.Kind.MASTER_WORKBOOK, project=project, original_filename=name, checksum_sha256=checksum,
            sheet_name=parsed.sheet, stored_path=str(staged), imported_by=user, initiated_via=via,
            report={**report(result), 'options': {'project': project, 'daily_only': True, 'daywise': True}},
            rejected_count=summary['rows_rejected'], skipped_count=summary['site_days']['identical_skipped'],
        )
        SiteDailyPerformance.objects.bulk_create([
            SiteDailyPerformance(site_id=s, date=d, outage_minutes=o, uptime_pct=u, batch=batch) for s, d, o, u in result['_inserts']
        ], batch_size=5000)
        for s, d, o, u in result['_fills']:
            SiteDailyPerformance.objects.filter(site_id=s, date=d, outage_minutes__isnull=True).update(outage_minutes=o, uptime_pct=u, batch=batch)
        batch.status, batch.committed_at = DataImportBatch.Status.COMMITTED, timezone.now()
        batch.counts = {'daily_only': True, 'daily': {'inserted': len(result['_inserts']), 'filled': len(result['_fills']),
                                                      'unchanged': summary['site_days']['identical_skipped'],
                                                      'conflicts_not_changed': summary['site_days']['conflicts_not_changed']},
                        'rejected': summary['rows_rejected']}
        batch.save(update_fields=['status', 'committed_at', 'counts'])
    datasource.clear_cache()  # the database-backed dashboard rebuilds; the source setting is unchanged
    audit('import_committed', _Actor(user) if user else None, batch=batch.pk, file=name, daily_only=True, daywise=True,
          project=project, daily=batch.counts['daily'], rejected=summary['rows_rejected'])
    return batch
