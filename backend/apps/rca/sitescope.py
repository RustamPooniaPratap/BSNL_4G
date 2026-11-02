"""Site Scope of the RCA module: All Sites, O&M Start Sites or O&M Not Started Sites.

One rule for every RCA page (``services.filtered`` applies it, so the register, the summary pages, their options and the
breakdown all use it): an RCA record belongs to the O&M Start sites when its site's **Site Master O&M Start** for the
record's reporting month is Yes (``SiteMonthlyPerformance.om_start``, the "O&M Start - <month>" column, the same field
the dashboard's O&M Start scope uses), and to the O&M Not Started sites when it is No.

The site is found by project, circle and site key (Site Master identity). A record whose site is not in the Site Master,
or whose month has no O&M Start value, is not guessed: it is counted under All Sites only, and ``coverage`` reports it.
The O&M Start (Yes/No) written on the RCA row itself is kept as stored and not used for the scope.
"""
from __future__ import annotations

from django.db.models import Count, Q, QuerySet, Subquery
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
    """Records whose Site Master site has O&M Start = ``value`` for the record's reporting month.

    One condition per (project, circle, month) of the Site Master's monthly O&M Start: the record's project and circle,
    a reporting date in that month, and a site key among that month's sites with that value (an uncorrelated subquery
    the database evaluates once, instead of a lookup per record)."""
    import calendar

    from apps.uptimedb.models import SiteMonthlyPerformance
    monthly = SiteMonthlyPerformance.objects.filter(om_start=value)
    q = Q(pk__in=[])
    for project, circle, month in monthly.order_by().values_list('site__project', 'site__circle', 'month').distinct():
        last = month.replace(day=calendar.monthrange(month.year, month.month)[1])
        keys = monthly.filter(site__project=project, site__circle=circle, month=month).values('site__site_key')
        q |= Q(project=project, circle=circle, reporting_date__range=(month, last), site_key__in=Subquery(keys))
    return q


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


def dashboard_scope(scope: str) -> str:
    """The dashboard selection scope for the same sites: On-Air sites, and of those the O&M Start / Not Started ones."""
    return {ALL: 'on_air', OM_START: 'on_air_om_start', OM_NOT_STARTED: 'on_air_om_not_started'}[scope]
