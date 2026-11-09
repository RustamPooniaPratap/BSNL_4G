"""Monthly site performance calculated from the central daily records, by the shared rules (rules.py).

Two categories per site and month, both outage-weighted over the days that have a record:
    availability = 100 x (1 - total outage / (1440 x reporting days))
- daily_derived: every reported day of the month.
- om_start: the O&M Start days only, from the site's matrix O&M Start Date (rules.om_effective_from): a site whose
  date falls in the month counts from that date; a site whose date is later, missing or unreadable has no om_start
  result (missing / unreadable dates are flagged on the site for review, never guessed).
- on_air: the same with the matrix Site On-Air Date (rules.on_air_effective_from).
Days without a record are not reported: not 0% and not 100%. Only dashboard-scope sites have daily records, so
outside-scope sites never get a result.

A recalculation that changes a result adds a new revision (the earlier one is kept, no longer current). A finalized
month is not recalculated unless forced, which also adds revisions.
"""
from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date

from django.db import transaction
from django.utils import timezone

from apps.accounts.audit import audit

from .models import DailySitePerformance, MonthlySitePerformance, Site
from .rules import MINUTES_PER_DAY, month_bounds, om_effective_from, on_air_effective_from

DAILY, OM, ON_AIR = (MonthlySitePerformance.Category.DAILY_DERIVED, MonthlySitePerformance.Category.OM_START,
                     MonthlySitePerformance.Category.ON_AIR)
TOLERANCE = 1e-6


class MonthFinalized(Exception):
    pass


def site_month_results(month: date) -> dict[tuple[int, str, str], dict]:
    """(site, technology, category) -> the month's totals from the daily records of dashboard-scope sites."""
    start, end = month_bounds(month)
    days_in_month = calendar.monthrange(month.year, month.month)[1]
    dates = list(Site.objects.filter(reporting_scope=Site.Scope.DASHBOARD).values_list('id', 'om_start_date', 'on_air_date'))
    effective = {OM: {pk: om_effective_from(d, month) for pk, d, _ in dates}, ON_AIR: {pk: on_air_effective_from(d, month) for pk, _, d in dates}}
    totals = defaultdict(lambda: {'outage': 0.0, 'days': 0, 'batches': set()})
    for site_id, technology, day, outage, batch in (DailySitePerformance.objects
                                                    .filter(report_date__gte=start, report_date__lte=end, site__reporting_scope=Site.Scope.DASHBOARD)
                                                    .values_list('site_id', 'technology', 'report_date', 'outage_minutes', 'batch_id')):
        categories = [DAILY] + [c for c in (OM, ON_AIR) if effective[c].get(site_id) is not None and day >= effective[c][site_id]]
        for category in categories:
            t = totals[(site_id, technology, category)]
            t['outage'] += outage
            t['days'] += 1
            t['batches'].add(batch)
    out = {}
    for (site_id, technology, category), t in totals.items():
        first = start if category == DAILY else effective[category][site_id]
        out[(site_id, technology, category)] = {
            'total_outage_minutes': t['outage'], 'reporting_days': t['days'], 'effective_from': first,
            'calendar_days': days_in_month if category == DAILY else (end - first).days + 1,
            'availability_pct': 100 * (1 - t['outage'] / (MINUTES_PER_DAY * t['days'])), 'source_batches': sorted(t['batches'])}
    return out


def calculate_month(month: date, *, force: bool = False, request=None) -> dict:
    month = month.replace(day=1)
    current = {(m.site_id, m.technology, m.calculation_category): m
               for m in MonthlySitePerformance.objects.filter(month=month, is_current=True)}
    if not force and any(m.finalized_at for m in current.values()):
        raise MonthFinalized(f'{month:%b %Y} is finalized; recalculate with force=True to add revisions.')
    results = site_month_results(month)
    created, revised, unchanged = [], [], 0
    for (site_id, technology, category), r in results.items():
        old = current.get((site_id, technology, category))
        if (old and old.reporting_days == r['reporting_days'] and old.effective_from == r['effective_from']
                and abs(old.total_outage_minutes - r['total_outage_minutes']) <= TOLERANCE):
            unchanged += 1
            continue
        record = MonthlySitePerformance(site_id=site_id, month=month, technology=technology, calculation_category=category,
                                        revision=old.revision + 1 if old else 1, **r)
        (revised if old else created).append((old, record))
    with transaction.atomic():
        MonthlySitePerformance.objects.filter(pk__in=[old.pk for old, _ in revised]).update(is_current=False)
        MonthlySitePerformance.objects.bulk_create([rec for _, rec in created + revised], batch_size=2000)
    om_review = Site.objects.filter(reporting_scope=Site.Scope.DASHBOARD).exclude(om_start_date_issue='').count()
    summary = {'month': month.isoformat(), 'sites': len({k[0] for k in results}), 'om_start_sites': sum(1 for k in results if k[2] == OM),
               'on_air_sites': sum(1 for k in results if k[2] == ON_AIR), 'om_start_date_review_sites': om_review, 'created': len(created), 'revised': len(revised), 'unchanged': unchanged}
    audit('sitedata.monthly_calculated', request, **summary)
    return summary


def finalize_month(month: date, *, user, request=None) -> int:
    from django.core.exceptions import PermissionDenied

    from apps.accounts.roles import ADMIN, role_of
    if role_of(user) != ADMIN:
        raise PermissionDenied('Only an Admin can finalize a month.')
    n = (MonthlySitePerformance.objects.filter(month=month.replace(day=1), is_current=True, finalized_at__isnull=True)
         .update(finalized_at=timezone.now(), finalized_by=user))
    audit('sitedata.month_finalized', request, month=month.replace(day=1), records=n)
    return n
