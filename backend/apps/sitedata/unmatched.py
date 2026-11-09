"""Up-Time Report sites that are not in the Consolidation Matrix site master: kept, reported and resolved safely.

The Consolidation Matrix owns the site master; Up-Time Reports own daily performance. A row whose site ID matches no
master site is never turned into a site and never guessed: its daily values stay pending in the upload's staged copy
(kept for every upload, checksum-verified), and the upload's report lists the site with its dates and site-days. They
are not in the daily table, so no KPI counts them.

Resolution by an Admin, one of:
- add the site to the Consolidation Matrix and import the updated matrix (the matrix stays the only source of site
  attributes); or
- map an approved alternate identifier to an existing master site (``map_alternate``): refused when the identifier is
  already a master site ID, an identifier of any site (of any kind), or blocked by an identifier conflict, so one ID
  can never name two sites. The Up-Time Report importer matches a row by BSNL Site ID first, then by an approved
  alternate identifier; the existing technology check keeps 4G and LWE apart.

Then ``process_pending`` re-reads the staged file of each committed upload with pending sites that now resolve and
imports their values under that original upload: daily.py's rules apply (one record per site, date and technology;
source precedence; authorized corrections kept; differing values logged), in one transaction, recorded on the upload
and audited. A site already processed for an upload is not processed again.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from django.db import transaction
from django.utils import timezone

from apps.accounts.audit import audit

from . import daily, uploads
from .identifiers import key_of
from .models import IdentifierConflict, Site, SiteIdentifier, UploadBatch

ALTERNATE = SiteIdentifier.Kind.ALTERNATE_SITE_ID
REASON = 'Not in the Consolidation Matrix site master'


class ResolutionRejected(Exception):
    """A mapping or processing request that would break a rule (e.g. one identifier for two sites)."""


def site_lookup() -> dict[str, Site]:
    """Site by key: master BSNL Site IDs, then approved alternate identifiers (never the other way round)."""
    sites = {s.site_key: s for s in Site.objects.all()}
    by_alternate = {i.key: i.site for i in SiteIdentifier.objects.filter(kind=ALTERNATE).select_related('site')}
    return {**by_alternate, **sites}


def map_alternate(value: str, site: Site, *, user, reason: str, request=None) -> SiteIdentifier:
    """Approve ``value`` as an alternate identifier of an existing master site (Admin only, with a reason)."""
    from apps.accounts.roles import ADMIN, role_of
    if role_of(user) != ADMIN:
        raise ResolutionRejected('Only an Admin can map an identifier to a master site.')
    if not (reason or '').strip():
        raise ResolutionRejected('A mapping needs a reason (the evidence for it).')
    key = key_of(value)
    if not key:
        raise ResolutionRejected('Enter the identifier as written in the Up-Time Report.')
    if site.reporting_scope != Site.Scope.DASHBOARD:
        raise ResolutionRejected(f'{site.bsnl_site_id} is outside the dashboard reporting scope.')
    if Site.objects.filter(site_key=key).exists():
        raise ResolutionRejected(f'{value} is itself a master site ID; it cannot also name another site.')
    taken = SiteIdentifier.objects.filter(key=key).select_related('site').first()
    if taken is not None:
        raise ResolutionRejected(f'{value} is already an identifier of {taken.site.bsnl_site_id} ({taken.get_kind_display()}).')
    if IdentifierConflict.objects.filter(key=key, active=True).exists():
        raise ResolutionRejected(f'{value} is blocked: it is claimed by more than one site (identifier conflict).')
    with transaction.atomic():
        batch = UploadBatch.objects.create(
            kind=UploadBatch.Kind.CORRECTION, original_filename=f'Alternate identifier {value} -> {site.bsnl_site_id}',
            uploaded_by=user, circle=site.circle, technology=site.technology, records_received=1, records_accepted=1,
            validation_status=UploadBatch.Validation.PASSED, processing_status=UploadBatch.Processing.COMMITTED,
            remarks=reason.strip(), report={'alternate_identifier': value, 'site': site.pk, 'site_id': site.bsnl_site_id})
        batch.committed_at = batch.uploaded_at
        batch.save(update_fields=['committed_at'])
        identifier = SiteIdentifier.objects.create(site=site, kind=ALTERNATE, value=value.strip(), key=key, batch=batch)
    audit('sitedata.alternate_identifier_mapped', request, identifier=value, site=site.bsnl_site_id, batch=batch.pk)
    return identifier


def _uploads():
    return UploadBatch.objects.filter(kind=UploadBatch.Kind.UPTIME_MASTER, processing_status=UploadBatch.Processing.COMMITTED).order_by('committed_at', 'id')


def refresh_details(*, user=None, request=None) -> int:
    """Record the per-site detail (dates, site-days) of unmatched sites on committed uploads made before the detail
    was stored with every preview. Re-reads the staged copies; changes only the uploads' reports. Returns the number
    of uploads updated."""
    from . import uptime_master
    updated = 0
    for batch in _uploads():
        report = batch.report or {}
        if batch.records_unmatched and 'unmatched_sites' not in report:
            result = uptime_master.analyse(uploads.staged_file(batch), batch.original_filename, batch.technology or None)
            batch.report = {**report, 'unmatched_sites': result['report']['unmatched_sites']}
            batch.save(update_fields=['report'])
            updated += 1
    if updated:
        audit('sitedata.unmatched_details_refreshed', request, uploads=updated)
    return updated


def report() -> dict:
    """Data-quality report: every site of a committed Up-Time Report that is not (or was not) in the site master."""
    lookup = site_lookup()
    rows: dict[str, dict] = {}
    missing_detail = []
    for batch in _uploads():
        rep = batch.report or {}
        processed = set(rep.get('pending_processed_sites', []))
        details = rep.get('unmatched_sites')
        if details is None:
            if batch.records_unmatched:
                missing_detail.append(batch.pk)
                details = [{'site_id': s} for s in rep.get('sites_not_in_site_master', [])]
            else:
                details = []
        for d in details:
            key = key_of(d['site_id'])
            entry = rows.setdefault(key, {'site_id': d['site_id'], 'project': d.get('project'), 'circle': d.get('circle'), 'uploads': [],
                                          'first_date': None, 'last_date': None, 'pending_site_days': 0, 'processed_site_days': 0,
                                          'reason': REASON})
            entry['uploads'].append(batch.pk)
            for f in ('project', 'circle'):
                entry[f] = entry[f] or d.get(f)
            if d.get('first_date'):
                entry['first_date'] = min(filter(None, (entry['first_date'], d['first_date'])))
                entry['last_date'] = max(filter(None, (entry['last_date'], d['last_date'])))
            days = d.get('site_days')
            if key in processed:
                entry['processed_site_days'] += days or 0
            elif days is not None:
                entry['pending_site_days'] += days
            elif entry['pending_site_days'] is not None:
                entry['pending_site_days'] = None  # not known until the details are refreshed
    out = []
    for key, entry in sorted(rows.items()):
        site = lookup.get(key)
        entry['resolved_to'] = site.bsnl_site_id if site is not None else None
        entry['resolved_by'] = None if site is None else 'master' if site.site_key == key else 'alternate_identifier'
        entry['status'] = ('pending' if site is None else
                           'processed' if entry['pending_site_days'] == 0 and entry['processed_site_days'] else 'ready')
        out.append(entry)
    return {'sites': out, 'uploads_without_detail': missing_detail,
            'pending_sites': sum(1 for e in out if e['status'] == 'pending'), 'ready_sites': sum(1 for e in out if e['status'] == 'ready')}


def process_pending(*, user, request=None) -> dict:
    """Import the pending values of sites that now resolve, under their original uploads (see the module notes)."""
    from apps.accounts.roles import ADMIN, role_of

    from . import uptime_master
    if role_of(user) != ADMIN:
        raise ResolutionRejected('Only an Admin can process pending records.')
    lookup = site_lookup()
    totals = defaultdict(int)
    processed_uploads = []
    for batch in _uploads():
        rep = batch.report or {}
        unmatched = {key_of(s) for s in rep.get('sites_not_in_site_master', [])} | {key_of(d['site_id']) for d in rep.get('unmatched_sites', [])}
        done = set(rep.get('pending_processed_sites', []))
        ready = {k for k in unmatched - done if k in lookup}
        if not ready:
            continue
        result = uptime_master.analyse(uploads.staged_file(batch), batch.original_filename, batch.technology or None)
        values = [v for v in result['values'] if key_of(v.source_identifier) in ready]
        rejected = [r for r in result['report']['rejected_rows'] if key_of(r['site_id']) in ready]
        classified = daily.classify(values, uptime_master.KIND)
        counts = classified.counts()
        with transaction.atomic():
            locked = UploadBatch.objects.select_for_update().get(pk=batch.pk)
            daily.write(locked, classified)
            history = (locked.report or {}).get('pending_processed', [])
            locked.report = {**(locked.report or {}),
                             'pending_processed_sites': sorted(done | ready),
                             'pending_processed': [*history, {'at': timezone.now().isoformat(), 'by': user.get_username(), 'sites': sorted(ready),
                                                             'counts': counts, 'rejected_rows': rejected}]}
            locked.save(update_fields=['report'])
        for k, v in counts.items():
            totals[k] += v
        processed_uploads.append({'upload': batch.pk, 'sites': sorted(ready), 'counts': counts, 'rejected_rows': len(rejected)})
    if processed_uploads:
        from . import portfolio
        portfolio.clear_cache()
        audit('sitedata.pending_processed', request, uploads=[u['upload'] for u in processed_uploads], **dict(totals))
    return {'uploads': processed_uploads, 'counts': dict(totals)}


def staged_exists(batch: UploadBatch) -> bool:
    return bool(batch.stored_path) and Path(batch.stored_path).is_file()
