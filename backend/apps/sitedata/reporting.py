"""Reporting completeness (approved rules B-1/B-2, B-4, B-5, B-6, B-7): which reporting units are expected on a date,
whether each unit-day is covered, and whether a date or period is Complete or Provisional.

- Reporting unit = circle + technology (ReportingUnit), expected only while active on the date (effective-dated
  configuration; a unit activated during a month is expected from its activation date, a deactivated unit no longer).
- Sites expected on a date: the unit's dashboard-scope sites whose Consolidation Matrix Site On-Air Date is on or before
  the date (B-5). The first date in an uploaded file is never used as an eligibility date.
- A unit-day is covered when the share of expected sites with a daily record reaches the coverage threshold effective
  on that date (CoverageThreshold, B-6; boundary: a share equal to the threshold counts as covered). A unit-day with no
  expected site (no site On-Air yet) is covered trivially. Missing records are never zero: they only make the unit-day
  uncovered.
- A date is Complete when every expected unit (within the units a user can see) is covered; otherwise Provisional.
  A period (week, month, MTD) is Complete only when it has ended (every calendar day is on or before the latest
  reporting date) and every one of its days is Complete; otherwise Provisional (B-4). Missing data of one unit never
  hides the data of others (B-7): statuses only label figures, they never exclude dates.
"""
from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.db.models import Count, F, Q

from .models import CoverageThreshold, DailySitePerformance, ReportingUnit, Site

COMPLETE, PROVISIONAL = 'Complete', 'Provisional'
Unit = tuple[str, str]  # (technology, circle)


def threshold_history() -> list[tuple[date, float]]:
    """[(effective_from, value_pct)] ascending; the latest row per effective date wins."""
    rows = {}
    for effective, value in CoverageThreshold.objects.order_by('effective_from', 'id').values_list('effective_from', 'value_pct'):
        rows[effective] = float(value)
    return sorted(rows.items())


def threshold_on(day: date, history: list[tuple[date, float]] | None = None) -> float:
    """Coverage threshold (%) effective on ``day``; 100 when nothing is configured (every expected site)."""
    history = threshold_history() if history is None else history
    value = 100.0
    for effective, pct in history:
        if effective <= day:
            value = pct
        else:
            break
    return value


def units_config() -> list[tuple[Unit, date, date | None]]:
    return [((u.technology, u.circle), u.active_from, u.active_until) for u in ReportingUnit.objects.all()]


def active_units(day: date, config=None) -> set[Unit]:
    config = units_config() if config is None else config
    return {unit for unit, start, end in config if start <= day and (end is None or day <= end)}


def coverage(days, *, pairs=None) -> dict[date, dict[Unit, dict]]:
    """{date: {unit: {'expected', 'with_data', 'share', 'threshold', 'covered'}}} for the units active on each date
    (within ``pairs`` when given). One query for the site master and one for the daily records."""
    days = sorted(set(days))
    if not days:
        return {}
    config = units_config()
    history = threshold_history()
    on_air: dict[Unit, list[date]] = defaultdict(list)
    for technology, circle, start in Site.objects.filter(reporting_scope=Site.Scope.DASHBOARD).values_list('technology', 'circle', 'on_air_date'):
        if start is not None:
            on_air[(technology, circle)].append(start)
    for dates in on_air.values():
        dates.sort()
    counts: dict[tuple[date, Unit], int] = {}
    rows = (DailySitePerformance.objects.order_by().filter(report_date__gte=days[0], report_date__lte=days[-1],
                                                           site__reporting_scope=Site.Scope.DASHBOARD)
            .values('report_date', 'technology', 'circle')
            .annotate(n=Count('id', filter=Q(site__on_air_date__isnull=False, site__on_air_date__lte=F('report_date')))))
    for r in rows:
        counts[(r['report_date'], (r['technology'], r['circle']))] = r['n']
    out: dict[date, dict[Unit, dict]] = {}
    for day in days:
        threshold = threshold_on(day, history)
        units = {}
        for unit in sorted(active_units(day, config)):
            if pairs is not None and unit not in pairs:
                continue
            expected = bisect_right(on_air.get(unit, []), day)
            with_data = counts.get((day, unit), 0)
            share = 100.0 * with_data / expected if expected else None
            covered = expected == 0 or round(share, 6) >= threshold
            units[unit] = {'expected': expected, 'with_data': with_data, 'share': None if share is None else round(share, 2),
                           'threshold': threshold, 'covered': covered}
        out[day] = units
    return out


def date_status(unit_coverage: dict, day: date, units: set[Unit] | None = None) -> dict:
    """Status of one date over ``units`` (None: every unit in the coverage table)."""
    entries = {u: v for u, v in (unit_coverage or {}).get(day, {}).items() if units is None or u in units}
    missing = sorted(f'{t} {c}' for (t, c), v in entries.items() if not v['covered'])
    return {'date': day.isoformat(), 'status': PROVISIONAL if missing else COMPLETE, 'missing_units': missing}


def period_status(unit_coverage: dict, period_dates, latest: date | None, units: set[Unit] | None = None) -> dict:
    """Complete only when the period has ended (its last calendar day is on or before ``latest``, the latest reporting
    date) and every day of it is Complete; otherwise Provisional, with the days and units still missing."""
    period_dates = sorted(period_dates)
    if not period_dates:
        return {'status': PROVISIONAL, 'missing': [], 'ended': False}
    ended = latest is not None and period_dates[-1] <= latest
    missing = []
    for day in period_dates:
        if latest is not None and day > latest:
            continue
        if day not in (unit_coverage or {}):
            # No unit reported on this day at all: every unit expected on it is missing (never a complete day).
            absent = sorted(f'{t} {c}' for t, c in (units if units is not None else
                            {u for entries in (unit_coverage or {}).values() for u in entries}))
            missing.append({'date': day.isoformat(), 'units': absent})
            continue
        st = date_status(unit_coverage, day, units)
        if st['status'] != COMPLETE:
            missing.append({'date': st['date'], 'units': st['missing_units']})
    return {'status': COMPLETE if ended and not missing else PROVISIONAL, 'missing': missing, 'ended': ended}


def units_of(ds) -> set[Unit]:
    """The reporting units of a (possibly restricted) dashboard dataset."""
    if ds is None or not len(ds.sites):
        return set()
    return set(zip(ds.sites['report_type'], ds.sites['circle']))


def as_decimal(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal('0.01'))
