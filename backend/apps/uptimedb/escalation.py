"""Import of the Consolidated Escalation Matrix ("Raw Data" sheet) into PostgreSQL, linked to the Up-Time sites.

Two steps, as for the Up-Time Report: preview() stages a copy, parses and cross-checks it (nothing is written to
the site table); commit() re-parses the staged copy (checksum checked) and inserts or updates one row per site in
one transaction. Sites missing from a later file are kept (never deleted) and reported.

Each escalation site is linked to the Up-Time Report site with the same project, circle and normalised ID
(``EscalationSite.uptime_site``), so it can be joined with the monthly, daily and RCA tables. The cross-check
compares the two sources (CI / IE names, On-Air, O&M Start) and reports differences; it never changes either.
"""
from __future__ import annotations

import logging
import re
import shutil
from datetime import date, datetime
from pathlib import Path

from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from apps.accounts.audit import audit
from apps.dashboard.activity import ENTITIES

from .models import EscalationImportBatch, EscalationSite, SiteMonthlyPerformance, UptimeSite
from .parser import sha256, site_key

logger = logging.getLogger(__name__)
SHEET = 'Raw Data'
KEY_HEADER = 'BSNL Site ID'
MAX_EXAMPLES = 10
CHUNK = 2000

# Normalised header -> field. "Contact" appears several times; it belongs to the person named just before it.
COLUMNS = {
    'entity': 'entity_raw', 'site type': 'site_type', 'circle name': 'circle_raw', 'bsnl site id': 'site_id',
    'site name/village name': 'site_name', 'village code': 'village_code', 'ba': 'ba', 'oa': 'oa',
    'district': 'district', 'sub-district': 'sub_district',
    'site commissioning /hoto date': 'commissioning_date', 'site commissioning /hoto status': 'commissioning_status',
    'o&m status': 'om_status', 'o&m start date': 'om_start_date', 'eb status': 'eb_status', 'dg status': 'dg_status',
    'case type': 'case_type', 'site on air status': 'on_air_status', 'site on air date': 'on_air_date',
    'ie emp code': 'ie_emp_code', 'ie name': 'ie_name', 'ie contact': 'ie_contact',
    'ci emp code': 'ci_emp_code', 'ci name': 'ci_name', 'ci contact': 'ci_contact',
    'il emp id': 'il_emp_code', 'il name': 'il_name',
    'o&m manager emp code': 'om_manager_emp_code', 'o&m manager name': 'om_manager_name',
    'o&m manager contact': 'om_manager_contact', 'cbh name': 'cbh_name',
    'ct status': 'ct_status', 'ct name': 'ct_name', 'ct contact': 'ct_contact', 'site address': 'site_address',
    'lattitude': 'latitude', 'latitude': 'latitude', 'longitude': 'longitude',
    'rigger emp id': 'rigger_emp_code', 'rigger name': 'rigger_name', 'other remarks (if any)': 'remarks',
    'ccu/smps make': 'smps_make', 'bts site id_b1(21mhz)': 'bts_id_b1', 'bts site id_b28(7mhz)': 'bts_id_b28',
    'master bts id': 'master_bts_id',
}
CONTACT_AFTER = {'il_name': 'il_contact', 'cbh_name': 'cbh_contact', 'rigger_name': 'rigger_contact'}
# Serial number and the sheet's own formatting helpers ("Mr. _<name>_MB:-<number>"): not stored.
SKIPPED = {'sl', '@', 'combo'}
DATES = {'commissioning_date': 'commissioning_raw', 'om_start_date': 'om_start_raw', 'on_air_date': 'on_air_raw'}
FIELDS = [f.name for f in EscalationSite._meta.get_fields()
          if f.concrete and f.name not in ('id', 'uptime_site', 'match_status', 'batch', 'updated_at')]
LIMITS = {f.name: f.max_length for f in EscalationSite._meta.concrete_fields if f.name in FIELDS and getattr(f, 'max_length', None)}
EMPTY = {'', '-', 'na', 'n/a', 'tbd', 'vacant'}


class EscalationRejected(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class _Actor:
    def __init__(self, user):
        self.user = user
        self.META = {}


def _header(value) -> str:
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def _text(value) -> str:
    if value is None:
        return ''
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, (datetime, date)):
        return value.strftime('%Y-%m-%d')
    return re.sub(r'\s+', ' ', str(value)).strip()


def _date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    return value if isinstance(value, date) else None


def _coordinate(value) -> float | None:
    """A coordinate, or None for blanks, text and 0 (the source's placeholder, never a real position here)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number else None


def project_of(entity: str) -> str:
    return ENTITIES.get(entity.casefold(), entity)


def circle_of(circle_raw: str, resolver=None) -> str:
    """Circle code through Organization > Code Mapping (source "Consolidated Escalation Matrix"); as written if unknown."""
    from apps.organization.services import AliasResolver
    return (resolver or AliasResolver('escalation_matrix')).resolve(circle_raw) or circle_raw.upper()


def parse(path: Path, filename: str) -> dict:
    """Rows of the Raw Data sheet as model field values, plus a parse summary. Raises EscalationRejected."""
    from apps.organization.services import AliasResolver
    circles = AliasResolver('escalation_matrix')
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        if SHEET not in book.sheetnames:
            raise EscalationRejected(f'{filename} has no "{SHEET}" sheet (sheets: {", ".join(book.sheetnames)}).')
        rows = book[SHEET].iter_rows(values_only=True)
        columns: list[tuple[int, str | None, str]] | None = None
        sites: dict[tuple[str, str], dict] = {}
        duplicates, skipped, row_number = [], 0, 0
        for row in rows:
            row_number += 1
            if columns is None:
                cells = [_header(v) for v in row]
                if KEY_HEADER in cells:
                    columns, previous = [], None
                    for i, name in enumerate(cells):
                        key = name.casefold()
                        field = CONTACT_AFTER.get(previous) if key == 'contact' else COLUMNS.get(key)
                        if key in SKIPPED:
                            field = None
                        columns.append((i, field, name or f'Column {get_column_letter(i + 1)}'))
                        previous = field or previous
                    missing = [h for h in ('entity_raw', 'circle_raw', 'site_id') if h not in {f for _, f, _ in columns}]
                    if missing:
                        raise EscalationRejected(f'{filename} ({SHEET}) is missing columns: {", ".join(missing)}.')
                continue
            values: dict = {'extra': {}}
            for i, field, name in columns:
                raw = row[i] if i < len(row) else None
                if field is None:
                    if name.casefold() not in SKIPPED and _text(raw):
                        values['extra'][name] = _text(raw)
                elif field in DATES:
                    values[field], values[DATES[field]] = _date(raw), _text(raw)
                elif field in ('latitude', 'longitude'):
                    values[field] = _coordinate(raw)
                else:
                    values[field] = _text(raw)
            if not values.get('site_id'):
                skipped += any(v is not None for v in row)
                continue
            values['project'] = project_of(values.get('entity_raw', ''))
            values['circle'] = circle_of(values.get('circle_raw', ''), circles)
            values['site_key'] = site_key(values['site_id'])
            values['source_file'], values['source_row'] = filename, row_number
            identity = (values['project'], values['site_key'])
            if identity in sites:
                duplicates.append(values['site_id'])
            sites[identity] = values  # the last row wins, as in a lookup
        if columns is None:
            raise EscalationRejected(f'{filename} ({SHEET}) has no "{KEY_HEADER}" header row.')
    finally:
        book.close()
    for values in sites.values():
        for field in FIELDS:
            values.setdefault(field, None if field in (*DATES, 'latitude', 'longitude') else '')
    # Values longer than their column would fail the commit on PostgreSQL; reject them in the preview instead.
    too_long = []
    for field, limit in LIMITS.items():
        longest = max(sites.values(), key=lambda v: len(v[field] or ''), default=None)
        if longest and len(longest[field] or '') > limit:
            too_long.append(f"{field} (row {longest['source_row']}: {len(longest[field])} characters, limit {limit})")
    if too_long:
        raise EscalationRejected(f'{filename}: values too long to store: {"; ".join(too_long)}.')
    unknown_circles = sorted({v['circle_raw'] for v in sites.values()
                              if v['project'] in ENTITIES.values() and not circles.is_known(v['circle_raw'])})
    return {
        'sites': sites,
        'summary': {
            'file': filename, 'sheet': SHEET, 'sites': len(sites), 'blank_id_rows_skipped': skipped,
            'duplicate_ids': {'count': len(duplicates), 'examples': duplicates[:MAX_EXAMPLES]},
            'by_project': _count(v['project'] for v in sites.values()),
            'by_circle': _count(f"{v['project']} {v['circle']}" for v in sites.values()),
            'unknown_circle_names': unknown_circles,
            'stored_extra_columns': sorted({k for v in sites.values() for k in v['extra']}),
            'text_in_date_columns': {f: sum(1 for v in sites.values() if v[raw] and v[f] is None)
                                     for f, raw in DATES.items()},
            'missing_coordinates': sum(1 for v in sites.values() if v['latitude'] is None or v['longitude'] is None),
        },
    }


def _count(values) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        out[value] = out.get(value, 0) + 1
    return dict(sorted(out.items()))


def _name(value: str) -> str:
    return re.sub(r'\s+', ' ', value or '').strip().casefold()


def _yes(value: str) -> bool:
    return _name(value) == 'yes'


def cross_check(sites: dict[tuple[str, str], dict]) -> dict:
    """Compare escalation rows with the Up-Time Report tables: matches, and differences in the shared fields.

    Names are compared ignoring case and spacing; a blank or placeholder ("-", "TBD") on either side is not a
    difference. O&M Start is compared with the latest month that has the O&M Start flag in the database.
    """
    uptime = {(s['project'], s['circle'], s['site_key']): s
              for s in UptimeSite.objects.values('id', 'project', 'circle', 'site_key', 'site_id', 'ci_name', 'ie_name', 'on_air')}
    flagged = SiteMonthlyPerformance.objects.filter(om_start__isnull=False).aggregate(m=Max('month'))['m']
    om_start = dict(SiteMonthlyPerformance.objects.filter(month=flagged).values_list('site_id', 'om_start')) if flagged else {}
    dashboard = set(ENTITIES.values())
    result = {key: {'count': 0, 'examples': []} for key in (
        'matched', 'not_in_uptime', 'other_entity', 'circle_differs', 'ci_name_differs', 'ie_name_differs',
        'on_air_differs', 'om_start_differs')}

    def note(key, example):
        result[key]['count'] += 1
        if len(result[key]['examples']) < MAX_EXAMPLES:
            result[key]['examples'].append(example)

    by_id = {(p, k): (c, s) for (p, c, k), s in uptime.items()}
    seen = set()
    for (project, key), row in sites.items():
        if project not in dashboard:
            note('other_entity', {'site_id': row['site_id'], 'entity': row['entity_raw'], 'circle': row['circle_raw']})
            continue
        site = uptime.get((project, row['circle'], key))
        if site is None:
            other = by_id.get((project, key))
            if other:
                note('circle_differs', {'site_id': row['site_id'], 'matrix': row['circle'], 'uptime_report': other[0]})
            note('not_in_uptime', {'site_id': row['site_id'], 'project': project, 'circle': row['circle']})
            continue
        seen.add(site['id'])
        note('matched', row['site_id'])
        for field in ('ci_name', 'ie_name'):
            a, b = _name(row[field]), _name(site[field])
            if a and b and a not in EMPTY and b not in EMPTY and a != b:
                note(f'{field}_differs', {'site_id': row['site_id'], 'matrix': row[field], 'uptime_report': site[field]})
        if _yes(row['on_air_status']) != site['on_air']:
            note('on_air_differs', {'site_id': row['site_id'], 'matrix': row['on_air_status'] or '(blank)',
                                    'uptime_report': 'Yes' if site['on_air'] else 'No'})
        flag = om_start.get(site['id'])
        if flag is not None and _yes(row['om_status']) != flag:
            note('om_start_differs', {'site_id': row['site_id'], 'matrix': row['om_status'] or '(blank)',
                                      'uptime_report': 'Yes' if flag else 'No'})
    result['matched'].pop('examples')
    missing = [s for s in uptime.values() if s['id'] not in seen]
    result['uptime_sites_not_in_matrix'] = {'count': len(missing), 'examples': [
        {'site_id': s['site_id'], 'project': s['project'], 'circle': s['circle']} for s in missing[:MAX_EXAMPLES]]}
    result['om_start_month_compared'] = flagged.strftime('%Y-%m') if flagged else None
    return result


def _stage(source: Path, name: str) -> tuple[Path, str]:
    from .importer import staging_dir
    checksum = sha256(source)
    target = staging_dir() / f"{datetime.now():%Y%m%d-%H%M%S}-escalation-{checksum[:10]}{Path(name).suffix.lower() or '.xlsx'}"
    shutil.copyfile(source, target)
    return target, checksum


def preview(path: Path, name: str, *, user=None, via: str = 'command') -> EscalationImportBatch:
    staged, checksum = _stage(path, name)
    parsed = parse(staged, name)
    existing = set(EscalationSite.objects.values_list('project', 'site_key'))
    report = {
        **parsed['summary'],
        'database_effect': {'new': sum(1 for k in parsed['sites'] if k not in existing),
                            'already_stored': sum(1 for k in parsed['sites'] if k in existing),
                            'stored_but_not_in_this_file': len(existing - set(parsed['sites']))},
        'cross_check': cross_check(parsed['sites']),
    }
    previous = EscalationImportBatch.objects.filter(status=EscalationImportBatch.Status.COMMITTED, checksum_sha256=checksum).first()
    if previous:
        report['same_file_as_import'] = previous.pk
    batch = EscalationImportBatch.objects.create(original_filename=name, checksum_sha256=checksum, sheet_name=SHEET,
                                                 stored_path=str(staged), imported_by=user, initiated_via=via, report=report)
    audit('escalation_import_previewed', _Actor(user) if user else None, batch=batch.pk, file=name, sites=len(parsed['sites']))
    return batch


def commit(batch: EscalationImportBatch, *, user=None) -> EscalationImportBatch:
    if batch.status != EscalationImportBatch.Status.PREVIEWED:
        raise EscalationRejected(f'Import #{batch.pk} is {batch.get_status_display().lower()}; preview the file again.', 409)
    path = Path(batch.stored_path)
    if not path.is_file() or sha256(path) != batch.checksum_sha256:
        raise EscalationRejected('The staged file is missing or has changed since the preview. Preview it again.', 409)
    parsed = parse(path, batch.original_filename)
    try:
        with transaction.atomic():
            counts = _write(parsed['sites'], batch)
            counts['links'] = link_uptime_sites()
    except Exception as exc:
        logger.exception('Escalation import #%s failed', batch.pk)
        batch.status, batch.error = EscalationImportBatch.Status.FAILED, f'{type(exc).__name__}: {exc}'[:2000]
        batch.save(update_fields=['status', 'error'])
        raise EscalationRejected('The import failed and was rolled back; no records were changed. ' + batch.error, 500) from exc
    batch.status, batch.counts, batch.committed_at = EscalationImportBatch.Status.COMMITTED, counts, timezone.now()
    batch.imported_by = batch.imported_by or user
    batch.save(update_fields=['status', 'counts', 'committed_at', 'imported_by'])
    audit('escalation_import_committed', _Actor(user) if user else None, batch=batch.pk, file=batch.original_filename,
          inserted=counts['inserted'], updated=counts['updated'], unchanged=counts['unchanged'])
    return batch


def _write(sites: dict[tuple[str, str], dict], batch: EscalationImportBatch) -> dict:
    compared = [f for f in FIELDS if f not in ('source_file', 'source_row')]
    existing = {(s['project'], s['site_key']): s for s in EscalationSite.objects.values(*FIELDS)}
    to_write, inserted, updated = [], 0, 0
    for key, values in sites.items():
        old = existing.get(key)
        if old is not None and all(old[f] == values[f] for f in compared):
            continue
        inserted += old is None
        updated += old is not None
        to_write.append(EscalationSite(**values, batch=batch))
    for i in range(0, len(to_write), CHUNK):
        EscalationSite.objects.bulk_create(to_write[i:i + CHUNK], update_conflicts=True, unique_fields=['project', 'site_key'],
                                           update_fields=[f for f in FIELDS if f not in ('project', 'site_key')] + ['batch', 'updated_at'])
    return {'inserted': inserted, 'updated': updated, 'unchanged': len(sites) - inserted - updated,
            'not_in_this_file': len(set(existing) - set(sites))}


def link_uptime_sites() -> dict[str, int]:
    """(Re)link every escalation site to its Up-Time Report site (same project, circle and ID). Run after either
    import, so sites added later are linked too. Returns the count per match status."""
    uptime = {(p, c, k): i for i, p, c, k in UptimeSite.objects.values_list('id', 'project', 'circle', 'site_key')}
    dashboard = set(ENTITIES.values())
    changed = []
    for row in EscalationSite.objects.only('id', 'project', 'circle', 'site_key', 'uptime_site_id', 'match_status'):
        site_id = uptime.get((row.project, row.circle, row.site_key))
        status = (EscalationSite.Match.MATCHED if site_id else
                  EscalationSite.Match.NOT_IN_UPTIME if row.project in dashboard else EscalationSite.Match.OTHER_ENTITY)
        if (row.uptime_site_id, row.match_status) != (site_id, status):
            row.uptime_site_id, row.match_status = site_id, status
            changed.append(row)
    with transaction.atomic():
        # Clear first, so a link can move from one row to another without breaking the one-to-one rule.
        EscalationSite.objects.filter(pk__in=[r.pk for r in changed]).update(uptime_site=None)
        EscalationSite.objects.bulk_update(changed, ['uptime_site', 'match_status'], batch_size=CHUNK)
    return _count(EscalationSite.objects.values_list('match_status', flat=True))
