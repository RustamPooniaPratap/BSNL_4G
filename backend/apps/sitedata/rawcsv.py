"""Raw daily CSV (CNMC dump) import for 4G Saturation and LWE into the central daily table.

One file per circle and reporting date; a circle's dump can hold both 4G and LWE rows, and each technology is imported
by its own upload. The Report Date must be the entered date and the Circle the entered circle. Availability and outage
follow the shared rules (rules.py), the same for 4G and LWE: "Nw Avail (4G TCS)" as a percentage, 0-100, a blank is not
reported (never 0), outage = 1440 x (1 - availability / 100).

Site resolution:
- 4G Saturation: the BTS IP ID is the site's BSNL Site ID (verified on the Odisha dump).
- LWE (confirmed 4 Nov 2026): BTS IP ID, BTS Site ID (2100) and BTS Site ID (700) are alternative identifiers of the
  same site. Each cell is split on ";;" (identifiers.split_ids); a token with any other separator is rejected
  (invalid_identifier). Then:
  - every 2100 / 700 token must match the mapping column of its kind (identifier_not_in_mapping otherwise);
  - a BTS IP ID token may match the mapping BTS IP ID column or the site's Master ID; a BTS IP ID that appears nowhere
    is not mandatory and is ignored (counted), but one naming another site is a conflict;
  - every resolved token must name the same site and Master ID (identifier_mismatch otherwise); one band token that
    resolves is enough;
  - a row with no identifier at all is rejected (no_identifier); a row none of whose identifiers is known is unmatched
    (not a site of the master);
  - an identifier the matrix gives to several sites (IdentifierConflict) is never matched (ambiguous_identifier).
  No first match, no fuzzy matching.
- Rows of the other technology are counted and skipped (they belong to that technology's upload).
- A site on several rows of one file: identical availability = one record (duplicates counted); different values =
  all of those rows rejected.
Every rejected or unmatched row is in the upload's exception report.
"""
from __future__ import annotations

import csv
import re
import io
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from django.db import transaction

from apps.accounts.audit import audit
from apps.uptimedb.raw import parser as raw_parser
from apps.uptimedb.raw.rules import canonical_circle

from . import daily, exceptions, rules, uploads
from .identifiers import IdentifierIndex, is_valid_id, split_ids
from .models import Site, SiteIdentifier, Technology, UploadBatch

KINDS = {Technology.G4: UploadBatch.Kind.RAW_CSV_4G, Technology.LWE: UploadBatch.Kind.RAW_CSV_LWE}
COLUMNS = {'btsipid': 'bts_ip_id', 'btssiteid2100': 'band_2100', 'btssiteid700': 'band_700', 'circle': 'circle', 'reportdate': 'report_date',
           'nwavail4g': 'avail_4g', 'nwavail4gtcs': 'avail_4g_tcs', 'btsname': 'site_name'}
REQUIRED = ('bts_ip_id', 'circle', 'report_date', 'avail_4g_tcs')
LWE_IDS = {'bts_ip_id': SiteIdentifier.Kind.BTS_IP_ID, 'band_2100': SiteIdentifier.Kind.BAND_2100, 'band_700': SiteIdentifier.Kind.BAND_700}
MAX_BYTES = 50 * 1024 * 1024


def read(path: Path) -> list[dict]:
    """Rows of a daily dump as {field: text, 'line': n}. Header found by column names in the first lines."""
    data = path.read_bytes()
    if len(data) > MAX_BYTES:
        raise uploads.UploadRejected('The file is larger than 50 MB.')
    try:
        text, _encoding = raw_parser._decode(data)
    except raw_parser.RawParseError as exc:
        raise uploads.UploadRejected(str(exc)) from exc
    lines = list(csv.reader(io.StringIO(text)))
    for at, header in enumerate(lines[:raw_parser.HEADER_SEARCH_ROWS]):
        keys = [raw_parser.norm(h) for h in header]
        if 'btsipid' in keys:
            if 'reportdate' not in keys:
                raise uploads.UploadRejected('The file has no "Report Date" column (the monthly dump cannot be imported as a day).')
            positions = {COLUMNS[k]: i for i, k in enumerate(keys) if k in COLUMNS}
            missing = [f for f in REQUIRED if f not in positions]
            if missing:
                raise uploads.UploadRejected(f'Missing columns: {", ".join(missing)}.')
            rows = []
            for n, cells in enumerate(lines[at + 1:], start=at + 2):
                if not any(c.strip() for c in cells):
                    continue
                rows.append({**{f: cells[i].strip() if i < len(cells) else '' for f, i in positions.items()}, 'line': n})
            if not rows:
                raise uploads.UploadRejected('The file has a header but no data rows.')
            return rows
    raise uploads.UploadRejected(f'No header row with "BTS IP ID" in the first {raw_parser.HEADER_SEARCH_ROWS} lines.')


def _resolve_4g(row, index):
    site = index.get(SiteIdentifier.Kind.BSNL_SITE_ID, row['bts_ip_id'])
    if site is None and index.get(SiteIdentifier.Kind.BTS_IP_ID, row['bts_ip_id']) is not None:
        return index.get(SiteIdentifier.Kind.BTS_IP_ID, row['bts_ip_id']), None
    return site, (None if site else ('unmatched', f"{row['bts_ip_id']} is not a site of the site master."))


LABELS = {'bts_ip_id': 'BTS IP ID', 'band_2100': 'BTS Site ID (2100)', 'band_700': 'BTS Site ID (700)'}


def _resolve_lwe(row, index):
    """(site, problem, notes). problem = (code, message) or None."""
    tokens = {f: split_ids(row.get(f, '')) for f in LWE_IDS}
    if not any(tokens.values()):
        return None, ('no_identifier', 'No BTS IP ID, BTS Site ID (2100) or BTS Site ID (700) on the row.'), []
    # A row whose BTS IP ID is a site of the other technology belongs to that technology's upload (skipped, not judged).
    for t in tokens['bts_ip_id']:
        own = index.get(SiteIdentifier.Kind.BSNL_SITE_ID, t)
        if own is not None and own.technology != Technology.LWE:
            return own, None, []
    invalid = [(f, t) for f, ts in tokens.items() for t in ts if not is_valid_id(t)]
    if invalid:
        # Never split or matched. Classified only: rejected when the row touches a known site (a valid token, or a part
        # of the malformed cell, names one); otherwise the row is not a site of the master (unmatched), like any other.
        touched = {s.bsnl_site_id for f, ts in tokens.items() for t in ts if is_valid_id(t)
                   for s in [index.get(LWE_IDS[f], t) or (index.get(SiteIdentifier.Kind.BSNL_SITE_ID, t) if f == 'bts_ip_id' else None)] if s}
        touched |= {s.bsnl_site_id for f, t in invalid for part in re.split(r'[;,\s]+', t) if part
                    for s in [index.get(LWE_IDS[f], part)] if s}
        text = ', '.join(f'{LABELS[f]} "{t}"' for f, t in invalid)
        if not touched:
            return None, ('unmatched', f'{text}: not a single identifier, and no identifier of the row is known.'), []
        return None, ('invalid_identifier', f'{text}: not a single identifier (identifiers are separated by ";;" only); '
                                            f'the row concerns {", ".join(sorted(touched))}.'), []
    blocked = [t for f, ts in tokens.items() for t in ts if index.is_blocked(LWE_IDS[f], t)]
    if blocked:
        return None, ('ambiguous_identifier', f"{', '.join(blocked)} {'is' if len(blocked) == 1 else 'are'} claimed by several sites in the "
                                              'Consolidation Matrix and cannot be matched.'), []
    resolved, unresolved = {}, []
    for f, ts in tokens.items():
        for t in ts:
            site = index.get(LWE_IDS[f], t)
            if site is None and f == 'bts_ip_id':  # the BTS IP ID may be the site's own (Master / BSNL) ID
                site = index.get(SiteIdentifier.Kind.BSNL_SITE_ID, t)
            (unresolved.append((f, t)) if site is None else resolved.__setitem__((f, t), site))
    if not resolved:
        return None, ('unmatched', f"{', '.join(t for _, t in unresolved)}: not in the LWE Band ID mapping or the site master."), []
    if len({s.pk for s in resolved.values()}) > 1:
        return None, ('identifier_mismatch', 'The identifiers of this row map to different Master IDs: '
                                             + ', '.join(f'{t} -> {s.bsnl_site_id}' for (_f, t), s in resolved.items()) + '.'), []
    site = next(iter(resolved.values()))
    bands_missing = [f'{LABELS[f]} {t}' for f, t in unresolved if f != 'bts_ip_id']
    if bands_missing:
        return None, ('identifier_not_in_mapping', f"{', '.join(bands_missing)} {'is' if len(bands_missing) == 1 else 'are'} not in the mapping, "
                                                   f'while the other identifiers of the row name {site.bsnl_site_id}.'), []
    notes = ['bts_ip_id_not_in_mapping' for f, _t in unresolved if f == 'bts_ip_id']
    return site, None, notes


def analyse(path: Path, *, technology: str, circle: str, reporting_date: date) -> dict:
    rows = read(path)
    index = IdentifierIndex()
    resolve = _resolve_lwe if technology == Technology.LWE else _resolve_4g
    rejected, skipped, unmatched_rows, not_reported_rows = [], Counter(), [], []
    by_site = defaultdict(list)

    def reject(row, code, message, value=''):
        rejected.append({'line': row['line'], 'id': row.get('bts_ip_id', ''), 'code': code, 'message': message, 'value': value,
                         'ids': ', '.join(row.get(f, '') for f in LWE_IDS if row.get(f, ''))})

    for row in rows:
        if raw_parser.parse_date(row['report_date']) != reporting_date:
            reject(row, 'other_report_date', f"Report Date {row['report_date']} is not {reporting_date:%d-%m-%Y}.")
            continue
        if canonical_circle(row['circle'], technology) != circle:
            reject(row, 'other_circle', f"Circle {row['circle']} is not {circle}.")
            continue
        if technology == Technology.G4 and not row['bts_ip_id']:
            reject(row, 'blank_site_id', 'BTS IP ID is blank.')
            continue
        if technology == Technology.LWE:
            site, problem, notes = resolve(row, index)
            for note in notes:
                skipped[note] += 1
        else:
            site, problem = resolve(row, index)
        if problem:
            code, message = problem
            if code == 'unmatched':
                skipped['unmatched'] += 1
                unmatched_rows.append((row, message))
            else:
                reject(row, code, message)
            continue
        if site.reporting_scope != Site.Scope.DASHBOARD:
            skipped['outside_scope'] += 1
            continue
        if site.technology != technology:
            skipped['other_technology'] += 1
            continue
        if site.circle != circle:
            reject(row, 'site_of_other_circle', f'{site.bsnl_site_id} is a site of circle {site.circle}.')
            continue
        availability = rules.check_availability(row.get(rules.AVAILABILITY_FIELD))
        if availability.code == 'not_reported':
            skipped['not_reported'] += 1
            not_reported_rows.append((row, availability.message))
            continue
        if not availability.usable:
            reject(row, availability.code, availability.message, row.get(rules.AVAILABILITY_FIELD, ''))
            continue
        by_site[site.pk].append((row, site, availability.value))

    values, duplicates = [], 0
    for site_id, entries in by_site.items():
        distinct = {round(v, 6) for _, _, v in entries}
        if len(distinct) > 1:
            for row, site, v in entries:
                reject(row, 'conflicting_rows', f'{site.bsnl_site_id} is on {len(entries)} rows with different availability ({", ".join(map(str, sorted(distinct)))}).')
            continue
        duplicates += len(entries) - 1
        row, site, value = entries[0]
        values.append(daily.DailyValue(site.pk, technology, site.circle, reporting_date, value, rules.outage_from_availability(value),
                                       row['line'], row['bts_ip_id']))
    classified = daily.classify(values, KINDS[technology])
    counts = {'received': len(rows), 'rejected': len(rejected), 'unmatched': skipped['unmatched'],
              'accepted': len(classified.new), 'duplicate': duplicates + len(classified.duplicate), 'conflict': len(classified.conflict),
              'superseded': len(classified.superseded)}
    in_scope = Site.objects.filter(reporting_scope=Site.Scope.DASHBOARD, technology=technology, circle=circle).count()
    report = {
        'technology': technology, 'circle': circle, 'reporting_date': reporting_date.isoformat(),
        'availability_column': rules.AVAILABILITY_COLUMN,
        'rejected_by_reason': dict(Counter(r['code'] for r in rejected)), 'rejected_rows': uploads.examples(rejected, 50),
        'skipped': dict(skipped), 'sites_in_scope': in_scope, 'sites_with_value': len(values),
        'sites_without_value': max(0, in_scope - len(values)), 'conflicts': daily.conflict_examples(classified),
        'warnings': [w for w in (
            (f'{len(classified.conflict)} site-day value(s) differ from a stored value of equal or higher precedence (e.g. the Uptime Master) '
             'and were logged as conflicts.') if classified.conflict else '',
        ) if w],
    }
    items = [exceptions.record(source_file=path.name, code=x['code'], row=x['line'], site_id=x['id'], circle=circle, report_date=reporting_date,
                               identifier=x['ids'], value=x['value'], message=x['message']) for x in rejected]
    items += [exceptions.record(source_file=path.name, code='not_in_site_master', severity=exceptions.UNMATCHED, row=row['line'], site_id=row.get('bts_ip_id', ''),
                                circle=circle, report_date=reporting_date, value=row.get(rules.AVAILABILITY_FIELD, ''), message=message)
              for row, message in unmatched_rows]
    items += [exceptions.record(source_file=path.name, code='not_reported', severity='not_reported', row=row['line'], site_id=row.get('bts_ip_id', ''),
                                circle=circle, report_date=reporting_date, message=message) for row, message in not_reported_rows]
    items += daily.exception_items(classified, path.name)
    return {'classified': classified, 'counts': counts, 'report': report, 'exceptions': items}


def preview(path: Path, name: str, *, technology: str, circle: str, reporting_date: date, user=None) -> UploadBatch:
    if technology not in KINDS:
        raise uploads.UploadRejected(f'Unknown technology {technology!r}.')
    batch = uploads.new_batch(KINDS[technology], path, name, user, technology=technology, circle=circle, reporting_date=reporting_date)
    try:
        result = analyse(Path(batch.stored_path), technology=technology, circle=circle, reporting_date=reporting_date)
    except uploads.UploadRejected as exc:
        batch.error = str(exc)
        return uploads.record_preview(batch, {}, {'error': str(exc)}, failed=True)
    for item in result['exceptions']:
        item['source_file'] = name
    return uploads.record_preview(batch, result['counts'], result['report'], exception_items=result['exceptions'])


def commit(batch: UploadBatch, *, user=None, request=None) -> UploadBatch:
    uploads.require_previewed(batch)
    result = analyse(uploads.staged_file(batch), technology=batch.technology, circle=batch.circle, reporting_date=batch.reporting_date)
    if not uploads.same_counts(batch, result['counts']):
        raise uploads.UploadRejected('The database changed since the preview; preview the file again before committing.')
    with transaction.atomic():
        daily.write(batch, result['classified'])
        uploads.mark_committed(batch)
    audit('sitedata.raw_csv_committed', request, batch=batch.pk, technology=batch.technology, circle=batch.circle,
          date=batch.reporting_date, **result['counts'])
    return batch
