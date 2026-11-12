"""Site Scope of the RCA module: All Sites, O&M Start Sites or O&M Not Started Sites.

One rule for every RCA page (``services.filtered`` applies it, so the register, the summary pages, their options and the
breakdown all use it): an RCA record belongs to the O&M Start sites when its site's **Consolidation Matrix O&M Start
Date** (``apps.sitedata.models.Site.om_start_date``) is on or before the last day of the record's reporting month (the
rule of ``apps.sitedata.rules.om_effective_from`` and of every O&M figure), and to the O&M Not Started sites when the
site has no O&M Start Date or a later one.

The site is the dashboard-scope site of the site master with the record's project as technology and the record's site
key. A record whose site is not in the site master is not guessed: it is counted under All Sites only, and ``coverage``
reports it. The O&M Start (Yes/No) written on the RCA row itself is kept as stored and not used for the scope.
"""
from __future__ import annotations

from django.db.models import Count, DateField, Exists, OuterRef, Q, QuerySet
from django.db.models.functions import TruncMonth
from rest_framework.exceptions import ValidationError

ALL, OM_START, OM_NOT_STARTED = 'all', 'om_start', 'om_not_started'
SCOPES = {ALL: 'All Sites', OM_START: 'O&M Start Sites', OM_NOT_STARTED: 'O&M Not Started Sites'}


def parse(value: str | None) -> str:
    """The scope of a request (``site_scope``); empty means All Sites."""
    value = (value or ALL).strip()
    if value not in SCOPES:
        raise ValidationError({'site_scope': f'Choose one of: {", ".join(SCOPES)}.'})
    return value


def _site_om(value: bool) -> Q:
    """Records whose site master site is (``value`` True) or is not (False) O&M Start in the record's reporting month.

    A correlated EXISTS on the site master (technology = project, site key, dashboard scope). "O&M Start Date on or
    before the last day of the reporting month" is tested as "first day of the O&M Start Date's month on or before the
    reporting date" (the same condition: both say the start month is not after the reporting month). A record without
    such a site matches neither value."""
    from apps.sitedata.models import Site
    sites = (Site.objects.filter(reporting_scope=Site.Scope.DASHBOARD, technology=OuterRef('project'), site_key=OuterRef('site_key'))
             .annotate(om_month=TruncMonth('om_start_date', output_field=DateField())))
    if value:
        sites = sites.filter(om_start_date__isnull=False, om_month__lte=OuterRef('reporting_date'))
    else:
        sites = sites.filter(Q(om_start_date__isnull=True) | Q(om_month__gt=OuterRef('reporting_date')))
    return Q(Exists(sites))


def apply(qs: QuerySet, scope: str) -> QuerySet:
    """RCA records of the scope (All Sites: unchanged)."""
    if scope == OM_START:
        return qs.filter(_site_om(True))
    if scope == OM_NOT_STARTED:
        return qs.filter(_site_om(False))
    return qs


def coverage(qs: QuerySet) -> dict:
    """How the records of ``qs`` (already filtered by everything but the scope) are classified."""
    counts = qs.order_by().aggregate(total=Count('id'), om_start=Count('id', filter=_site_om(True)),
                                     not_started=Count('id', filter=_site_om(False)))
    return {**counts, 'unclassified': counts['total'] - counts['om_start'] - counts['not_started']}


# The RCA site figures (breakdown.site_metrics, overview) use the site POPULATION of the request (``scope``: On-Air or O&M
# Start, apps.dashboard.metrics) narrowed by this Site Scope's O&M Start status; the Site Scope itself never selects a
# population.
