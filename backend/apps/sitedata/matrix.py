"""Consolidation Matrix import: the authoritative source of site attributes, identities and effective dates.

Reading (``read``): the "Raw Data" sheet of the Consolidated Escalation Matrix, header row found by "BSNL Site ID".
Columns are matched by header text (case and spacing ignored), including the renamed commissioning columns of the
November 2026 file ("Site Comm./Hoto Date" / "Status"). A known column that a file does not have (e.g. the band IDs
or CCU/SMPS Make in the November file) leaves the stored values untouched.

Rules (approved 4 Nov 2026, extended 5 Nov 2026):
- One Site per BSNL Site ID (normalised key). Sites are never deleted; a site a newer matrix does not list is flagged
  (present_in_latest_matrix = False).
- Entities: 4G Saturation and LWE are dashboard sites; Sterlite and VI-HPSC are kept as outside-scope sites (excluded
  from every KPI). Any other entity is rejected (invalid technology), never guessed.
- Circle: a dashboard site's circle must resolve through Organization > Code Mapping (source "Consolidated Escalation
  Matrix"); an unknown circle name rejects the row.
- Mandatory: BSNL Site ID, Entity, Circle Name. A row with data but without one of them is rejected and reported.
- Duplicate BSNL Site ID in the file: identical rows are imported once (reported); differing rows are all rejected,
  so no row silently wins.
- Identity: an existing site whose technology, reporting scope or circle would change is blocked (rejected as an
  identity conflict) until resolved; its stored record is not changed. A matrix identifier (BSNL ID, band IDs,
  Master BTS ID) claimed by more than one site is assigned to none and recorded as an active IdentifierConflict.
- Blank cells never overwrite stored values: an empty cell (or a missing column) keeps the stored value; such
  fields are counted in the preview. Placeholders written in the file ("-", "Vacant") are values and are stored.
- Effective dates (Site On-Air Date, O&M Start Date) come from the matrix only. A date that is not readable, in the
  future, or an O&M Start before the On-Air Date is flagged for review (not imported as a date when unreadable, never
  guessed); a changed stored date is listed. The *_issue flags are recomputed from the resulting values.
- Daily performance records are never touched by this import (monthly results are recalculated after it, as the
  effective dates may change). Every changed On-Air / O&M Start date (site, old, new) is stored in full in the committed
  upload's report (effective_date_changes) and audited.
- Every (technology, circle) of the dashboard sites written must be set up in the Organization
  (organization.services.check_pairs); otherwise the preview fails with the set-up message.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

from django.db import transaction
from django.utils import timezone
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from apps.accounts.audit import audit
from . import exceptions, uploads
from .rules import ENTITIES
from .sources import matrix_sheet as escalation
from .identifiers import key_of
from .models import IdentifierConflict, Site, SiteIdentifier, SiteManualOverride, Technology, UploadBatch
from .rules import date_issue, om_start_date_issue

KIND = UploadBatch.Kind.CONSOLIDATION_MATRIX
SHEET = escalation.SHEET
KEY_HEADER = escalation.KEY_HEADER
# Header text (normalised) -> parser field: the parser's columns plus the November 2026 spellings.
COLUMNS = {**escalation.COLUMNS, 'site comm./hoto date': 'commissioning_date', 'site comm./hoto status': 'commissioning_status'}
OUTSIDE_ENTITIES = {'sterlite': 'Sterlite', 'vi-hpsc': 'VI-HPSC'}  # kept and flagged outside the dashboard scope
# Site fields set from the matrix (parser field -> Site field).
FIELDS = {
    'site_id': 'bsnl_site_id', 'entity_raw': 'entity', 'site_type': 'site_type', 'circle': 'circle', 'circle_raw': 'circle_raw',
    'site_name': 'site_name', 'village_code': 'village_code', 'ba': 'ba', 'oa': 'oa', 'district': 'district',
    'sub_district': 'sub_district', 'site_address': 'site_address', 'latitude': 'latitude', 'longitude': 'longitude',
    'commissioning_status': 'commissioning_status', 'commissioning_date': 'commissioning_date', 'commissioning_raw': 'commissioning_raw',
    'om_status': 'om_status', 'om_start_date': 'om_start_date', 'om_start_raw': 'om_start_raw',
    'on_air_status': 'on_air_status', 'on_air_date': 'on_air_date', 'on_air_raw': 'on_air_raw',
    'eb_status': 'eb_status', 'dg_status': 'dg_status', 'case_type': 'case_type', 'smps_make': 'smps_make', 'remarks': 'remarks',
    'ci_emp_code': 'ci_emp_code', 'ci_name': 'ci_name', 'ci_contact': 'ci_contact',
    'ie_emp_code': 'ie_emp_code', 'ie_name': 'ie_name', 'ie_contact': 'ie_contact',
    'il_emp_code': 'il_emp_code', 'il_name': 'il_name', 'il_contact': 'il_contact',
    'om_manager_emp_code': 'om_manager_emp_code', 'om_manager_name': 'om_manager_name', 'om_manager_contact': 'om_manager_contact',
    'cbh_name': 'cbh_name', 'cbh_contact': 'cbh_contact', 'ct_status': 'ct_status', 'ct_name': 'ct_name', 'ct_contact': 'ct_contact',
    'rigger_emp_code': 'rigger_emp_code', 'rigger_name': 'rigger_name', 'rigger_contact': 'rigger_contact',
}
# A date column sets the date and its text together (the text keeps an unreadable value for review).
DATE_PAIRS = {'commissioning_date': 'commissioning_raw', 'om_start_date': 'om_start_raw', 'on_air_date': 'on_air_raw'}
IDENTITY_FIELDS = ('technology', 'reporting_scope', 'circle')
# Matrix identifier columns (besides the BSNL Site ID).
IDENTIFIERS = {'bts_id_b1': SiteIdentifier.Kind.BAND_2100, 'bts_id_b28': SiteIdentifier.Kind.BAND_700, 'master_bts_id': SiteIdentifier.Kind.MASTER_BTS_ID}
LIMITS = {f.name: f.max_length for f in Site._meta.concrete_fields if getattr(f, 'max_length', None) and f.get_internal_type() == 'CharField'}
MATRIX_KINDS = {SiteIdentifier.Kind.BSNL_SITE_ID, *IDENTIFIERS.values()}
MAX_LISTED = 500  # rejected rows / review items listed in the preview (all of them are in the CSV)

REASONS = {
    'missing_site_id': 'BSNL Site ID is blank (the row has other data)',
    'missing_entity': 'Entity is blank',
    'missing_circle': 'Circle Name is blank',
    'unknown_entity': 'Entity is not 4G Saturation, LWE, Sterlite or VI-HPSC',
    'unknown_circle': 'Circle Name is not a known circle (Organization > Code Mapping)',
    'duplicate_site_id': 'BSNL Site ID is on several rows with different values',
    'identity_change': 'The site exists with another technology, scope or circle',
    'value_too_long': 'A value is longer than the site master allows',
}


def _blank(value) -> bool:
    return value is None or value == '' or value == {}


def read(path: Path, name: str) -> dict:
    """Every data row of the Raw Data sheet as parser fields, the columns present, and rows without a BSNL Site ID.
    Raises UploadRejected when the file is not a Consolidation Matrix."""
    try:
        book = load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:  # not an xlsx, or damaged
        raise uploads.UploadRejected(f'{name} could not be opened as an Excel workbook ({exc.__class__.__name__}).') from exc
    try:
        if SHEET not in book.sheetnames:
            raise uploads.UploadRejected(f'{name} has no "{SHEET}" sheet, so it is not a Consolidation Matrix (sheets: {", ".join(book.sheetnames)}). '
                                         'For an Up-Time Report workbook choose the Up-Time Report type.')
        columns, rows, blank_id_rows, row_number = None, [], [], 0
        for raw in book[SHEET].iter_rows(values_only=True):
            row_number += 1
            if columns is None:
                cells = [escalation._header(v) for v in raw]
                if KEY_HEADER in cells:
                    columns, previous = [], None
                    for i, header in enumerate(cells):
                        key = header.casefold()
                        field = escalation.CONTACT_AFTER.get(previous) if key == 'contact' else COLUMNS.get(key)
                        if key in escalation.SKIPPED:
                            field = None
                        columns.append((i, field, header or f'Column {get_column_letter(i + 1)}'))
                        previous = field or previous
                    present = {f for _, f, _ in columns if f}
                    missing = [label for field, label in (('entity_raw', 'Entity'), ('circle_raw', 'Circle Name'), ('site_id', 'BSNL Site ID'))
                               if field not in present]
                    if missing:
                        raise uploads.UploadRejected(f'{name} ({SHEET}) is missing columns: {", ".join(missing)}.')
                continue
            if raw is None or all(v is None or escalation._text(v) == '' for v in raw):
                continue
            values: dict = {'extra': {}}
            for i, field, header in columns:
                cell = raw[i] if i < len(raw) else None
                if field is None:
                    if header.casefold() not in escalation.SKIPPED and escalation._text(cell):
                        values['extra'][header] = escalation._text(cell)
                elif field in escalation.DATES:
                    values[field], values[escalation.DATES[field]] = escalation._date(cell), escalation._text(cell)
                elif field in ('latitude', 'longitude'):
                    values[field] = escalation._coordinate(cell)
                else:
                    values[field] = escalation._text(cell)
            values['source_row'] = row_number
            (rows if values.get('site_id') else blank_id_rows).append(values)
        if columns is None:
            raise uploads.UploadRejected(f'{name} ({SHEET}) has no "{KEY_HEADER}" header row, so it is not a Consolidation Matrix.')
    finally:
        book.close()
    present = {f for _, f, _ in columns if f}
    for f, raw_field in escalation.DATES.items():
        if f in present:
            present.add(raw_field)
    known = sorted({h for _, f, h in columns if f}, key=str.casefold)
    expected = sorted({k for k, f in COLUMNS.items() if f in FIELDS or f in IDENTIFIERS} - {k.casefold() for k in known})
    return {'rows': rows, 'blank_id_rows': blank_id_rows, 'present': present, 'headers': known,
            'absent_columns': sorted({COLUMNS[k] for k in expected} - present)}


def _entity(raw: str) -> tuple[str, str] | None:
    """(technology, reporting scope) of an entity as written, or None when it is not a known entity."""
    key = (raw or '').strip().casefold()
    if key in ENTITIES:
        return ENTITIES[key], Site.Scope.DASHBOARD
    if key in OUTSIDE_ENTITIES:
        return '', Site.Scope.OUTSIDE
    return None


def _incoming(row: dict, present: set) -> dict:
    """The Site values a row provides: only fields whose column is in the file and whose cell is not empty."""
    out = {}
    for source, field in FIELDS.items():
        if source not in present and source not in ('circle',):
            continue
        value = row.get(source)
        if not _blank(value):
            out[field] = value
    if row.get('extra'):
        out['extra'] = row['extra']
    return out


def _derived(values: dict, scope: str) -> dict:
    """Flags computed from the resulting values (never kept from an earlier import)."""
    in_scope = scope == Site.Scope.DASHBOARD
    return {
        'on_air': (values.get('on_air_status') or '').strip().casefold() == 'yes',
        'om_start_date_issue': om_start_date_issue(values.get('om_start_date'), values.get('om_start_raw') or '') if in_scope else '',
        'on_air_date_issue': date_issue(values.get('on_air_date'), values.get('on_air_raw') or '') if in_scope else '',
    }


def _row_record(name, row, code, message, severity=exceptions.REJECTED, **extra) -> dict:
    return exceptions.record(source_file=name, code=code, severity=severity, row=row.get('source_row'), site_id=row.get('site_id', ''),
                             circle=row.get('circle_raw', ''), message=message, **extra)


def analyse(path: Path, name: str, *, lock: bool = False) -> dict:
    """What a commit would do: the plan, the counts and the preview report. Reads the database, writes nothing."""
    from apps.organization.services import AliasResolver
    data = read(path, name)
    present = data['present']
    circles = AliasResolver('escalation_matrix')
    today = timezone.localdate()
    items: list[dict] = []
    rejected: list[dict] = []

    def reject(row, code, detail=''):
        message = REASONS[code] + (f': {detail}' if detail else '')
        rejected.append({'row': row.get('source_row'), 'site_id': row.get('site_id', ''), 'entity': row.get('entity_raw', ''),
                         'circle': row.get('circle_raw', ''), 'code': code, 'reason': message})
        items.append(_row_record(name, row, code, message))

    for row in data['blank_id_rows']:
        reject(row, 'missing_site_id')

    # Row checks: mandatory values, entity, circle, lengths.
    candidates = defaultdict(list)
    for row in data['rows']:
        row['site_key'] = escalation.site_key(row['site_id'])
        if not row.get('entity_raw'):
            reject(row, 'missing_entity')
            continue
        if not row.get('circle_raw'):
            reject(row, 'missing_circle')
            continue
        entity = _entity(row['entity_raw'])
        if entity is None:
            reject(row, 'unknown_entity', f'"{row["entity_raw"]}"')
            continue
        technology, scope = entity
        if scope == Site.Scope.DASHBOARD:
            circle = circles.resolve(row['circle_raw'], technology)
            if circle is None:
                reject(row, 'unknown_circle', f'"{row["circle_raw"]}"')
                continue
        else:
            circle = circles.resolve(row['circle_raw']) or row['circle_raw'].strip().upper()
        row['circle'] = circle  # checked with the other values below
        too_long = [f'{dst} ({len(str(row.get(src)))} > {LIMITS[dst]})' for src, dst in FIELDS.items()
                    if dst in LIMITS and len(str(row.get(src) or '')) > LIMITS[dst]]
        if too_long:
            reject(row, 'value_too_long', ', '.join(too_long))
            continue
        row['circle'], row['_technology'], row['_scope'] = circle, technology, scope
        candidates[row['site_key']].append(row)

    # Duplicate BSNL Site IDs: identical rows import once; differing rows are all rejected.
    duplicates = []
    rows: dict[str, dict] = {}
    for key, group in candidates.items():
        if len(group) > 1:
            comparable = {tuple(sorted((k, str(v)) for k, v in r.items() if k != 'source_row')) for r in group}
            duplicates.append({'site_id': group[0]['site_id'], 'rows': [r['source_row'] for r in group], 'identical': len(comparable) == 1})
            if len(comparable) > 1:
                for r in group:
                    reject(r, 'duplicate_site_id', f'rows {", ".join(str(x["source_row"]) for x in group)}')
                continue
            items.append(_row_record(name, group[0], 'duplicate_identical_rows', severity=exceptions.REVIEW,
                                     message=f'BSNL Site ID on {len(group)} identical rows ({", ".join(str(x["source_row"]) for x in group)}): imported once.'))
        rows[key] = group[0]

    sites = Site.objects.select_for_update() if lock else Site.objects.all()
    existing = {s.site_key: s for s in sites}
    override_rows = SiteManualOverride.objects.filter(site_id__in=[s.pk for s in existing.values()])
    if lock:
        override_rows = override_rows.select_for_update()
    overrides: dict[int, list[SiteManualOverride]] = defaultdict(list)
    for override in override_rows:
        overrides[override.site_id].append(override)
    plan = {'insert': {}, 'update': {}, 'unchanged': [], 'missing': [], 'identifiers': [], 'identifier_conflicts': []}
    blank_kept: Counter = Counter()
    date_changes, date_reviews = [], []
    for key, row in list(rows.items()):
        technology, scope = row['_technology'], row['_scope']
        incoming = _incoming(row, present)
        incoming.update(circle=row['circle'], technology=technology, reporting_scope=scope)
        site = existing.get(key)
        if site is not None:
            differs = [f for f in IDENTITY_FIELDS if getattr(site, f) != incoming[f]]
            if differs:
                reject(row, 'identity_change', '; '.join(f'{f} {getattr(site, f) or "blank"} -> {incoming[f] or "blank"}' for f in differs))
                del rows[key]
                continue
        stored = {f: getattr(site, f) for f in [*FIELDS.values(), 'extra', 'technology', 'reporting_scope']} if site else {}
        # A date cell with text that is not a date: an existing site keeps its stored date and text (flagged for review);
        # a new site gets the text without a date (flagged by its *_issue). Nothing is guessed.
        for date_field, raw_field in DATE_PAIRS.items():
            if raw_field in incoming and date_field not in incoming and site is not None and stored.get(date_field):
                del incoming[raw_field]
                if date_field in ('om_start_date', 'on_air_date') and scope == Site.Scope.DASHBOARD:
                    date_reviews.append(_row_record(name, row, f'{date_field}_unreadable', severity=exceptions.REVIEW, value=row.get(raw_field, ''),
                                                    message=f'"{row.get(raw_field)}" is not a date: the stored value is kept.'))
        values = dict(stored)
        for field in FIELDS.values():
            if field in incoming:
                values[field] = incoming[field]
            elif site is not None and not _blank(stored.get(field)) and FIELDS_BY_DST[field] in present:
                blank_kept[field] += 1  # an empty cell: the stored value stays
        values['extra'] = {**(stored.get('extra') or {}), **(row.get('extra') or {})}
        values.update(technology=technology, reporting_scope=scope, circle=row['circle'])
        for field in FIELDS.values():
            values.setdefault(field, None if field in ('latitude', 'longitude', *DATE_PAIRS) else '')
        values.update(_derived(values, scope))
        matrix_values = {}
        if site is not None:
            for override in overrides.get(site.pk, []):
                if override.field in incoming:
                    matrix_value = _json_value(values.get(override.field))
                    if matrix_value != override.matrix_value:
                        matrix_values[override.field] = matrix_value
                values[override.field] = getattr(site, override.field)
            values.update(_derived(values, scope))
        values['source_row'] = row['source_row']
        # Effective dates: review flags and changes of stored dates.
        if scope == Site.Scope.DASHBOARD:
            for field, label in (('on_air_date', 'Site On-Air Date'), ('om_start_date', 'O&M Start Date')):
                value = values.get(field)
                if value and value > today:
                    date_reviews.append(_row_record(name, row, f'{field}_in_future', severity=exceptions.REVIEW, value=value,
                                                    message=f'{label} {value:%d %b %Y} is in the future: the site counts from that date.'))
                if site is not None and getattr(site, field) and value != getattr(site, field):
                    date_changes.append({'site_id': row['site_id'], 'field': field, 'from': getattr(site, field), 'to': value, 'row': row['source_row']})
            if values.get('om_start_date') and values.get('on_air_date') and values['om_start_date'] < values['on_air_date']:
                date_reviews.append(_row_record(name, row, 'om_start_before_on_air', severity=exceptions.REVIEW,
                                                value=f"{values['om_start_date']} < {values['on_air_date']}",
                                                message='O&M Start Date is before the Site On-Air Date: please check both dates.'))
            for field, code in (('om_start_date_issue', 'om_start_date'), ('on_air_date_issue', 'on_air_date')):
                issue = values[field]
                if issue:
                    raw = values.get('om_start_raw' if code == 'om_start_date' else 'on_air_raw')
                    label = 'O&M Start Date' if code == 'om_start_date' else 'Site On-Air Date'
                    date_reviews.append(_row_record(name, row, f'{code}_{issue}', severity=exceptions.REVIEW, value=raw or '',
                                                    message=f'No readable {label} in the matrix: the site does not count as '
                                                            f'{"O&M Start" if code == "om_start_date" else "On-Air"} until one is added.'))
        if site is None:
            plan['insert'][key] = values
            continue
        changed = sorted(f for f, v in values.items() if f != 'source_row' and getattr(site, f) != v)
        if changed or matrix_values or not site.present_in_latest_matrix:
            plan['update'][key] = {'values': values, 'changed': changed, 'matrix_values': matrix_values}
        else:
            plan['unchanged'].append(key)
    rejected_keys = {escalation.site_key(r['site_id']) for r in rejected if r['site_id']}
    plan['missing'] = sorted(k for k, s in existing.items() if k not in rows and k not in rejected_keys and s.present_in_latest_matrix)

    # Identifiers of accepted rows: (kind, key) -> claiming site keys. One claimant and no other owner: assigned.
    stored_ids = {(i.kind, i.key): i.site for i in SiteIdentifier.objects.select_related('site')}
    wanted = defaultdict(dict)
    for key, row in rows.items():
        wanted[(SiteIdentifier.Kind.BSNL_SITE_ID, key)][key] = (row['site_id'], row['source_row'])
        for column, kind in IDENTIFIERS.items():
            raw = (row.get(column) or '').strip() if column in present else ''
            if raw:
                wanted[(kind, key_of(raw))][key] = (raw, row['source_row'])
    for ident, owners in wanted.items():
        kind, ident_key = ident
        owner_now = stored_ids.get(ident)
        if len(owners) > 1 or (owner_now is not None and owner_now.site_key not in owners):
            claims = [{'site_id': rows[k]['site_id'], 'circle': rows[k]['circle'], 'entity': rows[k].get('entity_raw', ''), 'row': r}
                      for k, (_v, r) in sorted(owners.items())]
            if owner_now is not None and owner_now.site_key not in owners:
                claims.append({'site_id': owner_now.bsnl_site_id, 'circle': owner_now.circle, 'entity': owner_now.entity, 'row': None, 'stored': True})
            plan['identifier_conflicts'].append({'kind': kind, 'key': ident_key, 'value': next(iter(owners.values()))[0], 'claims': claims})
        elif owner_now is None:
            value, row_number = next(iter(owners.values()))
            plan['identifiers'].append((kind, ident_key, value, next(iter(owners)), row_number))
    for c in plan['identifier_conflicts']:
        where = lambda x: f"{x['site_id']} ({x['entity']}, {x['circle']}, {'stored' if x.get('stored') else 'row ' + str(x['row'])})"  # noqa: E731
        items.append(exceptions.record(
            source_file=name, code='ambiguous_identifier', identifier=c['value'], row=c['claims'][0]['row'],
            site_id=', '.join(x['site_id'] for x in c['claims']), circle=', '.join(sorted({x['circle'] for x in c['claims']})),
            message=f"{SiteIdentifier.Kind(c['kind']).label} {c['value']} is claimed by {len(c['claims'])} sites; assigned to none.",
            related='; '.join(where(x) for x in c['claims'])))
    items += date_reviews
    plan['exceptions'] = items

    # The Organization must cover every (technology, circle) of the dashboard sites this import writes.
    from apps.organization import services as organization
    organization_check = organization.check_pairs({(row['_technology'], row['circle']) for key, row in rows.items()
                                                   if row['_scope'] == Site.Scope.DASHBOARD and (key in plan['insert'] or key in plan['update'])})
    organization_error = organization.blocking_message(organization_check) if organization_check['blocking'] else ''

    reasons = Counter(r['code'] for r in rejected)
    counts = {'received': len(data['rows']) + len(data['blank_id_rows']), 'accepted': len(plan['insert']) + len(plan['update']),
              'duplicate': len(plan['unchanged']), 'rejected': len(rejected), 'conflict': len(plan['identifier_conflicts']) + reasons['identity_change']}
    review = Counter(i['code'] for i in date_reviews)
    manual_overrides_retained = sum(len(overrides.get(existing[key].pk, [])) for key in rows if key in existing)
    report = {
        'sheet': SHEET, 'columns_found': data['headers'],
        # Known columns this file does not have: their stored values stay unchanged.
        'columns_not_in_file': [c for c in data['absent_columns'] if c in FIELDS or c in IDENTIFIERS],
        'preview': {
            'total_rows': counts['received'], 'new_sites': len(plan['insert']), 'updated_sites': len(plan['update']),
            'unchanged_sites': len(plan['unchanged']), 'rejected_rows': len(rejected),
            'duplicate_site_ids': len(duplicates), 'conflicting_mappings': len(plan['identifier_conflicts']) + reasons['identity_change'],
            'missing_mandatory': reasons['missing_site_id'] + reasons['missing_entity'] + reasons['missing_circle'],
            'invalid_circle_or_technology': reasons['unknown_circle'] + reasons['unknown_entity'],
            'effective_date_issues': sum(review.values()), 'effective_date_changes': len(date_changes),
            'blank_values_kept': sum(blank_kept.values()), 'sites_not_in_file': len(plan['missing']),
            'manual_overrides_retained': manual_overrides_retained,
        },
        'rejected_by_reason': {code: {'rows': n, 'reason': REASONS[code]} for code, n in reasons.most_common()},
        'rejected': sorted(rejected, key=lambda r: (r['row'] or 0))[:MAX_LISTED],
        'duplicates': duplicates[:MAX_LISTED],
        'identity_conflicts': [r for r in rejected if r['code'] == 'identity_change'][:MAX_LISTED],
        'identifier_conflicts': [{'kind': SiteIdentifier.Kind(c['kind']).label, 'value': c['value'], 'sites': [x['site_id'] for x in c['claims']]}
                                 for c in plan['identifier_conflicts']][:MAX_LISTED],
        'effective_date_review': dict(review),
        'effective_date_review_rows': [{'row': i['row'], 'site_id': i['site_id'], 'code': i['code'], 'value': i['value'], 'message': i['message']}
                                       for i in date_reviews][:MAX_LISTED],
        'effective_date_changes': [{**c, 'from': c['from'].isoformat() if c['from'] else None, 'to': c['to'].isoformat() if c['to'] else None}
                                   for c in date_changes][:MAX_LISTED],
        'blank_values_kept': dict(blank_kept.most_common()),
        'changed_fields': dict(Counter(f for u in plan['update'].values() for f in u['changed']).most_common()),
        'sites': {'inserted': len(plan['insert']), 'updated': len(plan['update']), 'unchanged': len(plan['unchanged']),
                  'no_longer_in_matrix': len(plan['missing'])},
        'by_scope': dict(Counter(r['_scope'] for r in rows.values())),
        'by_technology_circle': dict(sorted(Counter(f"{r['_technology'] or 'Outside scope'} {r['circle']}" for r in rows.values()).items())),
        'no_longer_in_matrix': uploads.examples(plan['missing']),
        'new_identifiers': len(plan['identifiers']),
        'organization': organization_check,
        'warnings': [w for w in (
            organization_error,
            f'{len(rejected)} row(s) are rejected and not imported (see the rejected rows).' if rejected else '',
            f"{len(plan['missing'])} site(s) of the previous matrix are not in this file: kept and flagged, not deleted." if plan['missing'] else '',
            f"{len(plan['identifier_conflicts'])} identifier(s) are claimed by more than one site and were assigned to none." if plan['identifier_conflicts'] else '',
            f'{sum(review.values())} effective date(s) need review.' if review else '',
            f'{manual_overrides_retained} manual Site Master override(s) will be retained; matrix values are tracked for explicit reversion.' if manual_overrides_retained else '',
        ) if w],
    }
    return {'plan': plan, 'counts': counts, 'report': report, 'organization_error': organization_error}


FIELDS_BY_DST = {dst: src for src, dst in FIELDS.items()}


def preview(path: Path, name: str, *, user=None) -> UploadBatch:
    batch = uploads.new_batch(KIND, path, name, user)
    try:
        result = analyse(uploads.staged_path(batch), name)
    except uploads.UploadRejected as exc:
        batch.error = str(exc)
        return uploads.record_preview(batch, {}, {'error': str(exc)}, failed=True)
    if result['organization_error']:
        batch.error = result['organization_error']
    return uploads.record_preview(batch, result['counts'], result['report'], failed=bool(result['organization_error']),
                                  exception_items=result['plan']['exceptions'])


def commit(batch: UploadBatch, *, user=None, request=None) -> UploadBatch:
    """Write the previewed plan in one transaction (sites and matrix identifiers only; performance records and legacy
    tables are never touched). Refused when the database changed since the preview."""
    uploads.require_previewed(batch)
    if batch.kind != KIND:
        raise uploads.UploadRejected(f'Upload #{batch.pk} is not a Consolidation Matrix.')
    with uploads.committing(batch) as batch:
        result = analyse(uploads.staged_file(batch), batch.original_filename, lock=True)
        if result['organization_error']:
            raise uploads.UploadRejected(result['organization_error'])
        if not uploads.same_counts(batch, result['counts']):
            raise uploads.UploadRejected('The database changed since the preview; preview the file again before committing.')
        plan = result['plan']
        # Retrospective effective-date changes (On-Air / O&M Start), recorded in full before the sites are updated: they
        # change which days count in months that may already have daily data (recalculated below).
        stored = {key: (site_id, on_air, om_start) for key, site_id, on_air, om_start in Site.objects.filter(site_key__in=list(plan['update']))
                  .values_list('site_key', 'bsnl_site_id', 'on_air_date', 'om_start_date')}
        effective_date_changes = []
        for key, change in plan['update'].items():
            site_id, on_air, om_start = stored[key]
            for field, old in (('on_air_date', on_air), ('om_start_date', om_start)):
                new = change['values'].get(field)
                if field in change['changed'] and old != new:
                    old_text, new_text = (old.isoformat() if old else None), (new.isoformat() if new else None)
                    # 'from' / 'to' as in the preview list (same key), 'old' / 'new' as recorded at commit.
                    effective_date_changes.append({'site_id': site_id, 'field': field, 'old': old_text, 'new': new_text,
                                                   'from': old_text, 'to': new_text, 'row': change['values'].get('source_row')})
        Site.objects.bulk_create([Site(site_key=key, matrix_batch=batch, present_in_latest_matrix=True, **values)
                                  for key, values in plan['insert'].items()], batch_size=2000)
        for key, change in plan['update'].items():
            Site.objects.filter(site_key=key).update(matrix_batch=batch, present_in_latest_matrix=True, updated_at=timezone.now(), **change['values'])
            for field, matrix_value in change['matrix_values'].items():
                SiteManualOverride.objects.filter(site__site_key=key, field=field).update(matrix_value=matrix_value)
        Site.objects.filter(site_key__in=plan['missing']).update(present_in_latest_matrix=False, updated_at=timezone.now())
        ids = dict(Site.objects.values_list('site_key', 'id'))
        # A changed band ID of a site replaces the matrix's previous identifier of that kind.
        for kind, ident_key, value, site_key, row in plan['identifiers']:
            SiteIdentifier.objects.filter(site_id=ids[site_key], kind=kind, batch__kind=KIND).exclude(key=ident_key).delete()
        SiteIdentifier.objects.bulk_create([SiteIdentifier(site_id=ids[site_key], kind=kind, key=ident_key, value=value, batch=batch, source_row=row)
                                            for kind, ident_key, value, site_key, row in plan['identifiers']], batch_size=2000)
        # Ambiguous identifiers: no site keeps them (whichever source assigned them earlier), and they stay blocked.
        conflicts = {(c['kind'], c['key']): c for c in plan['identifier_conflicts']}
        for kind, key in conflicts:
            SiteIdentifier.objects.filter(kind=kind, key=key).delete()
        for (kind, key), c in conflicts.items():
            IdentifierConflict.objects.update_or_create(kind=kind, key=key, defaults={'value': c['value'], 'claims': c['claims'], 'active': True, 'batch': batch})
        # A conflict of an identifier kind this file lists (and does not report again) is resolved.
        listed_kinds = {SiteIdentifier.Kind.BSNL_SITE_ID} | {k for column, k in IDENTIFIERS.items() if column in read_present(batch)}
        for conflict in IdentifierConflict.objects.filter(active=True, kind__in=listed_kinds):
            if (conflict.kind, conflict.key) not in conflicts:
                conflict.active = False
                conflict.save(update_fields=['active', 'updated_at'])
        uploads.mark_committed(batch, {'committed': result['report']['sites'], 'effective_date_changes': effective_date_changes})
    # Effective dates may have changed: monthly results of the months with daily records follow the matrix.
    from .models import DailySitePerformance
    uploads.refresh_after_daily_write(DailySitePerformance.objects.dates('report_date', 'month'), request)
    audit('sitedata.matrix_committed', request, batch=batch.pk, file=batch.original_filename, effective_date_changes=len(effective_date_changes),
          **result['report']['sites'])
    if effective_date_changes:
        audit('sitedata.matrix_effective_dates_changed', request, batch=batch.pk, changes=len(effective_date_changes),
              sites=len({c['site_id'] for c in effective_date_changes}))
    return batch


def read_present(batch: UploadBatch) -> set:
    """Parser fields of the columns the batch's file has (from its preview report)."""
    found = {h.casefold() for h in (batch.report or {}).get('columns_found', [])}
    return {COLUMNS[h] for h in found if h in COLUMNS}


def _json_value(value):
    return value.isoformat() if hasattr(value, 'isoformat') else value

