"""RCA reporting periods: expected coverage, received versus pending data, and the consolidated RCA Master reports.

A period is a reporting date or a date range; periods never overlap. The NOC Lead uploads the consolidated RCA
workbook for a period; the first accepted upload creates the period if an Admin has not started it already.

Expected scope is generated, never configured: every active project / circle association of the Organization
(an active project, an active circle and an active association), so a new project or circle is tracked as soon as
it is associated and a deactivated one stops being expected. A finalized period keeps the scope its first final
report was built on (stored with it), so a later Organization change never rewrites a finalized report. A unit counts
as received when accepted RCA records of that project and circle exist in the period. A successful upload alone proves
nothing about a circle that has no rows in it. With no active association at all the period reports "expected scope
not configured" and its report stays partial.

Two facts per expected unit, never derived from each other:
- RCA data availability ("received" / "pending"): accepted records of the project and circle exist in the period,
  whichever upload (circle, consolidated, legacy) or manual entry wrote them. Period completeness and the final report
  rest on this.
- Circle submission ("received" / "not_received"): a committed *circle* upload of that project, circle and reporting
  date, with its upload and commit times. Previews, failed or rejected uploads, consolidated and legacy uploads never
  count. No deadline is configured, so nothing is called on time or late.

Upload status (validated, imported, failed...) is kept apart from period completeness. The period's status is
derived each time:
- "final": the latest final report was built from exactly the records stored now (same fingerprint);
- "revised": a final report exists but the stored records changed afterwards (an accepted correction);
- otherwise "unconfigured", "ready" (every expected unit has data), "review" (an upload awaits confirmation),
  "partial" (some expected units have data) or "awaiting".

Reports are always built from the canonical records in the database (never by adding upload totals). A final
report is stored per version; generating again from unchanged records returns the existing version.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import date
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from . import report as workbook
from . import services
from .importer import SOURCE_FIELDS
from .models import RcaImportBatch, RcaRecord, RcaReport, RcaReportingCycle, RcaRequiredSubmission

logger = logging.getLogger(__name__)
STATUS_LABELS = {
    'unconfigured': 'Expected scope not configured', 'awaiting': 'Awaiting data', 'review': 'Upload awaiting confirmation',
    'partial': 'Partially received', 'ready': 'Ready for final report', 'final': 'Final report generated',
    'revised': 'Revised after finalization',
}
UNIT_LABELS = {'received': 'Data received', 'pending': 'Pending — no accepted records'}  # as printed in the final workbook
DATA_LABELS = {'received': 'Data available', 'pending': 'No data'}
SUBMISSION_LABELS = {'received': 'Received', 'not_received': 'Not received'}


class CycleError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def period_label(start: date, end: date) -> str:
    return f'{start:%d %b %Y}' if start == end else f'{start:%d %b %Y} – {end:%d %b %Y}'


# --- Periods -------------------------------------------------------------------------------------

def period_cycle(start: date, end: date, *, create: bool = False, name: str = '', user=None, lock: bool = False) -> RcaReportingCycle | None:
    """The period with exactly these dates (created on request). Refused if it overlaps another period."""
    if end < start:
        raise CycleError('The reporting period ends before it starts.')
    qs = RcaReportingCycle.objects.select_for_update() if lock else RcaReportingCycle.objects.all()
    overlapping = [c for c in qs.filter(reporting_date__lte=end) if c.end >= start]
    exact = next((c for c in overlapping if c.reporting_date == start and c.end == end), None)
    if exact is None and overlapping:
        other = overlapping[0]
        raise CycleError(f'The period overlaps the existing reporting period {period_label(other.reporting_date, other.end)}'
                         f'{f" ({other.name})" if other.name else ""}. Use that period or dates that do not overlap it.', 409)
    if exact is not None or not create:
        return exact
    return RcaReportingCycle.objects.create(reporting_date=start, period_end=end if end != start else None, name=name, created_by=user)


def containing_cycle(day: date) -> RcaReportingCycle | None:
    """The existing period containing ``day`` (read only, no lock, nothing created)."""
    return next((c for c in RcaReportingCycle.objects.filter(reporting_date__lte=day) if c.end >= day), None)


def cycle_for_date(day: date, *, user=None, name: str = '') -> RcaReportingCycle:
    """The period containing ``day``, or a new single-date (daily) period for it, named ``name``."""
    containing = next((c for c in RcaReportingCycle.objects.select_for_update().filter(reporting_date__lte=day) if c.end >= day), None)
    return containing or period_cycle(day, day, create=True, name=name, user=user, lock=True)


def expected_units(cycle: RcaReportingCycle | None = None) -> list[tuple[str, str]]:
    """The (project, circle) units a period is expected to cover.

    A finalized period: the scope stored when its first final report was generated (or, for a report generated before
    the scope was stored with it, the units that report lists). Any other period, or no period yet: every active
    project / circle association of the Organization, in the Organization's order (project, then circle).
    """
    if cycle is not None and cycle.pk and cycle.reports.exists():
        frozen = list(cycle.required.values_list('project', 'circle'))
        if frozen:
            return frozen
        first = cycle.reports.order_by('version').first()
        return [(u['project'], u['circle']) for u in first.submissions or []]
    from apps.organization.services import associations
    return associations(active_only=True)


def _freeze_scope(cycle: RcaReportingCycle, units: list[dict]) -> None:
    """Stores the scope of the first final report with the period (it never changes afterwards)."""
    cycle.required.all().delete()  # rows of a former manual configuration, never used for an open period
    RcaRequiredSubmission.objects.bulk_create([RcaRequiredSubmission(cycle=cycle, project=u['project'], circle=u['circle']) for u in units])


# --- Records, coverage and status ----------------------------------------------------------------

def records(cycle: RcaReportingCycle):
    """The canonical accepted records of the period: every stored (not withdrawn) RCA record with a date in it."""
    # The batch's parsed rows and validation report (large JSON, up to the whole workbook) are never read from a record:
    # loading them once per record made a daily period take close to a minute.
    return services.with_category(RcaRecord.objects.filter(reporting_date__range=(cycle.reporting_date, cycle.end))) \
        .select_related('batch').defer(*BATCH_PAYLOAD) \
        .order_by('reporting_date', 'project', 'circle', 'site_key', 'id')


# Large JSON columns of an upload, needed only to preview or commit it.
BATCH_PAYLOAD = ('batch__rows', 'batch__report')
_FINGERPRINT_FIELDS = ('pk', 'source', 'reporting_date', 'project', 'site_key', *SOURCE_FIELDS)


def _digest(rows) -> str:
    return hashlib.sha256(json.dumps(sorted(rows, key=lambda x: x[0]), default=str).encode()).hexdigest()


def fingerprint(recs) -> str:
    """Changes whenever a record is added, withdrawn or has a source value changed."""
    return _digest([[r.pk, r.source, r.reporting_date.isoformat(), r.project, r.site_key, *[getattr(r, f) for f in SOURCE_FIELDS]] for r in recs])


def stored_fingerprint(cycle: RcaReportingCycle) -> tuple[str, int]:
    """(fingerprint, record count) of the period's accepted records, read as plain values: the same digest as
    ``fingerprint(records(cycle))`` without building a model instance per record."""
    rows = [[r[0], r[1], r[2].isoformat(), *r[3:]] for r in RcaRecord.objects.filter(
        reporting_date__range=(cycle.reporting_date, cycle.end)).order_by().values_list(*_FINGERPRINT_FIELDS)]
    return _digest(rows), len(rows)


def uploads(cycle: RcaReportingCycle):
    """Every upload for the period: accepted ones, and those still awaiting confirmation, rejected or failed."""
    ids = RcaImportBatch.objects.filter(
        Q(cycle=cycle) | Q(period_start=cycle.reporting_date, period_end=cycle.end)
        # a cumulative workbook of a later date that added or corrected records of this period (withdrawn ones included)
        | Q(pk__in=RcaRecord.all_objects.filter(reporting_date__range=(cycle.reporting_date, cycle.end)).order_by().values('batch_id'))
    ).values('pk')
    # The parsed rows held between preview and commit are not needed to describe an upload.
    return RcaImportBatch.objects.select_related('imported_by').defer('rows').filter(pk__in=ids).order_by('-uploaded_at', '-id')


def batch_json(batch: RcaImportBatch, *, full: bool = False) -> dict:
    c, r = dict(batch.counts or {}), batch.report or {}
    rejected = c.get('rejected', r.get('rejected_rows')) or 0
    if batch.status == RcaImportBatch.Status.COMMITTED:  # imports made before these counts existed: derived from their own counts
        c.setdefault('updated', c.get('overwritten', 0))
        c.setdefault('skipped', c.get('unchanged', 0) + c.get('skipped_conflicts', 0))
        c.setdefault('total', r.get('rows_read', c.get('inserted', 0) + c['skipped'] + c['updated'] + rejected))
    status = batch.status
    if status == RcaImportBatch.Status.COMMITTED:
        label = 'Imported with rejected rows' if rejected else 'Imported'
    elif status == RcaImportBatch.Status.PREVIEWED:
        label = 'Validated — awaiting confirmation'
    else:
        label = batch.get_status_display()
    data = {
        'id': batch.pk, 'status': status, 'status_label': label, 'file': batch.original_filename, 'checksum': batch.checksum_sha256,
        'upload_type': batch.upload_type, 'upload_type_label': batch.get_upload_type_display(), 'circle': batch.circle or None,
        'sheet': batch.sheet_name, 'uploaded_at': batch.uploaded_at.isoformat(),
        'committed_at': batch.committed_at.isoformat() if batch.committed_at else None,
        'imported_by': batch.imported_by.get_username() if batch.imported_by else None,
        'report_name': batch.report_name or None, 'project_scope': batch.project_scope or None, 'remarks': batch.remarks or None,
        'period_start': batch.period_start.isoformat() if batch.period_start else None,
        'period_end': batch.period_end.isoformat() if batch.period_end else None,
        'cycle': batch.cycle_id, 'units': batch.units, 'counts': c, 'correction': bool(c.get('correction') or r.get('is_correction')),
        'conflict_action': batch.conflict_action or None, 'missing_action': batch.missing_action or None,
        'error': batch.error or None, 'file_kept': bool(batch.stored_path),
    }
    if full:
        data['report'] = {k: v for k, v in r.items() if k != 'all_issues'}
    return data


def _covers(batch: RcaImportBatch, project: str, circle: str) -> bool:
    """The upload is for this unit: a circle upload of it, or a workbook with valid rows of it."""
    if batch.upload_type == RcaImportBatch.UploadType.CIRCLE and (batch.project_scope, batch.circle) == (project, circle):
        return True
    return [project, circle] in (batch.units or [])


def unit_states(cycle: RcaReportingCycle, batches: list[RcaImportBatch] | None = None) -> list[dict]:
    """Each expected unit with the evidence: accepted records of that project and circle in the period, their files, and
    the period's uploads for the unit (``upload_ids``, latest first; the uploads themselves are listed once per period)."""
    batches = list(uploads(cycle)) if batches is None else batches
    recs = RcaRecord.objects.filter(reporting_date__range=(cycle.reporting_date, cycle.end)).order_by()
    stored = {(r['project'], r['circle']): r for r in recs.values('project', 'circle').annotate(records=Count('id'), minutes=Sum('outage_minutes'))}
    sources: dict[tuple, set] = {}
    for p, c, f in recs.values_list('project', 'circle', 'source_file').distinct():
        sources.setdefault((p, c), set()).add(f or 'Recorded in the portal')
    submitted = circle_submissions(cycle)
    states = []
    for project, circle in expected_units(cycle):
        row = stored.get((project, circle), {})
        status = 'received' if row.get('records') else 'pending'
        files = submitted.get((project, circle), [])
        submission = 'received' if files else 'not_received'
        latest = files[0] if files else None
        states.append({'project': project, 'circle': circle, 'status': status, 'status_label': UNIT_LABELS[status],
                       'data_label': DATA_LABELS[status],
                       'records': row.get('records', 0), 'outage_minutes': services._round(row.get('minutes')),
                       'source_files': sorted(sources.get((project, circle), ())),
                       'submission_status': submission, 'submission_label': SUBMISSION_LABELS[submission],
                       'submission': latest, 'submissions': len(files),
                       'upload_ids': [b.pk for b in batches if _covers(b, project, circle)]})
    return states


def circle_submissions(cycle: RcaReportingCycle) -> dict[tuple[str, str], list[dict]]:
    """Committed circle uploads per (project, circle) with a reporting date in the period, latest first."""
    out: dict[tuple[str, str], list[dict]] = {}
    batches = (RcaImportBatch.objects.filter(upload_type=RcaImportBatch.UploadType.CIRCLE, status=RcaImportBatch.Status.COMMITTED,
                                             period_start__range=(cycle.reporting_date, cycle.end))
               .select_related('imported_by').order_by('-committed_at', '-id'))
    for b in batches:
        out.setdefault((b.project_scope, b.circle), []).append({
            'batch': b.pk, 'file': b.original_filename, 'reporting_date': b.period_start.isoformat(),
            'uploaded_at': b.uploaded_at.isoformat(), 'committed_at': b.committed_at.isoformat() if b.committed_at else None,
            'uploaded_by': b.imported_by.get_username() if b.imported_by else None})
    return out


def status(cycle: RcaReportingCycle, *, units: list[dict] | None = None, current: str | None = None) -> dict:
    units = unit_states(cycle) if units is None else units
    current = stored_fingerprint(cycle)[0] if current is None else current
    latest = cycle.reports.first()
    required, received = len(units), sum(1 for u in units if u['status'] == 'received')
    submitted = sum(1 for u in units if u.get('submission_status') == 'received')
    complete = bool(required) and received == required
    # The same uploads the period lists and counts as awaiting confirmation (uploads_summary): a preview linked to the
    # period, or of exactly its dates. Matching the dates alone missed a day's preview inside a multi-day period.
    waiting = uploads(cycle).filter(status=RcaImportBatch.Status.PREVIEWED).exists()
    if latest is not None:
        code = 'final' if latest.records_checksum == current else 'revised'
    elif not required:
        code = 'unconfigured'
    elif complete:
        code = 'ready'
    elif waiting:
        code = 'review'
    elif received:
        code = 'partial'
    else:
        code = 'awaiting'
    return {
        'code': code, 'label': STATUS_LABELS[code], 'required': required, 'received': received, 'complete': complete,
        # Circle files received (separate from data availability; never needed for the final report).
        'circle_submissions': submitted,
        'outstanding': [{'project': u['project'], 'circle': u['circle'], 'status': u['status'], 'status_label': u['status_label']}
                        for u in units if u['status'] != 'received'],
        'final_version': latest.version if latest else None, 'upload_awaiting_confirmation': waiting,
        'can_finalize': complete and code in ('ready', 'revised'),
        'records_checksum': current,
    }


def cycle_json(cycle: RcaReportingCycle, *, full: bool = False, site_scope: str = 'all') -> dict:
    batches = list(uploads(cycle))  # read once: per-unit uploads, the upload summary and the period's upload list
    units = unit_states(cycle, batches)
    current, count = stored_fingerprint(cycle)
    data = {
        'id': cycle.pk, 'name': cycle.name or None, 'period_start': cycle.reporting_date.isoformat(), 'period_end': cycle.end.isoformat(),
        'period_label': period_label(cycle.reporting_date, cycle.end), 'notes': cycle.notes or None,
        'created_by': cycle.created_by.get_username() if cycle.created_by else None, 'created_at': cycle.created_at.isoformat(),
        'status': status(cycle, units=units, current=current), 'records': count,
        'uploads_summary': _uploads_summary(batches),
    }
    if full:
        expected = {(u['project'], u['circle']) for u in units}
        represented = {(r['project'], r['circle']): r['n'] for r in RcaRecord.objects.filter(
            reporting_date__range=(cycle.reporting_date, cycle.end)).order_by().values('project', 'circle').annotate(n=Count('id'))}
        from . import sitescope
        if site_scope != sitescope.ALL:
            # Site Scope: each unit's records and outage minutes of those sites only. The unit's status (data received
            # or pending) still counts every record: the submission rules do not change with the view.
            recs_qs = RcaRecord.objects.filter(reporting_date__range=(cycle.reporting_date, cycle.end)).order_by()
            scoped = {(r['project'], r['circle']): r for r in sitescope.apply(recs_qs, site_scope).values('project', 'circle')
                      .annotate(records=Count('id'), minutes=Sum('outage_minutes'))}
            for u in units:
                row = scoped.get((u['project'], u['circle']), {})
                u['records_in_scope'], u['outage_minutes_in_scope'] = row.get('records', 0), services._round(row.get('minutes'))
        data.update({
            'site_scope': {'scope': site_scope, 'label': sitescope.SCOPES[site_scope]} if full else None,
            'units': units,
            # Data present for projects / circles the period is not expected to cover (shown, never counted as coverage).
            'unexpected': [{'project': p, 'circle': c, 'records': n} for (p, c), n in sorted(represented.items()) if (p, c) not in expected],
            'uploads': [batch_json(b) for b in batches],
            'reports': [report_json(r) for r in cycle.reports.select_related('generated_by')],
            # The scope is fixed once a final report exists; until then it follows the Organization.
            'locked': cycle.reports.exists(),
        })
    return data


def _uploads_summary(period_uploads: list[RcaImportBatch]) -> dict:
    """Upload outcomes for the period (kept apart from completeness): imported, awaiting confirmation, failed, corrections."""
    batches = [b for b in period_uploads if b.status != RcaImportBatch.Status.DISCARDED]  # discarded before import: not counted
    return {
        'total': len(batches),
        'imported': sum(1 for b in batches if b.status == RcaImportBatch.Status.COMMITTED),
        'with_rejected_rows': sum(1 for b in batches if b.status == RcaImportBatch.Status.COMMITTED and (b.counts or {}).get('rejected')),
        'awaiting_confirmation': sum(1 for b in batches if b.status == RcaImportBatch.Status.PREVIEWED),
        'validation_failed': sum(1 for b in batches if b.status in (RcaImportBatch.Status.FAILED, RcaImportBatch.Status.REJECTED)),
        'corrections': sum(1 for b in batches if (b.counts or {}).get('correction')),
        'last_upload_at': batches[0].uploaded_at.isoformat() if batches else None,
    }


def report_json(rep: RcaReport) -> dict:
    return {
        'id': rep.pk, 'version': rep.version, 'filename': rep.filename, 'generated_at': rep.generated_at.isoformat(),
        'generated_by': rep.generated_by.get_username() if rep.generated_by else None, 'automatic': rep.automatic,
        'record_count': rep.record_count, 'superseded_at': rep.superseded_at.isoformat() if rep.superseded_at else None,
        'current': rep.superseded_at is None, 'available': Path(rep.stored_path).is_file(),
    }


# --- Reports -------------------------------------------------------------------------------------

def _summary(cycle: RcaReportingCycle) -> dict:
    return services.summary({'date_from': cycle.reporting_date.isoformat(), 'date_to': cycle.end.isoformat()})


def _file_stem(cycle: RcaReportingCycle) -> str:
    start, end = cycle.reporting_date.isoformat(), cycle.end.isoformat()
    return f'RCA_Master_{start}' if start == end else f'RCA_Master_{start}_to_{end}'


def partial_workbook(cycle: RcaReportingCycle, user=None) -> tuple[bytes, str]:
    """The consolidated workbook of the records stored now, labelled with the period's status (not stored, no version)."""
    units = unit_states(cycle)
    recs = list(records(cycle))
    state = status(cycle, units=units, current=fingerprint(recs))
    if state['code'] == 'revised':
        label = f'DRAFT — REVISED AFTER FINAL v{state["final_version"]}; NOT YET FINALIZED'
    elif state['code'] == 'unconfigured':
        label = 'PARTIAL — EXPECTED SCOPE NOT CONFIGURED'
    elif state['complete']:
        label = 'DRAFT — ALL EXPECTED DATA ACCEPTED; FINAL NOT YET GENERATED'
    else:
        label = 'PARTIAL — AWAITING DATA'
    content = workbook.build(cycle=cycle, records=recs, summary=_summary(cycle), units=units, uploads=list(uploads(cycle)), state=state,
                             label=label, version=None, generated_at=timezone.now(), generated_by=user)
    stamp = timezone.localtime().strftime('%Y%m%d-%H%M')
    return content, f'{_file_stem(cycle)}_{"DRAFT" if state["complete"] else "PARTIAL"}_{stamp}.xlsx'


def generate_final(cycle: RcaReportingCycle, *, user=None, automatic: bool = False) -> tuple[RcaReport, bool]:
    """Build and store the final report from one snapshot of the accepted records. (report, created).

    Refused while expected data is missing or no scope is configured. If the latest final report already reflects
    the stored records, it is returned unchanged (no new version).
    """
    with transaction.atomic():
        cycle = RcaReportingCycle.objects.select_for_update().get(pk=cycle.pk)  # imports into this period wait meanwhile
        units = unit_states(cycle)
        recs = list(records(cycle))
        current = fingerprint(recs)
        state = status(cycle, units=units, current=current)
        if not state['complete']:
            if not state['required']:
                raise CycleError('No active project and circle is associated in the Organization, so nothing is expected yet.', 409)
            names = ', '.join(f'{u["project"]} / {u["circle"]}' for u in state['outstanding'])
            raise CycleError(f'The final report needs accepted data for every expected project and circle. Pending: {names}.', 409)
        latest = cycle.reports.select_for_update().first()
        if latest is not None and latest.records_checksum == current:
            return latest, False
        summary = _summary(cycle)
        if summary['kpis']['records'] != len(recs):  # same transaction and lock: a mismatch means a defect, never ship it
            raise CycleError('The RCA Summary and the record list disagree; the report was not generated.', 500)
        version = latest.version + 1 if latest else 1
        now = timezone.now()
        label = f'FINAL — VERSION {version}' + (f' (REVISED; SUPERSEDES v{latest.version})' if latest else '')
        content = workbook.build(cycle=cycle, records=recs, summary=summary, units=units, uploads=list(uploads(cycle)), state=state,
                                 label=label, version=version, generated_at=now, generated_by=user)
        folder = Path(settings.DATA_DIR) / 'processed' / 'rca_reports' / _file_stem(cycle).removeprefix('RCA_Master_')
        folder.mkdir(parents=True, exist_ok=True)
        filename = f'{_file_stem(cycle)}_FINAL_v{version}.xlsx'
        path = folder / filename
        path.write_bytes(content)
        if latest is not None:
            latest.superseded_at = now
            latest.save(update_fields=['superseded_at'])
        else:
            _freeze_scope(cycle, units)
        report = RcaReport.objects.create(
            cycle=cycle, version=version, generated_by=user, automatic=automatic, filename=filename, stored_path=str(path),
            checksum_sha256=hashlib.sha256(content).hexdigest(), records_checksum=current, record_count=len(recs),
            summary=summary, submissions=units,
        )
    return report, True


def after_commit(cycle: RcaReportingCycle, *, user=None) -> RcaReport | None:
    """Called after an upload is committed: the first final report is generated as soon as every expected unit has data.

    A correction after finalization only marks the period as revised; an Admin generates the revised version.
    """
    if cycle.reports.exists() or not status(cycle)['complete']:
        return None
    try:
        return generate_final(cycle, user=user, automatic=True)[0]
    except Exception:  # the import is committed either way; an Admin can generate the report from the submissions page
        logger.exception('RCA period %s: automatic final report failed', cycle.pk)
        return None
