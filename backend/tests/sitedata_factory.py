"""Small builders for data-layer records in tests (test database only): sites of the site master and daily records.

    from tests.sitedata_factory import make_site, make_daily
    site = make_site('UVMP001', technology='4G Saturation', circle='MP', on_air_date=date(2026, 1, 1), om_start_date=date(2026, 2, 1))
    make_daily(site, date(2026, 10, 1), outage=0)

Records are created directly (no file import), with an upload batch of the right kind so provenance and source
precedence stay valid. Call apps.sitedata.portfolio.clear_cache() after adding records when a test reads the dashboard
dataset.
"""
from __future__ import annotations

from datetime import date

from django.utils import timezone

from apps.sitedata.models import DailySitePerformance, ReportingUnit, Site, SiteIdentifier, Technology, UploadBatch
from apps.sitedata.rules import availability_from_outage



def batch(kind: str = UploadBatch.Kind.CONSOLIDATION_MATRIX, name: str | None = None) -> UploadBatch:
    """A committed upload of ``kind`` (one per kind and test, reused)."""
    existing = UploadBatch.objects.filter(kind=kind, original_filename=name or f'test-{kind}', processing_status=UploadBatch.Processing.COMMITTED).first()
    if existing:
        return existing
    return UploadBatch.objects.create(kind=kind, original_filename=name or f'test-{kind}', processing_status=UploadBatch.Processing.COMMITTED,
                                      validation_status=UploadBatch.Validation.PASSED, committed_at=timezone.now())


def make_unit(technology: str, circle: str, active_from: date = date(2020, 1, 1), active_until: date | None = None) -> ReportingUnit:
    """A reporting unit (circle + technology) of the effective-dated configuration (apps.sitedata.reporting)."""
    unit, _ = ReportingUnit.objects.update_or_create(technology=technology, circle=circle,
                                                      defaults={'active_from': active_from, 'active_until': active_until})
    return unit


def make_units(rows) -> None:
    """Reporting units for every (technology, circle) of ``rows`` (e.g. the dashboard sites of a test matrix)."""
    for technology, circle in {(t, c) for t, c in rows}:
        make_unit(technology, circle)


def make_site(site_id: str, *, technology: str = Technology.G4, circle: str = 'MP', site_name: str = '', on_air_date: date | None = date(2025, 1, 1),
              om_start_date: date | None = None, outside_scope: bool = False, unit: bool = True, **fields) -> Site:
    """A site of the site master (Consolidation Matrix) with its BSNL Site ID identifier (and, by default, an active
    reporting unit for its technology and circle when none exists yet)."""
    if unit and not outside_scope and not ReportingUnit.objects.filter(technology=technology, circle=circle).exists():
        make_unit(technology, circle)
    from apps.sitedata.identifiers import key_of
    key = key_of(site_id)
    entity = fields.pop('entity', 'Sterlite' if outside_scope else technology)
    site = Site.objects.create(
        bsnl_site_id=site_id, site_key=key, entity=entity, technology='' if outside_scope else technology,
        reporting_scope=Site.Scope.OUTSIDE if outside_scope else Site.Scope.DASHBOARD, circle=circle, site_name=site_name or site_id,
        on_air=on_air_date is not None, on_air_date=on_air_date, om_start_date=om_start_date, matrix_batch=batch(), source_row=Site.objects.count() + 1,
        **fields)
    SiteIdentifier.objects.create(site=site, kind=SiteIdentifier.Kind.BSNL_SITE_ID, value=site_id, key=key, batch=site.matrix_batch)
    return site


def make_daily(site: Site, day: date, outage: float, *, kind: str = UploadBatch.Kind.UPTIME_MASTER) -> DailySitePerformance:
    """A daily record of ``site`` on ``day`` with ``outage`` minutes (0-1440), from an upload of ``kind``."""
    return DailySitePerformance.objects.create(site=site, report_date=day, technology=site.technology, circle=site.circle,
                                               availability_pct=availability_from_outage(outage), outage_minutes=outage, batch=batch(kind))
