"""Historical monthly trend points from the imported workbook totals (MonthlySitePerformance, category historical_import).

Only for trend charts (Overview / 4G / LWE monthly uptime and outage). They are added beside the months calculated from
daily records and never enter the dashboard dataset, so no KPI card, period KPI, threshold, export, All KPI's or
Portfolio figure reads them.

- Current revisions only; months before the first month the dashboard calculates from daily records (``before``), so a
  month is never shown from both sources. Missing months stay missing; a site without a value is not a record.
- Same project / circle filters and the user's Dashboard grants (pairs) as the dashboard.
- Availability is outage-weighted over the site-minutes of the month: 100 x (1 - total outage / (1440 x sum of the
  records' calendar days)), as the dashboard measures any month (metrics.uptime_pct). reporting_days (NULL for these
  records) is not used. The source's own Up-Time agrees with this per site (validated at import).
- Every imported site-month counts, whatever its On-Air note (historical values as reported, not eligible operational
  performance); the notes are returned per month for traceability.
"""
from __future__ import annotations

import calendar
from collections import Counter, defaultdict
from datetime import date

from django.db.models import Count, Q, Sum

from .models import MonthlySitePerformance, Site

HISTORICAL, DAILY = 'historical_import', 'daily_derived'
LABELS = {HISTORICAL: 'Historical monthly (Excel source)', DAILY: 'Calculated from daily records'}


def records(pairs, before: date | None, report_type: str | None = None, circle: str | None = None):
    """Current historical records within the user's pairs (None: all) and the filters, before ``before``."""
    qs = MonthlySitePerformance.objects.filter(calculation_category=MonthlySitePerformance.Category.HISTORICAL_IMPORT, is_current=True,
                                               site__reporting_scope=Site.Scope.DASHBOARD)
    if before is not None:
        qs = qs.filter(month__lt=before)
    if report_type:
        qs = qs.filter(technology=report_type)
    if circle:
        qs = qs.filter(site__circle=circle)
    if pairs is not None:
        if not pairs:
            return qs.none()
        allowed = Q()
        for project, code in pairs:
            allowed |= Q(technology=project, site__circle=code)
        qs = qs.filter(allowed)
    return qs


def month_options(pairs, before: date | None) -> list[dict]:
    """Months with historical values, oldest first (offered in the trend month picker, apart from the calculated months)."""
    months = sorted(set(records(pairs, before).order_by().values_list('month', flat=True).distinct()))
    return [{'key': m.strftime('%Y-%m'), 'label': m.strftime('%b-%y'), 'source': HISTORICAL} for m in months]


def _uptime(outage: float, site_days: int) -> float | None:
    from apps.dashboard.metrics import uptime_pct
    return uptime_pct(outage, site_days)


def monthly_points(pairs, before: date | None, report_type: str | None = None, circle: str | None = None,
                   report_types=(), circle_keys=()) -> list[dict]:
    """One point per month with historical values, in the shape of the dashboard's monthly points (``source`` set)."""
    qs = records(pairs, before, report_type, circle)
    totals: dict = defaultdict(lambda: [0.0, 0, 0])  # (month, group) -> outage minutes, site-days, sites
    for row in qs.order_by().values('month', 'technology', 'site__circle').annotate(outage=Sum('total_outage_minutes'), days=Sum('calendar_days'),
                                                                                        sites=Count('id')):
        for group in (None, ('type', row['technology']), ('circle', f"{row['technology']}|{row['site__circle']}")):
            t = totals[(row['month'], group)]
            t[0] += row['outage']
            t[1] += row['days']
            t[2] += row['sites']
    notes: dict = defaultdict(Counter)
    for month, note, n in qs.order_by().values_list('month', 'source_values__on_air_note').annotate(n=Count('id')):
        notes[month][note or 'unknown'] += n
    types = list(report_types) or sorted({g[1] for (_, g) in totals if g and g[0] == 'type'})
    circles = list(dict.fromkeys([*circle_keys, *sorted({g[1] for (_, g) in totals if g and g[0] == 'circle'})]))

    def value(month, group):
        t = totals.get((month, group))
        return (_uptime(t[0], t[1]), round(t[0], 2)) if t and t[1] else (None, None)

    points, previous = [], None
    for month in sorted({m for (m, g) in totals if g is None}):
        uptime, outage = value(month, None)
        sites = totals[(month, None)][2]
        # Several projects shown and one without a value this month (e.g. LWE before Jan-26 or held): a combined figure
        # would be a different mix of networks, not comparable with the other months; it stays empty (the project lines show).
        missing_types = [t for t in types if value(month, ('type', t))[1] is None] if len(types) > 1 else []
        if missing_types:
            uptime, outage = None, None
        points.append({
            'key': month.strftime('%Y-%m'), 'label': month.strftime('%b-%y'), 'start': month.isoformat(),
            'days': calendar.monthrange(month.year, month.month)[1], 'partial': False,
            'sites_in_scope': sites, 'sites_reported': sites,  # sites with a value in the source; no population is applied
            'uptime_pct': uptime, 'uptime_pct_blank_as_zero': None,
            'change_pts': round(uptime - previous, 2) if uptime is not None and previous is not None else None,
            'by_report_type': {t: value(month, ('type', t))[0] for t in types},
            'outage_minutes': outage,
            'outage_by_report_type': {t: value(month, ('type', t))[1] for t in types},
            'by_circle': {k: value(month, ('circle', k))[0] for k in circles},
            'outage_by_circle': {k: value(month, ('circle', k))[1] for k in circles},
            'finalization_status': None,
            'source': HISTORICAL, 'source_label': LABELS[HISTORICAL],
            'missing_report_types': missing_types,
            'on_air_notes': dict(notes[month]),
        })
        if uptime is not None:
            previous = uptime
    return points
