"""Two-step import of an Up-Time Report workbook into PostgreSQL: preview, then an explicit commit.

preview(): stage a copy of the upload(s), parse, validate and report; nothing is written to the
business tables. commit(): re-parse the staged file (checksum checked), then insert new records
and update changed ones in one transaction. Unchanged records are not written, so importing the
same file twice changes nothing. Existing records are never deleted.
"""
from __future__ import annotations

import logging
import shutil
from datetime import date, datetime
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.audit import audit

from . import datasource
from .models import DataImportBatch, SiteDailyPerformance, SiteMonthlyPerformance, UptimeSite
from .parser import MONTH_FIELDS, SITE_FIELDS, ParsedWorkbook, ParseError, parse_workbook, sha256, summary
from .reconcile import compare

logger = logging.getLogger(__name__)
CHUNK = 5000
RECONCILIATION_PROJECT = '4G Saturation'  # the RJ, MP & OD report covers 4G Saturation sites only
CONFLICT_CHOICES = ('primary', 'reconciliation')
PROJECTS = ('4G Saturation', 'LWE')


class ImportRejected(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class _Actor:
    """Minimal request stand-in so audit() can name the user (commands pass no request)."""

    def __init__(self, user):
        self.user = user
        self.META = {}


def staging_dir() -> Path:
    path = Path(settings.DATA_DIR) / 'processed' / 'imports'
    path.mkdir(parents=True, exist_ok=True)
    return path


def _stage(source: Path, original_name: str) -> tuple[Path, str]:
    checksum = sha256(source)
    target = staging_dir() / f"{datetime.now():%Y%m%d-%H%M%S}-{checksum[:10]}{Path(original_name).suffix.lower() or '.xlsx'}"
    shutil.copyfile(source, target)
    return target, checksum


def _parse(path: Path, name: str, *, reconciliation: bool = False, project: str | None = None) -> ParsedWorkbook:
    try:
        return parse_workbook(path, filename=name, default_project=RECONCILIATION_PROJECT if reconciliation else project)
    except ParseError as exc:
        raise ImportRejected(f'{name}: {exc}') from exc


def preview(primary: Path, primary_name: str, *, user=None, reconciliation: Path | None = None,
            reconciliation_name: str = '', via: str = 'api', project: str | None = None, daily_only: bool = False) -> DataImportBatch:
    """Stage and validate; returns a PREVIEWED batch whose report is shown before commit.

    ``project``: for a sheet without a Project column (e.g. the RJ, MP & OD report: 4G Saturation).
    ``daily_only``: write only daily values, for sites already in the database (e.g. a previous
    month's workbook); site details and monthly figures are left as they are.
    """
    if project is not None and project not in PROJECTS:
        raise ImportRejected(f'Unknown project {project!r}; choose 4G Saturation or LWE.')
    if daily_only and reconciliation is not None:
        raise ImportRejected('A daily-values-only import takes one workbook; leave the second report empty.')
    staged, checksum = _stage(primary, primary_name)
    parsed = _parse(staged, primary_name, project=project)
    report = {'primary': {**summary(parsed), 'all_issues': parsed.issues[:5000]}, 'database_effect': database_effect(parsed),
              'options': {'project': project, 'daily_only': daily_only}}
    if daily_only:
        report['daily_effect'] = daily_effect(parsed)
    batch = DataImportBatch(original_filename=primary_name, checksum_sha256=checksum, sheet_name=parsed.sheet,
                            stored_path=str(staged), imported_by=user, initiated_via=via)
    if reconciliation is not None:
        staged_other, other_checksum = _stage(reconciliation, reconciliation_name)
        other = _parse(staged_other, reconciliation_name, reconciliation=True)
        report['reconciliation'] = {**summary(other), 'all_issues': other.issues[:5000]}
        report['comparison'] = compare(parsed, other)
        batch.reconciliation_filename, batch.reconciliation_checksum = reconciliation_name, other_checksum
        batch.reconciliation_path = str(staged_other)
    previous = DataImportBatch.objects.filter(status=DataImportBatch.Status.COMMITTED, checksum_sha256=checksum).first()
    if previous:
        report['already_imported'] = {'batch': previous.pk, 'committed_at': previous.committed_at.isoformat()}
    batch.report = report
    batch.rejected_count = parsed.rejected
    batch.skipped_count = sum(parsed.skipped.values())
    batch.save()
    audit('import_previewed', _Actor(user) if user else None, batch=batch.pk, file=primary_name,
          sites=len(parsed.sites), rejected=parsed.rejected)
    return batch


def daily_effect(parsed: ParsedWorkbook) -> dict:
    """For a daily-only import: which sites can receive values, and whether the daily values add up to the monthly totals."""
    ids = {(s['project'], s['circle'], s['site_key']): s['id'] for s in UptimeSite.objects.values('id', 'project', 'circle', 'site_key')}
    known = [k for k in parsed.sites if k in ids]
    months = sorted({d[:7] for m in parsed.daily_months.values() for d in m['reported_dates']})
    checks = {}
    for key in months:
        month = date.fromisoformat(key + '-01')
        db_totals = dict(SiteMonthlyPerformance.objects.filter(month=month, site_id__in=[ids[k] for k in known])
                         .values_list('site_id', 'outage_minutes'))
        compared = file_differs = db_differs = 0
        examples = []
        for k in known:
            days = [o for d, (o, _) in parsed.daily[k].items() if d.isoformat()[:7] == key and o is not None]
            if not days:
                continue
            compared += 1
            daily_sum = sum(days)
            file_total = parsed.monthly[k].get(month, {}).get('outage_minutes')
            if file_total is not None and abs(file_total - daily_sum) > 0.01:
                file_differs += 1
            db_total = db_totals.get(ids[k])
            if db_total is not None and abs(db_total - daily_sum) > 0.01:
                db_differs += 1
                if len(examples) < 10:
                    examples.append({'site_id': parsed.sites[k]['site_id'], 'daily_sum': round(daily_sum, 2), 'database_monthly': round(db_total, 2)})
        checks[key] = {'sites_compared': compared, 'file_monthly_total_differs': file_differs,
                       'database_monthly_total_differs': db_differs, 'examples': examples}
    return {'months': months, 'sites_in_file': len(parsed.sites), 'sites_in_database': len(known),
            'sites_not_in_database': len(parsed.sites) - len(known), 'monthly_total_checks': checks}


def database_effect(parsed: ParsedWorkbook) -> dict:
    """How many sites would be inserted or matched (no writes)."""
    existing = set(UptimeSite.objects.values_list('project', 'circle', 'site_key'))
    new = sum(1 for k in parsed.sites if k not in existing)
    return {'sites_in_database': len(existing), 'new_sites': new, 'existing_sites': len(parsed.sites) - new,
            'database_sites_not_in_file': len(existing - set(parsed.sites))}


def _apply_reconciliation(primary: ParsedWorkbook, other: ParsedWorkbook) -> int:
    """Use the second file's values for the sites both files contain. Returns the number of sites replaced."""
    replaced = 0
    for key in set(primary.sites) & set(other.sites):
        primary.sites[key] = {**other.sites[key], 'project_raw': primary.sites[key]['project_raw'], '_file': other.filename}
        primary.monthly[key] = {**primary.monthly[key], **other.monthly[key]}
        primary.daily[key] = {**primary.daily[key], **other.daily[key]}
        replaced += 1
    for month, info in other.daily_months.items():
        mine = primary.daily_months.setdefault(month, {**info, 'reported_dates': []})
        mine['reported_dates'] = sorted(set(mine['reported_dates']) | set(info['reported_dates']))
    return replaced


def commit(batch: DataImportBatch, *, user=None, conflict_source: str = '') -> DataImportBatch:
    if batch.status != DataImportBatch.Status.PREVIEWED:
        raise ImportRejected(f'Import #{batch.pk} is {batch.get_status_display().lower()}; preview the file again.', 409)
    differences = (batch.report.get('comparison') or {}).get('sites_with_differences', 0)
    if batch.reconciliation_path and differences and conflict_source not in CONFLICT_CHOICES:
        raise ImportRejected(f"{differences} sites differ between the two files. Choose which file's values to apply "
                             '("primary" or "reconciliation") before committing.')
    path = Path(batch.stored_path)
    if not path.is_file() or sha256(path) != batch.checksum_sha256:
        raise ImportRejected('The staged file is missing or has changed since the preview. Preview it again.', 409)
    options = batch.report.get('options') or {}
    parsed = _parse(path, batch.original_filename, project=options.get('project'))
    replaced = 0
    if batch.reconciliation_path and conflict_source == 'reconciliation':
        other_path = Path(batch.reconciliation_path)
        if not other_path.is_file() or sha256(other_path) != batch.reconciliation_checksum:
            raise ImportRejected('The staged second file is missing or has changed since the preview. Preview again.', 409)
        replaced = _apply_reconciliation(parsed, _parse(other_path, batch.reconciliation_filename, reconciliation=True))
    try:
        with transaction.atomic():
            counts = _write_daily_only(parsed, batch) if options.get('daily_only') else _write(parsed, batch)
    except Exception as exc:
        logger.exception('Import #%s failed', batch.pk)
        batch.status, batch.error = DataImportBatch.Status.FAILED, f'{type(exc).__name__}: {exc}'[:2000]
        batch.save(update_fields=['status', 'error'])
        raise ImportRejected('The import failed and was rolled back; no records were changed. ' + batch.error, 500) from exc
    counts.setdefault('sites_from_reconciliation_file', replaced)
    batch.status, batch.counts, batch.committed_at = DataImportBatch.Status.COMMITTED, counts, timezone.now()
    batch.conflict_source = conflict_source if batch.reconciliation_path else ''
    batch.imported_by = batch.imported_by or user
    batch.save(update_fields=['status', 'counts', 'committed_at', 'conflict_source', 'imported_by'])
    datasource.clear_cache()
    audit('import_committed', _Actor(user) if user else None, batch=batch.pk, file=batch.original_filename,
          conflict_source=batch.conflict_source or '-', daily_only=bool(options.get('daily_only')),
          sites=counts.get('sites'), monthly=counts.get('monthly'), daily=counts['daily'])
    return batch


def _upsert(model, rows: list, unique: list[str], fields: list[str]) -> None:
    for i in range(0, len(rows), CHUNK):
        model.objects.bulk_create(rows[i:i + CHUNK], update_conflicts=True, unique_fields=unique, update_fields=fields)


def _same(a: tuple, b: tuple) -> bool:
    """Equal record values: None only equals None; numbers equal within rounding."""
    for x, y in zip(a, b):
        if x is None or y is None:
            if x is not y:
                return False
        elif isinstance(x, float) or isinstance(y, float):
            if abs(float(x) - float(y)) > 1e-9:
                return False
        elif x != y:
            return False
    return True


def _write(parsed: ParsedWorkbook, batch: DataImportBatch) -> dict:
    counts: dict = {}
    # --- Sites -----------------------------------------------------------------------------
    existing = {(s['project'], s['circle'], s['site_key']): s
                for s in UptimeSite.objects.values('id', 'site_key', 'source_file', 'source_row', *SITE_FIELDS)}
    to_write, inserted, updated = [], 0, 0
    for key, site in parsed.sites.items():
        values = {f: site[f] for f in SITE_FIELDS}
        source_file = site.get('_file', parsed.filename)
        old = existing.get(key)
        if old and all(old[f] == values[f] for f in SITE_FIELDS):
            continue
        inserted += old is None
        updated += old is not None
        to_write.append(UptimeSite(**values, site_key=key[2], batch=batch, source_file=source_file, source_row=site['source_row']))
    _upsert(UptimeSite, to_write, ['project', 'circle', 'site_key'], [*SITE_FIELDS, 'batch', 'source_file', 'source_row', 'updated_at'])
    counts['sites'] = {'inserted': inserted, 'updated': updated, 'unchanged': len(parsed.sites) - inserted - updated}
    ids = {(s['project'], s['circle'], s['site_key']): s['id'] for s in UptimeSite.objects.values('id', 'project', 'circle', 'site_key')}
    wanted = [ids[k] for k in parsed.sites]

    # --- Monthly ---------------------------------------------------------------------------
    old_months = {(m['site_id'], m['month']): tuple(m[f] for f in MONTH_FIELDS)
                  for m in SiteMonthlyPerformance.objects.filter(site_id__in=wanted).values('site_id', 'month', *MONTH_FIELDS)}
    rows, inserted, total = [], 0, 0
    for key, months in parsed.monthly.items():
        for month, record in months.items():
            total += 1
            old = old_months.get((ids[key], month))
            if old is not None and _same(old, tuple(record[f] for f in MONTH_FIELDS)):
                continue
            inserted += old is None
            rows.append(SiteMonthlyPerformance(site_id=ids[key], month=month, batch=batch, **{f: record[f] for f in MONTH_FIELDS}))
    _upsert(SiteMonthlyPerformance, rows, ['site', 'month'], [*MONTH_FIELDS, 'batch'])
    counts['monthly'] = {'inserted': inserted, 'updated': len(rows) - inserted, 'unchanged': total - len(rows)}

    # --- Daily: only actual reporting dates (a date with any reported value) -----------------
    reported = {date.fromisoformat(d) for m in parsed.daily_months.values() for d in m['reported_dates']}
    old_days = {(d['site_id'], d['date']): (d['outage_minutes'], d['uptime_pct'])
                for d in SiteDailyPerformance.objects.filter(site_id__in=wanted, date__in=reported)
                .values('site_id', 'date', 'outage_minutes', 'uptime_pct')}
    rows, inserted, total = [], 0, 0
    for key, days in parsed.daily.items():
        for day, (outage, uptime) in days.items():
            if day not in reported:
                continue
            total += 1
            old = old_days.get((ids[key], day))
            if old is not None and _same(old, (outage, uptime)):
                continue
            inserted += old is None
            rows.append(SiteDailyPerformance(site_id=ids[key], date=day, outage_minutes=outage, uptime_pct=uptime, batch=batch))
    _upsert(SiteDailyPerformance, rows, ['site', 'date'], ['outage_minutes', 'uptime_pct', 'batch'])
    counts['daily'] = {'inserted': inserted, 'updated': len(rows) - inserted, 'unchanged': total - len(rows)}
    counts['rejected'] = parsed.rejected
    counts['skipped'] = sum(parsed.skipped.values())
    return counts


def _write_daily_only(parsed: ParsedWorkbook, batch: DataImportBatch) -> dict:
    """Daily values for sites already in the database; sites and monthly figures are not touched."""
    ids = {(s['project'], s['circle'], s['site_key']): s['id'] for s in UptimeSite.objects.values('id', 'project', 'circle', 'site_key')}
    known = {k: ids[k] for k in parsed.sites if k in ids}
    reported = {date.fromisoformat(d) for m in parsed.daily_months.values() for d in m['reported_dates']}
    old_days = {(d['site_id'], d['date']): (d['outage_minutes'], d['uptime_pct'])
                for d in SiteDailyPerformance.objects.filter(site_id__in=list(known.values()), date__in=reported)
                .values('site_id', 'date', 'outage_minutes', 'uptime_pct')}
    rows, inserted, total = [], 0, 0
    for key, site_id in known.items():
        for day, (outage, uptime) in parsed.daily[key].items():
            if day not in reported:
                continue
            total += 1
            old = old_days.get((site_id, day))
            if old is not None and _same(old, (outage, uptime)):
                continue
            inserted += old is None
            rows.append(SiteDailyPerformance(site_id=site_id, date=day, outage_minutes=outage, uptime_pct=uptime, batch=batch))
    _upsert(SiteDailyPerformance, rows, ['site', 'date'], ['outage_minutes', 'uptime_pct', 'batch'])
    return {'daily_only': True,
            'daily': {'inserted': inserted, 'updated': len(rows) - inserted, 'unchanged': total - len(rows)},
            'sites_not_in_database': len(parsed.sites) - len(known),
            'rejected': parsed.rejected, 'skipped': sum(parsed.skipped.values())}
