"""LWE Band ID mapping import into the database ("LWE Band ID.xlsx": Circle, BTS IP ID, BTS Site ID (2100),
BTS Site ID (700), btsIpId -Master ID).

The workbook is reference data stored in the database, never read at runtime and never hard-coded:
- every import keeps all its rows (LweMappingRow: accepted, rejected and duplicate, as written) and their normalised
  identifiers (LweMappingIdentifier), plus the staged workbook copy and checksum (UploadBatch); nothing is deleted;
- the active mapping used to match raw LWE rows is SiteIdentifier (unique per kind), each identifier pointing to the
  mapping row that supplied it.

Confirmed rules (4 Nov 2026):
- Every identifier cell is split on ";;" (identifiers.split_ids: trimmed, empty tokens and placeholders such as "-"
  dropped, every distinct identifier kept). A token with any other separator (e.g. a single ";") is invalid: the row is
  rejected; nothing is split or chosen.
- The Master ID is required; the BTS IP ID is not (a row needs at least one identifier of any kind).
- A row is accepted only if its Master ID is an LWE site of the site master with the same circle; the Master ID is on
  one row only (identical repeated rows are duplicates); none of its identifiers appears on a row of another Master
  ID; none already names a different site (held for review: an active mapping is never replaced automatically when it
  conflicts); and none is ambiguous in the matrix (IdentifierConflict).

A new workbook version:
- accepted rows are added (site had no mapping), changed (identifiers differ: the site's earlier mapping identifiers
  of that kind are replaced by the new ones) or unchanged;
- a site whose new row is rejected, or that is not in the new workbook, keeps its active mapping and is reported for
  review; nothing is removed automatically.
The import summary is in the upload's report and every rejected or review item in its exception report (CSV).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

from django.db import transaction
from openpyxl import load_workbook

from apps.accounts.audit import audit
from apps.uptimedb.raw.parser import norm
from apps.uptimedb.raw.rules import canonical_circle

from . import exceptions, uploads
from .identifiers import SEPARATOR, IdentifierIndex, is_valid_id, key_of, split_ids
from .models import LweMappingIdentifier, LweMappingRow, Site, SiteIdentifier, Technology, UploadBatch

KIND = UploadBatch.Kind.LWE_BAND_MAPPING
COLUMNS = {'circle': 'circle', 'btsipid': 'bts_ip_id', 'btssiteid2100': 'band_2100', 'btssiteid700': 'band_700', 'btsipidmasterid': 'master_id'}
HEADERS = {'circle': 'Circle', 'bts_ip_id': 'BTS IP ID', 'band_2100': 'BTS Site ID (2100)', 'band_700': 'BTS Site ID (700)', 'master_id': 'btsIpId -Master ID'}
REQUIRED = ('master_id',)
ID_KINDS = {'bts_ip_id': SiteIdentifier.Kind.BTS_IP_ID, 'band_2100': SiteIdentifier.Kind.BAND_2100, 'band_700': SiteIdentifier.Kind.BAND_700}
MAPPING_KINDS = set(ID_KINDS.values())
HEADER_ROWS = 10


def read_rows(path: Path) -> tuple[str, list[str], list[dict]]:
    """(sheet, headers found, rows): the first sheet with a "btsIpId -Master ID" header and at least one ID column."""
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        for sheet in book.worksheets:
            rows = sheet.iter_rows(values_only=True)
            for line, header in enumerate(rows, start=1):
                if line > HEADER_ROWS:
                    break
                fields = {i: COLUMNS[norm(str(h or ''))] for i, h in enumerate(header) if norm(str(h or '')) in COLUMNS}
                if set(REQUIRED) <= set(fields.values()) and set(fields.values()) & set(ID_KINDS):
                    out = []
                    for row_number, row in enumerate(rows, start=line + 1):
                        values = {f: str(row[i]).strip() if i < len(row) and row[i] is not None else '' for i, f in fields.items()}
                        if any(values.values()):
                            out.append({**values, 'row': row_number})
                    return sheet.title, [HEADERS[f] for f in fields.values()], out
    finally:
        book.close()
    raise uploads.UploadRejected('No sheet with a "btsIpId -Master ID" column and a BTS IP ID / BTS Site ID (2100) / (700) column was found.')


def active_mapping() -> tuple[dict, dict]:
    """(from mapping imports, from any source): site -> {kind: keys} of the active BTS IP ID / 2100 / 700 identifiers."""
    mapped, every = defaultdict(lambda: defaultdict(set)), defaultdict(lambda: defaultdict(set))
    for site_id, kind, key, batch_kind in SiteIdentifier.objects.filter(kind__in=MAPPING_KINDS).values_list('site_id', 'kind', 'key', 'batch__kind'):
        every[site_id][kind].add(key)
        if batch_kind == KIND:
            mapped[site_id][kind].add(key)
    return mapped, every


def analyse(path: Path) -> dict:
    sheet, headers, rows = read_rows(path)
    sites = {s.site_key: s for s in Site.objects.filter(technology=Technology.LWE)}
    other_sites = set(Site.objects.exclude(technology=Technology.LWE).values_list('site_key', flat=True))
    index = IdentifierIndex()
    current, every = active_mapping()
    limits = {'circle': 60, 'bts_ip_id': 200, 'band_2100': 200, 'band_700': 200, 'master_id': 80}  # LweMappingRow columns
    for r in rows:
        r['_tokens'] = {f: split_ids(r.get(f, '')) for f in ID_KINDS}
        r['_too_long'] = [f'{HEADERS[f]} ({len(r.get(f, ""))} characters, limit {n})' for f, n in limits.items() if len(r.get(f, '')) > n]
        for f in limits:  # stored as written up to the limit only when the row is rejected for its length
            r[f'_{f}_stored'] = r.get(f, '')[:limits[f]]
        r['_status'], r['_code'], r['_message'], r['_site'], r['_circle'], r['_change'] = '', '', '', None, '', ''

    def reject(r, code, message):
        r['_status'], r['_code'], r['_message'] = LweMappingRow.Status.REJECTED, code, message

    signature = lambda r: (key_of(r.get('circle')), key_of(r.get('master_id')), *(tuple(sorted(key_of(t) for t in r['_tokens'][f])) for f in ID_KINDS))  # noqa: E731
    seen, unique_rows = set(), []
    for r in rows:
        if signature(r) in seen:
            r['_status'], r['_code'], r['_message'] = LweMappingRow.Status.DUPLICATE, 'duplicate_row', 'Identical repeat of an earlier row.'
            continue
        seen.add(signature(r))
        unique_rows.append(r)
    masters = Counter(key_of(r['master_id']) for r in unique_rows if r['master_id'])
    id_owners = defaultdict(set)
    for r in unique_rows:
        for f in ID_KINDS:
            for t in r['_tokens'][f]:
                id_owners[(f, key_of(t))].add(key_of(r['master_id']))

    for r in unique_rows:
        master, tokens = key_of(r['master_id']), r['_tokens']
        site = sites.get(master)
        r['_site'] = site
        r['_circle'] = canonical_circle(r.get('circle', ''), Technology.LWE) if r.get('circle') else ''
        if r['_too_long']:
            reject(r, 'value_too_long', f"{', '.join(r['_too_long'])}: longer than the mapping can store; the row is rejected, not truncated.")
        elif not master:
            reject(r, 'missing_master_id', 'No Master ID (btsIpId -Master ID).')
        elif not any(tokens.values()):
            reject(r, 'no_identifier', 'No BTS IP ID, BTS Site ID (2100) or BTS Site ID (700).')
        elif invalid := [f'{HEADERS[f]} "{t}"' for f in ID_KINDS for t in tokens[f] if not is_valid_id(t)]:
            reject(r, 'invalid_identifier', f'{", ".join(invalid)}: not a single identifier (identifiers are separated by "{SEPARATOR}" only).')
        elif site is None:
            reject(r, 'not_lwe_site' if master in other_sites else 'unknown_master_id',
                   f"{r['master_id']} is {'not an LWE site' if master in other_sites else 'not in the site master'}.")
        elif r.get('circle') and r['_circle'] != site.circle:
            reject(r, 'circle_mismatch', f"Circle {r['circle']} differs from the site master circle {site.circle}.")
        elif masters[master] > 1:
            reject(r, 'duplicate_master_id', f"{r['master_id']} is on {masters[master]} rows with different identifiers.")
        elif shared := [t for f in ID_KINDS for t in tokens[f] if len(id_owners[(f, key_of(t))]) > 1]:
            reject(r, 'duplicate_identifier', f"{', '.join(shared)} also map to another Master ID in this file.")
        elif blocked := [t for f in ID_KINDS for t in tokens[f] if index.is_blocked(ID_KINDS[f], t)]:
            reject(r, 'ambiguous_identifier', f"{', '.join(blocked)} {'is' if len(blocked) == 1 else 'are'} claimed by several sites in the Consolidation Matrix and cannot be mapped.")
        elif taken := [f'{t} ({owner.bsnl_site_id})' for f in ID_KINDS for t in tokens[f] if (owner := index.get(ID_KINDS[f], t)) is not None and owner.pk != site.pk]:
            reject(r, 'identifier_assigned_elsewhere', f"{', '.join(taken)}: already the active identifier of another site. Held for review; "
                                                       'the active mapping is not replaced automatically.')
        else:
            r['_status'] = LweMappingRow.Status.ACCEPTED
            desired = {ID_KINDS[f]: {key_of(t) for t in tokens[f]} for f in ID_KINDS if tokens[f]}
            # What the site has now: its mapping identifiers, plus any wanted one another source (the matrix) already gives it.
            own, anywhere = current.get(site.pk, {}), every.get(site.pk, {})
            had = {k: set(own.get(k, ())) | (set(anywhere.get(k, ())) & desired.get(k, set())) for k in MAPPING_KINDS}
            had = {k: v for k, v in had.items() if v}
            r['_desired'] = desired
            r['_change'] = (LweMappingRow.Change.ADDED if not own else
                            LweMappingRow.Change.UNCHANGED if had == desired else LweMappingRow.Change.CHANGED)

    accepted = [r for r in rows if r['_status'] == LweMappingRow.Status.ACCEPTED]
    rejected = [r for r in rows if r['_status'] == LweMappingRow.Status.REJECTED]
    duplicates = [r for r in rows if r['_status'] == LweMappingRow.Status.DUPLICATE]
    in_file = {key_of(r['master_id']) for r in rows if r.get('master_id')}
    site_keys = {s.pk: s.site_key for s in sites.values()}
    kept_rejected = sorted({r['_site'].bsnl_site_id for r in rejected if r['_site'] is not None and r['_site'].pk in current})
    not_in_file = sorted(site_keys[pk] for pk in current if pk in site_keys and site_keys[pk] not in in_file)
    changes = Counter(r['_change'] for r in accepted)
    codes = Counter(r['_code'] for r in rejected)
    quality = {
        'sheet': sheet, 'headers_found': headers, 'headers_missing': [h for f, h in HEADERS.items() if h not in headers],
        'rows': len(rows), 'identical_repeated_rows': len(duplicates),
        'blank_cells': {**{HEADERS[f]: sum(1 for r in rows if not r['_tokens'][f]) for f in ID_KINDS},  # placeholders such as '-' count as blank
                        **{HEADERS[f]: sum(1 for r in rows if not r.get(f)) for f in ('master_id', 'circle')}},
        'placeholder_cells': {HEADERS[f]: sum(1 for r in rows if r.get(f) and not r['_tokens'][f]) for f in ID_KINDS},
        'multi_id_cells': {HEADERS[f]: sum(1 for r in rows if len(r['_tokens'][f]) > 1) for f in ID_KINDS},
        'cells_with_other_separators': {HEADERS[f]: sum(1 for r in rows for t in r['_tokens'][f] if not is_valid_id(t)) for f in ID_KINDS},
        'identifiers_on_several_master_ids': {HEADERS[f]: sum(1 for (k, _), m in id_owners.items() if k == f and len(m) > 1) for f in ID_KINDS},
        'master_ids_on_several_rows': sum(1 for n in masters.values() if n > 1),
        'missing_master_ids': codes.get('missing_master_id', 0), 'circle_mismatches': codes.get('circle_mismatch', 0),
        'master_ids_not_lwe_sites': codes.get('not_lwe_site', 0), 'master_ids_not_in_site_master': codes.get('unknown_master_id', 0),
        'identifiers_ambiguous_in_matrix': codes.get('ambiguous_identifier', 0),
    }
    mapped = {r['_site'].pk for r in accepted} | {pk for pk in current}
    counts = {'received': len(rows), 'accepted': len(accepted), 'rejected': len(rejected), 'duplicate': len(duplicates),
              'unmatched': codes.get('unknown_master_id', 0)}
    report = {
        'sheet': sheet, 'rows': len(rows), 'rejected_by_reason': dict(codes),
        'changes': {'added': changes.get('added', 0), 'changed': changes.get('changed', 0), 'unchanged': changes.get('unchanged', 0),
                    'kept_new_row_rejected': len(kept_rejected), 'not_in_this_workbook_kept': len(not_in_file)},
        'kept_new_row_rejected': kept_rejected[:200], 'not_in_this_workbook_kept': not_in_file[:200],
        'lwe_sites_mapped_after_import': len(mapped), 'lwe_sites_without_mapping': len(set(site_keys) - mapped), 'quality': quality,
        'warnings': [w for w in (
            f'{len(rejected)} row(s) rejected.' if rejected else '',
            f'{len(kept_rejected)} site(s) keep their earlier mapping because their new row is rejected (review).' if kept_rejected else '',
            f'{len(not_in_file)} mapped site(s) are not in this workbook; their mapping is kept (review).' if not_in_file else '',
        ) if w],
    }
    items = [exceptions.record(source_file=path.name, code=r['_code'], row=r['row'], site_id=r.get('master_id', ''), circle=r.get('circle', ''),
                               identifier=', '.join(t for f in ID_KINDS for t in r['_tokens'][f]), message=r['_message'],
                               severity=exceptions.REJECTED if r in rejected else 'duplicate')
             for r in rejected + duplicates]
    items += [exceptions.record(source_file=path.name, code='mapping_kept_new_row_rejected', severity=exceptions.REVIEW, site_id=s,
                                message='The new row of this site is rejected; its earlier active mapping is kept until reviewed.') for s in kept_rejected]
    items += [exceptions.record(source_file=path.name, code='mapping_not_in_workbook', severity=exceptions.REVIEW, site_id=s,
                                message='Mapped by an earlier import but not in this workbook; its active mapping is kept (not removed automatically).')
              for s in not_in_file]
    return {'rows': rows, 'counts': counts, 'report': report, 'exceptions': items}


def preview(path: Path, name: str, *, user=None) -> UploadBatch:
    batch = uploads.new_batch(KIND, path, name, user, technology=Technology.LWE)
    try:
        result = analyse(Path(batch.stored_path))
    except uploads.UploadRejected as exc:
        batch.error = str(exc)
        return uploads.record_preview(batch, {}, {'error': str(exc)}, failed=True)
    for item in result['exceptions']:
        item['source_file'] = name
    return uploads.record_preview(batch, result['counts'], result['report'], exception_items=result['exceptions'])


def commit(batch: UploadBatch, *, user=None, request=None) -> UploadBatch:
    uploads.require_previewed(batch)
    result = analyse(uploads.staged_file(batch))
    if not uploads.same_counts(batch, result['counts']):
        raise uploads.UploadRejected('The database changed since the preview; preview the file again before committing.')
    rows = result['rows']
    with transaction.atomic():
        # 1. History: every row of the workbook, as written, with its outcome and its normalised identifiers.
        records = LweMappingRow.objects.bulk_create([LweMappingRow(
            batch=batch, source_row=r['row'], circle_raw=r['_circle_stored'], bts_ip_id_raw=r['_bts_ip_id_stored'],
            band_2100_raw=r['_band_2100_stored'], band_700_raw=r['_band_700_stored'], master_id_raw=r['_master_id_stored'],
            master_key=key_of(r.get('master_id'))[:80], circle=r['_circle'], site=r['_site'], status=r['_status'], change=r['_change'],
            reject_code=r['_code'], reject_message=r['_message']) for r in rows], batch_size=2000)
        by_row = {rec.source_row: rec for rec in records}
        LweMappingIdentifier.objects.bulk_create([
            LweMappingIdentifier(row=by_row[r['row']], kind=ID_KINDS[f], value=t, key=key_of(t))
            for r in rows for f in ID_KINDS for t in r['_tokens'][f] if is_valid_id(t) and len(t) <= 80], batch_size=5000, ignore_conflicts=True)
        # 2. Active mapping: added / changed rows replace the site's earlier mapping identifiers of each kind they give.
        new_ids = []
        for r in rows:
            if r['_status'] != LweMappingRow.Status.ACCEPTED:
                continue
            site, rec = r['_site'], by_row[r['row']]
            for kind, keys in r['_desired'].items():
                SiteIdentifier.objects.filter(site=site, kind=kind, batch__kind=KIND).exclude(key__in=keys).delete()
                existing = set(SiteIdentifier.objects.filter(site=site, kind=kind, key__in=keys).values_list('key', flat=True))
                SiteIdentifier.objects.filter(site=site, kind=kind, key__in=existing, batch__kind=KIND).update(mapping_row=rec)
                values = {key_of(t): t for f, k in ID_KINDS.items() if k == kind for t in r['_tokens'][f]}
                new_ids += [SiteIdentifier(site=site, kind=kind, key=key, value=values[key][:80], batch=batch, source_row=r['row'], mapping_row=rec)
                            for key in sorted(keys - existing)]
        SiteIdentifier.objects.bulk_create(new_ids, batch_size=2000)
        uploads.mark_committed(batch, {'identifiers_created': len(new_ids)})
    audit('sitedata.band_mapping_committed', request, batch=batch.pk, file=batch.original_filename, identifiers=len(new_ids), **result['report']['changes'])
    return batch
