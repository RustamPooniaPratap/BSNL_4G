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
  - a row with no identifier at all is rejected (no_identifier);
  - an identifier the matrix gives to several sites (IdentifierConflict) is never matched (ambiguous_identifier).
  No first match, no fuzzy matching.
- Rows of the other technology are counted and skipped (they belong to that technology's upload).
- A site on several rows of one file: identical availability = one record (duplicates counted); different values =
  all of those rows rejected.
- A reporting date after today is refused (the whole file); a row dated after today is rejected (future_date).

Whole-circle classification (the CNMC file is a dump of every BTS of the circle). Every row is in exactly one category,
kept in report['rows'] with its code, and counted in report['classification'] (the counts sum to the rows received):
- matched: resolves to a dashboard site of the selected technology and circle (ready, identical, conflict_existing,
  duplicate_row, not_reported = blank availability), and rows of a programme site of the OTHER technology
  (other_technology: counted here, never imported, they belong to the other upload);
- unmatched_programme (pending; the only rows counted in records_unmatched): a programme identifier that does not resolve
  to exactly one site of the selected technology and circle: ambiguous_identifier, identifier_mismatch,
  identifier_not_in_mapping, site_of_other_circle, and unmatched_programme (an identifier present in
  sitedata_siteidentifier of another kind, in sitedata_identifierconflict or in the LWE mapping history, naming no site);
- outside_programme (informational, not a warning, not pending): no identifier of the row is known anywhere in those
  tables (outside_programme), or it resolves to an outside-scope site such as Sterlite / VI-HPSC (outside_scope);
- invalid (records_rejected): other_report_date, future_date, other_circle, blank_site_id, no_identifier,
  invalid_identifier (identifier format), invalid_availability, availability_out_of_range, conflicting_rows, malformed_row.
Rejected and pending rows are in the exception report (severity rejected / unmatched); outside-programme rows are there
with severity info.
"""
from __future__ import annotations

import csv
import re
import io
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from django.db import transaction
from django.utils import timezone

from apps.accounts.audit import audit
from .sources import cnmc_csv as raw_parser
from .sources.cnmc_csv import canonical_circle

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


# Row categories of a whole-circle dump (every row is in exactly one; see the module notes).
MATCHED, UNMATCHED_PROGRAMME, OUTSIDE_PROGRAMME, INVALID = 'matched', 'unmatched_programme', 'outside_programme', 'invalid'
CATEGORIES = (MATCHED, UNMATCHED_PROGRAMME, OUTSIDE_PROGRAMME, INVALID)
CATEGORY = {
    **dict.fromkeys(('ready', 'identical', 'conflict_existing', 'duplicate_row', 'other_technology', 'not_reported'), MATCHED),
    **dict.fromkeys(('unmatched_programme', 'ambiguous_identifier', 'identifier_mismatch', 'identifier_not_in_mapping',
                     'site_of_other_circle', 'unmatched'), UNMATCHED_PROGRAMME),  # 'unmatched': uploads before the classification
    **dict.fromkeys(('outside_programme', 'outside_scope'), OUTSIDE_PROGRAMME),
    **dict.fromkeys(('other_report_date', 'future_date', 'other_circle', 'blank_site_id', 'no_identifier', 'invalid_identifier',
                     'invalid_availability', 'availability_out_of_range', 'conflicting_rows', 'malformed_row'), INVALID),
}
PENDING_CODES = {code for code, category in CATEGORY.items() if category == UNMATCHED_PROGRAMME}


def category_of(code: str) -> str:
    return CATEGORY.get(code, INVALID)


def _unresolved(tokens, index, technology):
    """(site, problem) of a row none of whose identifiers resolves by the matching rule of its technology. Deterministic:
    - an identifier (any kind) of sites that are all outside the dashboard scope -> that site (outside_scope); of dashboard
      sites all of the other technology -> that site (other_technology: the other upload's row);
    - otherwise an identifier known to the programme (any kind in sitedata_siteidentifier, an identifier conflict, the LWE
      mapping history) -> unmatched_programme (pending);
    - nothing known anywhere -> outside_programme (a BTS outside the programme; informational)."""
    sites = {s.pk: s for t in tokens for s in index.sites_of_key(t)}
    listed = sorted(sites.values(), key=lambda s: s.bsnl_site_id)
    if listed and all(s.reporting_scope != Site.Scope.DASHBOARD for s in listed):
        return listed[0], None
    if listed and all(s.reporting_scope == Site.Scope.DASHBOARD and s.technology != technology for s in listed):
        return listed[0], None
    text = ', '.join(tokens)
    if listed:
        return None, ('unmatched_programme', f'{text}: an identifier of {", ".join(s.bsnl_site_id for s in listed)} in the site master, '
                                             'but not one that matches a row of this technology; kept pending (no site is created).')
    where = next((w for w in (index.known_where(t) for t in tokens) if w), '')
    if where:
        return None, ('unmatched_programme', f'{text}: known from {where}, but it names no site; kept pending (no site is created).')
    return None, ('outside_programme', f'{text}: no identifier of the row is known to the site master or the LWE mapping '
                                       '(a BTS outside the programme).')


def _resolve_4g(row, index):
    raw = row['bts_ip_id']
    site = index.get(SiteIdentifier.Kind.BSNL_SITE_ID, raw) or index.get(SiteIdentifier.Kind.BTS_IP_ID, raw)
    if site is not None:
        return site, None
    if index.is_blocked(SiteIdentifier.Kind.BSNL_SITE_ID, raw) or index.is_blocked(SiteIdentifier.Kind.BTS_IP_ID, raw):
        return None, ('ambiguous_identifier', f'{raw} is claimed by several sites in the Consolidation Matrix and cannot be matched.')
    if not is_valid_id(raw):
        return None, ('invalid_identifier', f'BTS IP ID "{raw}" is not a single identifier (letters, digits and . _ / - only).')
    return _unresolved([raw], index, Technology.G4)


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
        # Never split or matched: an invalid identifier format (invalid category), naming the sites it touches if any.
        touched = {s.bsnl_site_id for f, ts in tokens.items() for t in ts if is_valid_id(t)
                   for s in [index.get(LWE_IDS[f], t) or (index.get(SiteIdentifier.Kind.BSNL_SITE_ID, t) if f == 'bts_ip_id' else None)] if s}
        touched |= {s.bsnl_site_id for f, t in invalid for part in re.split(r'[;,\s]+', t) if part
                    for s in [index.get(LWE_IDS[f], part)] if s}
        text = ', '.join(f'{LABELS[f]} "{t}"' for f, t in invalid)
        return None, ('invalid_identifier', f'{text}: not a single identifier (identifiers are separated by ";;" only)'
                                            + (f'; the row concerns {", ".join(sorted(touched))}.' if touched else '.')), []
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
        site, problem = _unresolved([t for _, t in unresolved], index, Technology.LWE)
        return site, problem, []
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
    today = timezone.localdate()
    if reporting_date > today:
        raise uploads.UploadRejected(f'The reporting date {reporting_date:%d-%m-%Y} is in the future; a daily file can only be '
                                     f'imported for today ({today:%d-%m-%Y}) or an earlier date.')
    rows = read(path)
    index = IdentifierIndex()
    resolve = _resolve_lwe if technology == Technology.LWE else _resolve_4g
    rejected, pending, outside_rows, skipped, not_reported_rows = [], [], [], Counter(), []
    by_site = defaultdict(list)
    outcome = {}  # line -> (code, message, site): the result of every row, for the preview and the validation report

    def entry(row, code, message, value=''):
        return {'line': row['line'], 'id': row.get('bts_ip_id', ''), 'code': code, 'message': message, 'value': value,
                'ids': ', '.join(row.get(f, '') for f in LWE_IDS if row.get(f, ''))}

    def reject(row, code, message, value=''):  # invalid
        rejected.append(entry(row, code, message, value))
        outcome[row['line']] = (code, message, None)

    def pend(row, code, message, site=None):  # unmatched_programme
        pending.append(entry(row, code, message, row.get(rules.AVAILABILITY_FIELD, '')))
        outcome[row['line']] = (code, message, site)

    def outside(row, code, message, site=None):  # outside_programme (informational)
        skipped[code] += 1
        outside_rows.append(entry(row, code, message, row.get(rules.AVAILABILITY_FIELD, '')))
        outcome[row['line']] = (code, message, site)

    for row in rows:
        day = raw_parser.parse_date(row['report_date'])
        if day is not None and day > today:
            reject(row, 'future_date', f"Report Date {row['report_date']} is in the future.")
            continue
        if day != reporting_date:
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
            if code in PENDING_CODES:
                pend(row, code, message)
            elif code == 'outside_programme':
                outside(row, code, message)
            else:
                reject(row, code, message)
            continue
        if site.reporting_scope != Site.Scope.DASHBOARD:
            outside(row, 'outside_scope', f'{site.bsnl_site_id} is outside the dashboard reporting scope ({site.entity}).', site)
            continue
        if site.technology != technology:
            skipped['other_technology'] += 1
            outcome[row['line']] = ('other_technology', f'{site.bsnl_site_id} is a {site.technology} site (imported by that upload).', site)
            continue
        if site.circle != circle:
            pend(row, 'site_of_other_circle', f'{site.bsnl_site_id} is a site of circle {site.circle}.', site)
            continue
        availability = rules.check_availability(row.get(rules.AVAILABILITY_FIELD))
        if availability.code == 'not_reported':
            skipped['not_reported'] += 1
            not_reported_rows.append((row, availability.message))
            outcome[row['line']] = ('not_reported', availability.message, site)
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
        for repeat, _site, _v in entries[1:]:
            outcome[repeat['line']] = ('duplicate_row', f'Repeat of line {row["line"]} with the same value: one record.', site)
        values.append(daily.DailyValue(site.pk, technology, site.circle, reporting_date, value, rules.outage_from_availability(value),
                                       row['line'], row['bts_ip_id']))
    classified = daily.classify(values, KINDS[technology])
    sites = {s.pk: s for s in Site.objects.filter(pk__in=[v.site_id for v in values])}
    for v in classified.new + [v for v, _ in classified.superseded]:
        outcome[v.source_row] = ('ready', '', sites[v.site_id])
    for v in classified.duplicate + [v for v, _ in classified.upgraded]:
        outcome[v.source_row] = ('identical', 'The same value is already stored for this site and date.', sites[v.site_id])
    for v, rec in classified.conflict:
        outcome[v.source_row] = ('conflict_existing', f'{rec.availability_pct:.6g}% is already stored from {rec.batch.get_kind_display()} '
                                                      f'({rec.batch.original_filename}); it is kept (equal or higher precedence).', sites[v.site_id])
    counts = {'received': len(rows), 'rejected': len(rejected), 'unmatched': len(pending),
              'accepted': len(classified.new), 'duplicate': duplicates + len(classified.duplicate), 'conflict': len(classified.conflict),
              'superseded': len(classified.superseded)}
    in_scope = Site.objects.filter(reporting_scope=Site.Scope.DASHBOARD, technology=technology, circle=circle).count()
    row_list = []
    for row in rows:
        code, message, site = outcome.get(row['line'], ('malformed_row', 'The row could not be classified.', None))
        checked = rules.check_availability(row.get(rules.AVAILABILITY_FIELD))
        row_list.append({'line': row['line'], 'raw_id': row.get('bts_ip_id', ''), 'site_id': site.bsnl_site_id if site else None,
                         'site_name': site.site_name if site else row.get('site_name', ''), 'circle': row.get('circle', ''),
                         'report_date': row.get('report_date', ''), 'raw_availability': row.get(rules.AVAILABILITY_FIELD, ''),
                         'availability': checked.value, 'outage_minutes': None if checked.value is None else rules.outage_from_availability(checked.value),
                         'code': code, 'category': category_of(code), 'message': message})
    by_category = Counter(r['category'] for r in row_list)
    report = {
        'technology': technology, 'circle': circle, 'reporting_date': reporting_date.isoformat(), 'rows': row_list,
        'availability_column': rules.AVAILABILITY_COLUMN,
        # Every row in exactly one category (the four counts sum to the rows received); only unmatched_programme is pending.
        'classification': {c: by_category.get(c, 0) for c in CATEGORIES},
        'classification_by_code': {c: dict(Counter(r['code'] for r in row_list if r['category'] == c)) for c in CATEGORIES},
        'rejected_by_reason': dict(Counter(r['code'] for r in rejected)), 'rejected_rows': uploads.examples(rejected, 50),
        'unmatched_by_reason': dict(Counter(r['code'] for r in pending)), 'unmatched_rows': uploads.examples(pending, 50),
        'skipped': dict(skipped), 'sites_in_scope': in_scope, 'sites_with_value': len(values),
        'sites_without_value': max(0, in_scope - len(values)), 'conflicts': daily.conflict_examples(classified),
        'warnings': [w for w in (
            (f'{len(pending)} row(s) carry a programme identifier that does not resolve to one {technology} site of {circle}; '
             'they are kept pending.') if pending else '',
            (f'{len(classified.conflict)} site-day value(s) differ from a stored value of equal or higher precedence (e.g. the Uptime Master) '
             'and were logged as conflicts.') if classified.conflict else '',
        ) if w],
    }

    def record(x, severity):
        return exceptions.record(source_file=path.name, code=x['code'], severity=severity, row=x['line'], site_id=x['id'], circle=circle,
                                 report_date=reporting_date, identifier=x['ids'], value=x['value'], message=x['message'])
    items = [record(x, exceptions.REJECTED) for x in rejected]
    items += [record(x, exceptions.UNMATCHED) for x in pending]
    items += [record(x, exceptions.INFO) for x in outside_rows]  # informational: neither pending nor a warning
    items += [exceptions.record(source_file=path.name, code='not_reported', severity='not_reported', row=row['line'], site_id=row.get('bts_ip_id', ''),
                                circle=circle, report_date=reporting_date, message=message) for row, message in not_reported_rows]
    items += daily.exception_items(classified, path.name)
    return {'classified': classified, 'counts': counts, 'report': report, 'exceptions': items}


def preview(path: Path, name: str, *, technology: str, circle: str, reporting_date: date, user=None) -> UploadBatch:
    if technology not in KINDS:
        raise uploads.UploadRejected(f'Unknown technology {technology!r}.')
    batch = uploads.new_batch(KINDS[technology], path, name, user, technology=technology, circle=circle, reporting_date=reporting_date)
    try:
        result = analyse(uploads.staged_path(batch), technology=technology, circle=circle, reporting_date=reporting_date)
    except uploads.UploadRejected as exc:
        batch.error = str(exc)
        return uploads.record_preview(batch, {}, {'error': str(exc)}, failed=True)
    for item in result['exceptions']:
        item['source_file'] = name
    return uploads.record_preview(batch, result['counts'], result['report'], exception_items=result['exceptions'])


def commit(batch: UploadBatch, *, user=None, request=None) -> UploadBatch:
    uploads.require_previewed(batch)
    with uploads.committing(batch) as batch:
        result = analyse(uploads.staged_file(batch), technology=batch.technology, circle=batch.circle, reporting_date=batch.reporting_date)
        if not uploads.same_counts(batch, result['counts']):
            raise uploads.UploadRejected('The database changed since the preview; preview the file again before committing.')
        daily.write(batch, result['classified'])
        uploads.mark_committed(batch)
    uploads.refresh_after_daily_write(result['classified'].written_dates(), request)
    audit('sitedata.raw_csv_committed', request, batch=batch.pk, technology=batch.technology, circle=batch.circle,
          date=batch.reporting_date, **result['counts'])
    return batch
