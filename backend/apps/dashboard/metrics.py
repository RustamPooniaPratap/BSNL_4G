"""Reporting business rules applied to the normalised Master workbook data.

The formulas reproduce the workbook's own summary sheets (see
docs/business-rules.md for the cell references and reconciliation):

    uptime % = 100 x (1 - total outage minutes / (1440 x site-days reported))

* Daily uptime (Day wise Trend):  site-days = sites in scope with a value that day.
* MTD uptime (Summ "Oct-26 MTD"):  site-days summed from the 1st of the month to
  the selected date.
* Site buckets (Uptime Bucketization): each site's MTD uptime, using the
  workbook's thresholds.

Unlike the workbook, a blank value counts as "not reported" and is left out of
the denominator instead of counting as zero outage (100% uptime).
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from fractions import Fraction

import numpy as np
import pandas as pd

from .workbook import MINUTES_PER_DAY, Dataset

# The site POPULATION of every site-based figure (approved project-wide rule): the On-Air or the O&M Start sites of the
# Consolidation Matrix, each site counted from its effective date (rules.on_air_effective_from / om_effective_from), per
# period: a history month uses the sites effective in that month. The population decides total site counts, uptime,
# outage, buckets, USD, NSLA, trends, comparisons, team metrics, RCA site metrics, All KPI's, exports and emails; two
# populations are never mixed. Only these two are user-facing (request parameter ``scope``); a missing ``scope`` is
# DEFAULT_SCOPE. "all" is internal only (status counts, the workbook cross-check), never a reporting population.
SCOPES = {
    'on_air': 'On-Air sites',
    'om_start': 'O&M Start sites',
}
POPULATIONS = SCOPES
DEFAULT_SCOPE = 'on_air'
# population -> (current flag column of the dataset, Consolidation Matrix effective date column)
POPULATION_COLUMNS = {'on_air': ('on_air', 'on_air_date'), 'om_start': ('om_start', 'om_start_date')}
# File name suffix of the Excel reports per population.
POPULATION_SUFFIX = {'on_air': 'OnAir', 'om_start': 'OMStart'}


def population(scope: str) -> dict:
    """The ``population`` block of every response with population-based figures: {"scope", "label"}."""
    return {'scope': scope, 'label': POPULATIONS.get(scope, 'All sites')}

# (id, label, workbook label, lower bound %). Thresholds match the workbook formula
# =IF(x>=98.5%,">98.5",IF(x>=97%,">97 To <98.5",IF(x>=90%,">90 To <97",IF(x>=60%,">60 To <90","<60"))))
BUCKETS = (
    ('lt_60', 'Below 60%', '<60', None),
    ('60_90', '60% to <90%', '>60 To <90', 60.0),
    ('90_97', '90% to <97%', '>90 To <97', 90.0),
    ('97_98_5', '97% to <98.5%', '>97 To <98.5', 97.0),
    ('gte_98_5', '98.5% and above', '>98.5', 98.5),
)
BUCKET_IDS = tuple(bucket[0] for bucket in BUCKETS)

# The workbook's weekly columns (Wk-1 .. Wk-4) use these day-of-month ranges.
WEEKS = (('Week 1', 1, 7), ('Week 2', 8, 14), ('Week 3', 15, 21), ('Week 4', 22, 31))

SORT_FIELDS = (
    'site_id', 'site_name', 'report_type', 'circle', 'oa',
    'outage_minutes', 'daily_uptime_pct', 'mtd_uptime_pct', 'ie_name', 'ci_name',
)


@dataclass(frozen=True)
class Selection:
    report_type: str | None = None
    circle: str | None = None
    scope: str = DEFAULT_SCOPE


def uptime_pct(outage_minutes: float, site_days: int) -> float | None:
    if site_days <= 0:
        return None
    return round(100.0 * (1.0 - outage_minutes / (MINUTES_PER_DAY * site_days)), 4)


def base_mask(ds: Dataset, selection: Selection) -> np.ndarray:
    mask = np.ones(len(ds.sites), dtype=bool)
    if selection.report_type:
        mask &= (ds.sites['report_type'] == selection.report_type).to_numpy()
    if selection.circle:
        mask &= (ds.sites['circle'] == selection.circle).to_numpy()
    return mask


def scope_mask(ds: Dataset, selection: Selection) -> np.ndarray:
    """The selection's sites of its population in the reporting month (population_flags); an internal scope that is not
    a population ("all") restricts nothing."""
    return base_mask(ds, selection) & population_flags(ds, selection.scope)


def mtd_positions(ds: Dataset, day: date) -> tuple[list[int], list[date]]:
    """Reported date columns from the 1st of the month up to ``day``, plus the gaps."""
    positions, missing = [], []
    for i, current in enumerate(ds.dates):
        if current > day:
            break
        if current in ds.reported_dates:
            positions.append(i)
        else:
            missing.append(current)
    return positions, missing


def site_uptime(block: np.ndarray) -> np.ndarray:
    """Per-row uptime % over the columns in ``block``; NaN when nothing was reported."""
    reported = (~np.isnan(block)).sum(axis=1)
    with np.errstate(invalid='ignore', divide='ignore'):
        values = 100.0 * (1.0 - np.nansum(block, axis=1) / (MINUTES_PER_DAY * reported))
    return np.where(reported > 0, values, np.nan)


# Percentages are compared with the thresholds after rounding to this many decimals, so floating-point noise never moves
# a site across a threshold: e.g. 98.5% stored as 21.60000000000002 outage minutes gives 98.49999999999999% when summed,
# which must still be 98.5% (bucket ">=98.5", not NSLA). Six decimals is far below any reported precision.
THRESHOLD_DECIMALS = 6


def comparable(values):
    """Values rounded for threshold comparisons (NaN stays NaN)."""
    return np.round(values, THRESHOLD_DECIMALS)


def bucket_ids(values: np.ndarray) -> np.ndarray:
    values = comparable(np.asarray(values, dtype=float))
    conditions = [values >= bound for _, _, _, bound in reversed(BUCKETS) if bound is not None]
    choices = [bucket_id for bucket_id, _, _, bound in reversed(BUCKETS) if bound is not None]
    result = np.select(conditions, choices, default='lt_60').astype(object)
    result[np.isnan(values)] = None
    return result


# --- USD / NSLA: one per-site rule each (approved rule B-3), over the SELECTED POPULATION ------------------------------
# NSLA: a site of the selected population (On-Air or O&M Start) whose uptime POOLED over its reported days of the period,
# counted from the population's effective date, is below 98.5% (compared after ``comparable`` rounding, so exactly 98.5%
# is not NSLA; one bad day does not make a site NSLA when its period uptime is >= 98.5%). Missing days are not reported,
# never zero; a site without a value is never NSLA.
# USD: a site of the selected population with outage > 0 on at least one REPORTED day within its effective period (a
# missing day is never "down"). Both follow the request's population in every consumer (dashboard, All KPI's, RCA,
# exports, emails): the former fixed O&M Start NSLA population and the per-consumer USD populations no longer exist.
NSLA_THRESHOLD = 98.5
USD_RULE = "Outage > 0 on at least one reported day of the period within the site's effective period (a missing day never counts)."
NSLA_RULE = ('Sites of the selected population whose uptime over the period (pooled over their reported days, from their '
             'effective date) is below 98.5%; exactly 98.5% is not NSLA; a site without a value is not NSLA.')


def usd_rule(scope: str) -> str:
    return f"{population(scope)['label']}: {USD_RULE}"


def nsla_rule(scope: str) -> str:
    return f"{population(scope)['label']}: {NSLA_RULE}"


def usd_mask(block: np.ndarray) -> np.ndarray:
    """Per row: outage > 0 on at least one reported day of ``block`` [rows x days] (NaN = not reported, never down)."""
    block = np.asarray(block, dtype=float)
    if block.ndim == 1:
        block = block[:, None]
    if not block.shape[1]:
        return np.zeros(block.shape[0], dtype=bool)
    return (np.nan_to_num(block, nan=0.0) > 0).any(axis=1)


def nsla_mask(uptime: np.ndarray, eligible: np.ndarray | None = None) -> np.ndarray:
    """Per row: the period uptime (pooled over reported days) is below 98.5% after ``comparable`` rounding; rows without
    a value are never NSLA. ``eligible``: the population of the period (rows outside it are never NSLA)."""
    uptime = np.asarray(uptime, dtype=float)
    mask = ~np.isnan(uptime) & (comparable(np.nan_to_num(uptime, nan=100.0)) < NSLA_THRESHOLD)
    return mask if eligible is None else mask & np.asarray(eligible, dtype=bool)


def _last_day(day: date) -> date:
    return day.replace(day=calendar.monthrange(day.year, day.month)[1])


def _dates_of(ds: Dataset, column: str) -> np.ndarray:
    """A site date column as datetime64[D] (NaT when blank)."""
    return np.array([np.datetime64(v, 'D') if v is not None and not pd.isna(v) else np.datetime64('NaT')
                     for v in ds.sites[column].tolist()], dtype='datetime64[D]')


def effective_in_month(ds: Dataset, column: str, month: date) -> np.ndarray | None:
    """Per site: effective in ``month`` by its matrix date (``on_air_date`` / ``om_start_date``: on or before the month's
    last day, as rules.on_air_effective_from / om_effective_from). None when the source has no such dates."""
    if column not in ds.sites:
        return None
    starts = _dates_of(ds, column)
    return ~np.isnat(starts) & (starts <= np.datetime64(_last_day(month), 'D'))


def population_flags(ds: Dataset, scope: str, month: date | None = None) -> np.ndarray:
    """THE population helper: per site of ``ds``, a member of population ``scope`` in ``month``.

    - The reporting month (``month`` None or a date in it): the dataset's current flags (sitedata.dataset: On-Air by the
      Site On-Air Date on or before the latest reporting date; O&M Start by the O&M Start Date on or before the month end).
    - An earlier month: the sites effective in that month by their matrix date (approved rule B-5), so a historical period
      uses the status effective then. Sources without matrix dates (a single workbook) use the current flags.
    - A scope that is not a population (internal "all"): every site.
    """
    if scope not in POPULATION_COLUMNS:
        return np.ones(len(ds.sites), dtype=bool)
    flag, column = POPULATION_COLUMNS[scope]
    if month is not None and ds.dates and not (ds.dates[0] <= month <= ds.dates[-1]):
        flags = effective_in_month(ds, column, month)
        if flags is not None:
            return flags
    return ds.sites[flag].to_numpy(dtype=bool)


def effective_on(ds: Dataset, scope: str, day: date) -> np.ndarray:
    """Per site: a member of population ``scope`` ON ``day`` (matrix effective date on or before it), for single-day
    lists (the Daily Uptime Report). Sources without matrix dates: the current flags; "all": every site."""
    if scope not in POPULATION_COLUMNS:
        return np.ones(len(ds.sites), dtype=bool)
    flag, column = POPULATION_COLUMNS[scope]
    if column not in ds.sites:
        return ds.sites[flag].to_numpy(dtype=bool)
    starts = _dates_of(ds, column)
    return ~np.isnat(starts) & (starts <= np.datetime64(day, 'D'))


def population_eligible(ds: Dataset, rows: np.ndarray, scope: str, period_dates=None) -> np.ndarray:
    """Per row of ``rows``: in population ``scope`` of a period: the population of the period's last date (its month's
    population, population_flags); no dates: the reporting month. With population_view (values from each site's
    effective date) this is the period's effective population: a site counts only within its effective period."""
    dates = sorted(set(period_dates or []))
    return population_flags(ds, scope, dates[-1] if dates else None)[np.asarray(rows, dtype=int)]


def population_rows(ds: Dataset, rows: np.ndarray, scope: str, period_dates=None) -> np.ndarray:
    """``rows`` limited to population ``scope`` of a period (population_eligible)."""
    rows = np.asarray(rows, dtype=int)
    return rows[population_eligible(ds, rows, scope, period_dates)]


def population_view(ds: Dataset, scope: str) -> Dataset:
    """``ds`` with every site's values before its effective date of population ``scope`` (per month) left out: the values
    of the dataset variant of that population (portfolio._effective with rules.on_air_effective_from / om_effective_from),
    vectorised and cached on ``ds``. Masking is idempotent, so the variant itself is unchanged. Sources without matrix
    dates, and internal scopes ("all"): ``ds``."""
    key = f'population_view:{scope}'
    view = ds._memo.get(key)
    if view is not None:
        return view
    column = POPULATION_COLUMNS.get(scope, (None, None))[1]
    if column is None or column not in ds.sites:
        view = ds
    else:
        import dataclasses
        starts = _dates_of(ds, column)

        def masked(matrix, dates):
            if not len(dates):
                return matrix
            end = np.datetime64(_last_day(dates[0]), 'D')
            days = np.array(dates, dtype='datetime64[D]')
            keep = (~np.isnat(starts) & (starts <= end))[:, None] & (days[None, :] >= starts[:, None])
            return np.where(keep, matrix, np.nan)

        view = dataclasses.replace(ds, outage=masked(ds.outage, ds.dates), _positions={},
                                   daily_history=tuple({**h, 'outage': masked(h['outage'], h['dates'])} for h in ds.daily_history))
    ds._memo[key] = view
    return view


def period_block(ds: Dataset, rows: np.ndarray, dates) -> tuple[np.ndarray, list[date]]:
    """Outage [rows x days] of the ``dates`` that have data: reporting dates of the current month and the days of earlier
    months with any value (daily_history). Days without data are not columns (never zero)."""
    wanted = set(dates)
    blocks, used = [], []
    cols = [ds.position(d) for d in sorted(wanted) if d in ds.reported_dates]
    if cols:
        blocks.append(ds.outage[np.ix_(rows, cols)])
        used += [ds.dates[c] for c in cols]
    for entry in ds.daily_history:
        idx = [i for i, d in enumerate(entry['dates']) if d in wanted and not np.isnan(entry['outage'][:, i]).all()]
        if idx:
            blocks.append(entry['outage'][np.ix_(rows, idx)])
            used += [entry['dates'][i] for i in idx]
    if not blocks:
        return np.full((len(rows), 0), np.nan), []
    return np.hstack(blocks), used


def nsla_dates(ds: Dataset, rows: np.ndarray, dates, *, scope: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(eligible, uptime, nsla) per row for a period of ``dates``: population ``scope`` of the period
    (population_eligible), uptime pooled over the reported days from each site's effective date (population_view)."""
    rows = np.asarray(rows, dtype=int)
    dates = sorted(set(dates))
    if not dates:
        empty = np.zeros(len(rows), dtype=bool)
        return empty, np.full(len(rows), np.nan), empty
    block, _ = period_block(population_view(ds, scope), rows, dates)
    eligible = population_eligible(ds, rows, scope, dates)
    uptime = np.where(eligible, site_uptime(block) if block.shape[1] else np.nan, np.nan)
    return eligible, uptime, nsla_mask(uptime, eligible)


def nsla_month(ds: Dataset, rows: np.ndarray, i: int, *, scope: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(eligible, uptime, nsla) per row for history month ``i`` of ``ds.months`` (month_values of the population view;
    the population effective in that month)."""
    rows = np.asarray(rows, dtype=int)
    m_outage, m_days, _down = month_values(population_view(ds, scope), i, rows)
    eligible = population_flags(ds, scope, ds.months[i]['start'])[rows]
    uptime = np.where(eligible, _per_site_uptime(m_outage, m_days), np.nan)
    return eligible, uptime, nsla_mask(uptime, eligible)


def usd_dates(ds: Dataset, rows: np.ndarray, dates, *, scope: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(eligible, reported, usd) per row for a period of ``dates``: population ``scope`` of the period; ``reported``: the
    site has a value in its effective period; ``usd``: usd_mask over those values (population_view)."""
    rows = np.asarray(rows, dtype=int)
    dates = sorted(set(dates))
    if not dates:
        empty = np.zeros(len(rows), dtype=bool)
        return empty, empty, empty
    block, _ = period_block(population_view(ds, scope), rows, dates)
    eligible = population_eligible(ds, rows, scope, dates)
    reported = eligible & (~np.isnan(block)).any(axis=1) if block.shape[1] else np.zeros(len(rows), dtype=bool)
    return eligible, reported, usd_mask(block) & eligible


def usd_month(ds: Dataset, rows: np.ndarray, i: int, *, scope: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(eligible, reported, usd) per row for history month ``i`` (see usd_dates)."""
    rows = np.asarray(rows, dtype=int)
    _outage, days, down = month_values(population_view(ds, scope), i, rows)
    eligible = population_flags(ds, scope, ds.months[i]['start'])[rows]
    return eligible, eligible & (days > 0), down & eligible


def nsla_count(eligible: np.ndarray, uptime: np.ndarray, mask: np.ndarray) -> dict:
    """NSLA count of a population; ``count`` None when no eligible site has a value (never zero)."""
    reported = int((eligible & ~np.isnan(uptime)).sum())
    total = int(eligible.sum())
    count = int(mask.sum()) if reported else None
    return {'count': count, 'eligible_sites': total, 'sites_reported': reported,
            'pct': round(100.0 * count / total, 2) if total and count is not None else None}


def month_scope_rows(ds: Dataset, rows: np.ndarray, scope: str, month: date) -> np.ndarray:
    """``rows`` limited to the sites of population ``scope`` in a history ``month`` by their own effective dates
    (approved rule B-5; population_flags). Unchanged for internal scopes ("all")."""
    rows = np.asarray(rows, dtype=int)
    if scope not in POPULATION_COLUMNS:
        return rows
    return rows[population_flags(ds, scope, month)[rows]]


# --- Complete / Provisional statuses of periods (approved rule B-4; apps.sitedata.reporting) --------------------------

def status_end(ds: Dataset) -> date | None:
    """The latest reporting date of the whole data layer within the dataset's month (statuses run to it, so a unit that
    stopped reporting shows its missing days as Provisional)."""
    cov = ds.unit_coverage or {}
    layer = [d for d in ds.dates if d in cov]
    return max([*layer, *([ds.latest_date] if ds.latest_date else [])], default=None)


def units_of_rows(ds: Dataset, rows: np.ndarray) -> set[tuple[str, str]]:
    return set(zip(ds.sites['report_type'].to_numpy()[rows], ds.sites['circle'].to_numpy()[rows]))


def dates_status(ds: Dataset, dates, units=None, until: date | None = None) -> dict | None:
    """{'status': 'Complete'|'Provisional', 'missing': [{date, units}], 'ended'} of a period (its calendar ``dates``) over
    ``units`` (None: every unit), through reporting.period_status up to the data layer's latest date in the month
    (``until`` caps it, e.g. an export's reporting date). A day without any data in the layer is missing for every unit.
    None when the source has no coverage information (a single workbook)."""
    if ds.unit_coverage is None:
        return None
    from apps.sitedata import reporting
    end = status_end(ds)
    if until is not None and end is not None:
        end = min(end, until)
    dates = sorted(set(dates))
    result = reporting.period_status(ds.unit_coverage, dates, end, units)
    gaps = [d for d in dates if end is not None and d <= end and d not in ds.unit_coverage]
    if gaps:
        names = sorted(f'{t} {c}' for t, c in (units if units is not None else {u for v in ds.unit_coverage.values() for u in v}))
        known = {m['date'] for m in result['missing']}
        result['missing'] = sorted(result['missing'] + [{'date': d.isoformat(), 'units': names} for d in gaps
                                                        if d.isoformat() not in known], key=lambda m: m['date'])
        result['status'] = reporting.PROVISIONAL
    return result


def bucket_counts(ids: np.ndarray) -> dict[str, int]:
    return {bucket_id: int((ids == bucket_id).sum()) for bucket_id in BUCKET_IDS}


def outage_total(block: np.ndarray) -> float | None:
    """Total outage minutes in a block; None when nothing in it was reported (not zero)."""
    return round(float(np.nansum(block)), 2) if block.size and not np.isnan(block).all() else None


def _window(block: np.ndarray) -> tuple[float, int]:
    return float(np.nansum(block)), int((~np.isnan(block)).sum())


def month_values(ds: Dataset, i: int, rows: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per site of ``rows`` for history month ``i`` of ``ds.months``: (outage minutes, reported days, down at least once).

    From the month's daily records when the source has them (``daily_history``): a missing day is excluded from both the
    minutes and the days, never counted as zero outage, and values outside a site's effective dates are already left
    out. Otherwise from the monthly total over the month's calendar days (sources without daily history). A site
    without a value has 0 days (no uptime), never zero outage.
    """
    key = ds.months[i]['start'].strftime('%Y-%m')
    entry = next((h for h in ds.daily_history if h['key'] == key), None)
    if entry is not None and not np.isnan(entry['outage']).all():
        block = entry['outage'][rows]
        return np.nansum(block, axis=1), (~np.isnan(block)).sum(axis=1), usd_mask(block)
    values = ds.monthly_outage[rows, i]
    reported = ~np.isnan(values)
    return np.where(reported, values, 0.0), np.where(reported, ds.months[i]['days'], 0), reported & (np.nan_to_num(values, nan=0.0) > 0)


def _per_site_uptime(outage: np.ndarray, days: np.ndarray) -> np.ndarray:
    with np.errstate(invalid='ignore', divide='ignore'):
        return np.where(days > 0, 100.0 * (1.0 - outage / (MINUTES_PER_DAY * np.maximum(days, 1))), np.nan)


def week_status(ds: Dataset, first: int, last: int, units=None, until: date | None = None) -> dict:
    """A week (days ``first``..``last`` of the month, Week 4 to the month end): the columns of its reporting dates (up to
    ``until``) and its status. Complete only when the week has ended and every day is covered for ``units``
    (reporting.period_status); otherwise Provisional, and its available figures are still shown (approved rule B-4).
    Sources without coverage information: Complete when every day of the week is a reporting date."""
    last = min(last, ds.dates[-1].day)
    days = [d for d in ds.dates if first <= d.day <= last]
    cols = [i for i, d in enumerate(ds.dates) if first <= d.day <= last and d in ds.reported_dates and (until is None or d <= until)]
    status = dates_status(ds, days, units, until)
    if status is None:
        complete = bool(days) and len(cols) == len(days)
        return {'cols': cols, 'complete': complete, 'status': None, 'missing': []}
    return {'cols': cols, 'complete': status['status'] == 'Complete', 'status': status['status'], 'missing': status['missing']}


def week_columns(ds: Dataset, first: int, last: int, units=None) -> tuple[list[int], bool]:
    """Columns of the reported dates in a week and whether it is Complete (see week_status)."""
    info = week_status(ds, first, last, units)
    return info['cols'], info['complete']


def summary(ds: Dataset, selection: Selection, day: date) -> dict:
    rows = np.flatnonzero(scope_mask(ds, selection))
    column = ds.position(day)
    daily = ds.outage[rows, column]
    reported = ~np.isnan(daily)
    mtd_cols, mtd_missing = mtd_positions(ds, day)
    mtd_block = ds.outage[np.ix_(rows, mtd_cols)]
    mtd_outage, mtd_site_days = _window(mtd_block)
    daily_outage = float(np.nansum(daily))
    buckets = bucket_counts(bucket_ids(site_uptime(mtd_block)))
    in_scope = len(rows)
    base = base_mask(ds, selection)
    mtd_dates = [ds.dates[c] for c in mtd_cols]
    nsla = nsla_count(*nsla_dates(ds, rows, mtd_dates, scope=selection.scope))
    usd = unique_sites_down(*usd_dates(ds, rows, mtd_dates, scope=selection.scope))
    on_air_flag, om_flag = ds.sites['on_air'].to_numpy(dtype=bool), ds.sites['om_start'].to_numpy(dtype=bool)

    return {
        'reporting_date': day.isoformat(),
        'mtd_window': {
            'start': ds.dates[0].isoformat(),
            'end': day.isoformat(),
            'days_reported': len(mtd_cols),
            'days_missing': [d.isoformat() for d in mtd_missing],
        },
        'metrics': {
            'sites_total': int(base.sum()),
            # On-Air = Yes and O&M Start = Yes on the same site (blank or 0 is "not recorded", not a failure).
            'sites_converted': int((base & ds.sites['on_air'].to_numpy(dtype=bool) & ds.sites['om_start'].to_numpy(dtype=bool)).sum()),
            'sites_in_scope': in_scope,
            'sites_reported': int(reported.sum()),
            'sites_missing': int((~reported).sum()),
            'coverage_pct': round(100.0 * reported.sum() / in_scope, 2) if in_scope else None,
            'daily_uptime_pct': uptime_pct(daily_outage, int(reported.sum())),
            'daily_outage_minutes': round(daily_outage, 2),
            'sites_without_outage': int((daily[reported] == 0).sum()),
            'sites_down_full_day': int((daily[reported] >= MINUTES_PER_DAY).sum()),
            'mtd_uptime_pct': uptime_pct(mtd_outage, mtd_site_days),
            'mtd_outage_minutes': round(mtd_outage, 2),
            'sites_below_60_mtd': buckets['lt_60'],
            'sites_at_or_above_98_5_mtd': buckets['gte_98_5'],
            # Sites with an MTD uptime value: the denominator of the MTD threshold shares (as in Threshold Analysis).
            'sites_with_mtd_value': sum(buckets.values()),
            # SLA = 98.5% MTD uptime: sites with a value below it.
            'sites_not_meeting_sla_mtd': sum(buckets.values()) - buckets['gte_98_5'],
            'out_of_range_values': int((reported & ((daily < 0) | (daily > MINUTES_PER_DAY))).sum()),
            # NSLA / USD month to date (approved rule B-3, nsla_mask / usd_mask) over the selected population, from each
            # site's effective date; None when none of its sites reported.
            'nsla_sites_mtd': nsla['count'],
            'nsla_eligible_sites': nsla['eligible_sites'],
            'usd_sites_mtd': usd['count'],
        },
        # Status counts of the selection's dashboard sites (Consolidation Matrix flags in the reporting month), whatever
        # the population: a status breakdown, not a population metric. sites_total / sites_converted above are the same
        # status counts (kept for compatibility); the population's site count is sites_in_scope.
        'status_counts': {'label': 'Status counts (all dashboard sites of the selection; not a population figure)',
                          'total': int(base.sum()), 'on_air': int((base & on_air_flag).sum()), 'om_start': int((base & om_flag).sum()),
                          'on_air_and_om_start': int((base & on_air_flag & om_flag).sum())},
        'previous_month_conversion': previous_month_conversion(ds, base),
        'outage_comparison': outage_comparison(ds, selection, day, daily_outage if reported.any() else None,
                                               outage_total(mtd_block), [ds.dates[c] for c in mtd_cols]),
    }


def _outage_change(current: float | None, previous: float | None, period: str, previous_period: str, note: str = '') -> dict:
    """Outage minutes against the previous comparable period. No direction or % without both values (or from 0)."""
    diff = None if current is None or previous is None else round(current - previous, 2)
    return {
        'current': current, 'previous': previous, 'period': period, 'previous_period': previous_period,
        'change_pct': round(100.0 * diff / previous, 1) if diff is not None and previous else None,
        # Fewer outage minutes is an improvement.
        'direction': None if diff is None else 'same' if abs(diff) < 0.005 else 'down' if diff < 0 else 'up',
        'note': note if diff is None else '',
    }


def outage_comparison(ds: Dataset, selection: Selection, day: date, daily: float | None, mtd: float | None,
                      mtd_dates: list[date]) -> dict:
    """Day: the previous calendar day. MTD: the same elapsed dates of the previous month, only when every one of them is
    reported. Month: the previous full month, only once the reporting month is complete. Earlier months come from the
    source's daily and monthly columns (period_summary); nothing is estimated."""
    fmt = lambda d: d.strftime('%d %b')  # noqa: E731
    prev_day = day - timedelta(days=1)
    p = period_summary(ds, selection, dates=[prev_day], label='')
    # A previous period counts only when sites of this selection reported in it (sites_reported), not other projects.
    out = {'day': _outage_change(daily, p['outage_minutes'] if p['sites_reported'] else None, fmt(day), fmt(prev_day),
                                 f'No data on {fmt(day)}.' if daily is None else f'No data on {fmt(prev_day)}.')}
    prev_last = ds.dates[0] - timedelta(days=1)
    prev_dates = [prev_last.replace(day=d.day) for d in mtd_dates if d.day <= prev_last.day]
    p = period_summary(ds, selection, dates=prev_dates, label='') if prev_dates else None
    complete = bool(p) and p['sites_reported'] > 0 and len(prev_dates) == len(mtd_dates) and p['days_reported'] == len(prev_dates)
    span = f'{fmt(mtd_dates[0])} – {fmt(mtd_dates[-1])}' if mtd_dates else ''
    out['mtd'] = _outage_change(mtd, p['outage_minutes'] if complete else None, span,
                         f'{fmt(prev_dates[0])} – {fmt(prev_dates[-1])}' if prev_dates else prev_last.strftime('%b'),
                         'No data in this month to date.' if mtd is None else f'{prev_last:%B} has no data for every one of these dates.')
    month_done = day.day == calendar.monthrange(day.year, day.month)[1] and len(mtd_dates) == day.day
    p = period_summary(ds, selection, month_keys=[prev_last.strftime('%Y-%m')], label='')
    out['month'] = _outage_change(mtd if month_done else None, p['outage_minutes'] if p['months'] and p['sites_reported'] else None, f'{day:%b %Y}', f'{prev_last:%b %Y}',
                           f'{day:%B} is not complete yet.' if not month_done else f'No data for {prev_last:%B}.')
    return out


def previous_month_conversion(ds: Dataset, base: np.ndarray) -> dict | None:
    """Sites converted with the previous month's O&M Start flag. On-Air has no history, so the current flag is used.

    None when the source has no O&M Start column for the previous month; nothing is estimated.
    """
    if ds.previous_om_label is None or 'om_start_previous' not in ds.sites:
        return None
    on_air = ds.sites['on_air'].to_numpy(dtype=bool)
    return {
        'label': ds.previous_om_label,
        'sites_converted': int((base & on_air & ds.sites['om_start_previous'].to_numpy(dtype=bool)).sum()),
    }


def circle_rows(ds: Dataset, rows: np.ndarray) -> dict[str, np.ndarray]:
    """Site rows per circle series, keyed "<report type>|<circle>" (MP 4G and MP LWE are separate networks)."""
    keys = ds.sites['report_type'].to_numpy()[rows].astype(str) + '|' + ds.sites['circle'].to_numpy()[rows].astype(str)
    return {str(key): rows[keys == key] for key in sorted(set(keys))}


def circle_list(c_rows: dict[str, np.ndarray]) -> list[dict]:
    return [{'key': key, 'report_type': key.split('|', 1)[0], 'circle': key.split('|', 1)[1], 'sites': len(r)}
            for key, r in c_rows.items()]


def trend(ds: Dataset, selection: Selection, start: date, end: date) -> dict:
    rows = np.flatnonzero(scope_mask(ds, selection))
    types = [selection.report_type] if selection.report_type else sorted(ds.sites['report_type'].unique())
    type_rows = {t: rows[(ds.sites['report_type'].to_numpy()[rows] == t)] for t in types}
    # Circle series use the same formula over each circle's own sites; a circle without data on a day is None.
    c_rows = circle_rows(ds, rows)

    points = []
    current = start
    while current <= end:
        column = ds.position(current)
        point = {'date': current.isoformat(), 'reported': False, 'sites_in_scope': len(rows),
                 'sites_reported': 0, 'coverage_pct': None, 'outage_minutes': None,
                 'uptime_pct': None, 'by_report_type': {t: None for t in types},
                 'outage_by_report_type': {t: None for t in types},
                 'by_circle': {k: None for k in c_rows}, 'outage_by_circle': {k: None for k in c_rows}}
        if column is not None and current in ds.reported_dates:
            values = ds.outage[rows, column]
            outage, site_days = _window(values)
            point.update(
                reported=True,
                sites_reported=site_days,
                coverage_pct=round(100.0 * site_days / len(rows), 2) if len(rows) else None,
                outage_minutes=round(outage, 2),
                uptime_pct=uptime_pct(outage, site_days),
                by_report_type={t: uptime_pct(*_window(ds.outage[r, column])) for t, r in type_rows.items()},
                outage_by_report_type={t: outage_total(ds.outage[r, column]) for t, r in type_rows.items()},
                by_circle={k: uptime_pct(*_window(ds.outage[r, column])) for k, r in c_rows.items()},
                outage_by_circle={k: outage_total(ds.outage[r, column]) for k, r in c_rows.items()},
            )
        points.append(point)
        current += timedelta(days=1)

    return {'series': points, 'report_types': types, 'weeks': weekly(ds, rows, type_rows, c_rows), 'circles': circle_list(c_rows)}


def weekly(ds: Dataset, rows: np.ndarray, type_rows: dict[str, np.ndarray] | None = None,
           c_rows: dict[str, np.ndarray] | None = None) -> list[dict]:
    """Uptime for the workbook's week ranges (days 1-7, 8-14, 15-21, 22-end), reported days only. Each week has
    ``status`` Complete / Provisional (week_status) and its ``missing`` unit-days; a Provisional week shows its figures.

    Daily values exist only for the workbook's reporting month, so weeks of earlier
    months cannot be compared. ``change_pts`` is the difference from the previous
    week that has data, in percentage points.
    """
    month_end = ds.dates[-1].day
    weeks = []
    previous = None
    units = units_of_rows(ds, rows)
    for label, first, last in WEEKS:
        last = min(last, month_end)
        info = week_status(ds, first, last, units)
        cols, complete = info['cols'], info['complete']  # a Provisional week shows the figures it has
        block = ds.outage[np.ix_(rows, cols)]
        value = uptime_pct(*_window(block))
        weeks.append({
            'label': label,
            'start': ds.dates[0].replace(day=first).isoformat(),
            'end': ds.dates[0].replace(day=last).isoformat(),
            'days_in_week': last - first + 1,
            'days_reported': len(cols),
            'complete': complete,
            'status': info['status'],
            'missing': info['missing'],
            'uptime_pct': value,
            'change_pts': _change(value, previous),
            'by_report_type': {
                t: uptime_pct(*_window(ds.outage[np.ix_(r, cols)])) for t, r in (type_rows or {}).items()
            },
            'outage_minutes': outage_total(block),
            'outage_by_report_type': {t: outage_total(ds.outage[np.ix_(r, cols)]) for t, r in (type_rows or {}).items()},
            'by_circle': {k: uptime_pct(*_window(ds.outage[np.ix_(r, cols)])) for k, r in (c_rows or {}).items()},
            'outage_by_circle': {k: outage_total(ds.outage[np.ix_(r, cols)]) for k, r in (c_rows or {}).items()},
        })
        if value is not None:
            previous = value
    return weeks


def same_days_previous_month(ds: Dataset, day: date) -> tuple[dict, np.ndarray | None]:
    """The previous month's days 1..N (N = the reporting date's day), for comparison with the MTD.

    Returns (description, outage[n_sites, days] or None). The block is None when the
    workbook has no daily columns for that month; months are never estimated from totals.
    """
    previous = (ds.dates[0] - timedelta(days=1)).replace(day=1)
    key, label = previous.strftime('%Y-%m'), previous.strftime('%b-%y')
    entry = next((h for h in ds.daily_history if h['key'] == key), None)
    meta = {'key': key, 'label': label, 'available': False, 'start': None, 'end': None, 'days_reported': 0}
    if entry is None:
        return meta, None
    cols = [i for i, d in enumerate(entry['dates']) if d.day <= day.day and not np.isnan(entry['outage'][:, i]).all()]
    if not cols:
        return meta, None
    end = previous.replace(day=min(day.day, calendar.monthrange(previous.year, previous.month)[1]))
    meta.update(available=True, start=previous.isoformat(), end=end.isoformat(), days_reported=len(cols))
    return meta, entry['outage'][:, cols]


def breakdown(ds: Dataset, selection: Selection, day: date) -> dict:
    rows = np.flatnonzero(scope_mask(ds, selection))
    comparison, previous_block = same_days_previous_month(ds, day)
    column = ds.position(day)
    mtd_cols, _ = mtd_positions(ds, day)
    sites = ds.sites.iloc[rows]
    site_buckets = bucket_ids(site_uptime(ds.outage[np.ix_(rows, mtd_cols)]))
    # Each site's uptime on the selected day, bucketed with the same thresholds.
    day_buckets = bucket_ids(site_uptime(ds.outage[rows, column][:, None]))

    circles = []
    for (report_type, circle), group in sites.groupby(['report_type', 'circle'], sort=True):
        positions = np.searchsorted(rows, group.index.to_numpy())
        group_rows = rows[positions]
        daily = ds.outage[group_rows, column]
        reported = int((~np.isnan(daily)).sum())
        mtd_block = ds.outage[np.ix_(group_rows, mtd_cols)]
        mtd = uptime_pct(*_window(mtd_block))
        previous = uptime_pct(*_window(previous_block[group_rows])) if previous_block is not None else None
        circles.append({
            'report_type': report_type,
            'circle': circle,
            'sites_in_scope': len(group_rows),
            **team_counts(group),
            'sites_reported': reported,
            'daily_uptime_pct': uptime_pct(float(np.nansum(daily)), reported),
            'mtd_uptime_pct': mtd,
            # Same days of the previous month (e.g. 1-14 Sep against 1-14 Oct); None without daily data.
            'previous_uptime_pct': previous,
            'mtd_change_pts': _change(mtd, previous),
            # Outage minutes over the same windows; None when nothing was reported (never zero).
            'mtd_outage_minutes': outage_total(mtd_block),
            'previous_outage_minutes': outage_total(previous_block[group_rows]) if previous_block is not None else None,
            'buckets': bucket_counts(site_buckets[positions]),
            'daily_buckets': bucket_counts(day_buckets[positions]),
        })

    return {
        'reporting_date': day.isoformat(),
        'mtd_window': {'start': ds.dates[0].isoformat(), 'end': day.isoformat(), 'days_reported': len(mtd_cols)},
        'comparison': comparison,
        'circles': circles,
        # Distinct people over several circles: someone named in two circles counts once, so these are not sums of the rows.
        'team_totals': {
            'all': team_counts(sites),
            **{report_type: team_counts(frame) for report_type, frame in sites.groupby('report_type', sort=True)},
        },
        'buckets': [
            {'id': bucket_id, 'label': label, 'workbook_label': workbook_label, 'count': count}
            for (bucket_id, label, workbook_label, _), count
            in zip(BUCKETS, bucket_counts(site_buckets).values())
        ],
        'daily_buckets': [
            {'id': bucket_id, 'label': label, 'workbook_label': workbook_label, 'count': count}
            for (bucket_id, label, workbook_label, _), count
            in zip(BUCKETS, bucket_counts(day_buckets).values())
        ],
    }


# Thresholds on the Threshold Analysis page: the top and bottom uptime buckets above.
THRESHOLDS = ('gte_98_5', 'lt_60')
# Penalty threshold: the buckets entirely below 98.5% (from BUCKETS, not redefined). Their sum is the
# "Below 98.5% - Total" aggregate; it is not a sixth bucket and never part of a grand total.
PENALTY_THRESHOLD = 98.5
PENALTY_BUCKETS = tuple(b for i, (b, *_rest) in enumerate(BUCKETS) if i + 1 < len(BUCKETS) and BUCKETS[i + 1][3] <= PENALTY_THRESHOLD)
BELOW_PENALTY = 'below_98_5'
NO_VALUE = 'no_value'
COMPARED = (*BUCKET_IDS, BELOW_PENALTY, NO_VALUE)
KIND_ORDER = {'mtd': 0, 'month': 1, 'week': 2, 'day': 3}
HISTORY_MONTHS = 7


def _share(count: int, population: int) -> dict:
    return {'count': count, 'pct': round(100.0 * count / population, 2) if population else None}


def bucket_values(period_ids: np.ndarray, uptime: np.ndarray, positions: np.ndarray) -> dict | None:
    """Counts and shares (of all sites in ``positions``) per bucket, the below-98.5% aggregate and the sites
    with no value; ``None`` when no site reported in the period (never zeros)."""
    reported = int((~np.isnan(uptime[positions])).sum())
    if not reported:
        return None
    population = len(positions)
    counts = {b: int((period_ids[positions] == b).sum()) for b in BUCKET_IDS}
    return {
        'sites_reported': reported,
        **{b: _share(n, population) for b, n in counts.items()},
        BELOW_PENALTY: _share(sum(counts[b] for b in PENALTY_BUCKETS), population),
        NO_VALUE: _share(population - reported, population),
    }


def compare_values(now: dict | None, before: dict | None) -> dict:
    """Change between two periods per bucket, aggregate and no-value; ``None`` where either is missing."""
    out = {}
    for key in COMPARED:
        if not now or not before:
            out[key] = None
            continue
        a, b = now[key], before[key]
        change = a['count'] - b['count']
        out[key] = {
            'count': a['count'], 'pct': a['pct'], 'compare_count': b['count'], 'compare_pct': b['pct'], 'change': change,
            'change_pct': round(100.0 * change / b['count'], 1) if b['count'] else None,
            'change_pts': round(a['pct'] - b['pct'], 2) if a['pct'] is not None and b['pct'] is not None else None,
        }
    return out


def resolve_periods(periods: list[dict], total_values: dict, period: str | None, compare: str | None) -> dict:
    """The selectable periods (with reported data; MTD, months, weeks, dates; latest first within a kind), the
    selected one (default MTD) and its comparison: ``compare`` if valid, none for "none", otherwise the natural
    one (the previous date, week or month; for MTD the latest earlier month)."""
    order = sorted(((p, i) for i, p in enumerate(periods) if total_values.get(p['key'])),
                   key=lambda pi: (KIND_ORDER[pi[0]['kind']], -pi[1]))
    choices = [p for p, _ in order]
    keys = [p['key'] for p in choices]
    selected = next((p for p in choices if p['key'] == period), None) or next((p for p in choices if p['kind'] == 'mtd'), None) \
        or (choices[0] if choices else None)
    vs = None
    if selected and compare != 'none':
        if compare and compare != selected['key'] and compare in keys:
            vs = compare
        else:
            kind = 'month' if selected['kind'] == 'mtd' else selected['kind']
            vs = next((p['key'] for p in choices if p['kind'] == kind and p['key'] != selected['key'] and p['start'] < selected['start']), None)
    return {'choices': keys, 'period': selected['key'] if selected else None, 'compare': vs}


def threshold_analysis(ds: Dataset, selection: Selection, day: date, period: str | None = None,
                       compare: str | None = None) -> dict:
    """Sites in each uptime bucket (all five; the page highlights <60% and >=98.5%), per circle and period.

    Mirrors the workbook's "All Circle - 98.5" and "All Circle - Below 60" sheets. A site's
    uptime for a period uses the standard formula over the days it reported (not-reported
    days are excluded, unlike the workbook, which counts them as 100%); thresholds are the
    workbook bucket edges (``bucket_ids``). Percentages are of all sites in scope, the
    workbook's denominator. A circle or period without any reported value is ``None``,
    never zero.
    """
    rows = np.flatnonzero(scope_mask(ds, selection))
    periods: list[tuple[dict, np.ndarray]] = []
    eligible: dict[str, np.ndarray] = {}  # period key -> rows eligible in it (history months: their own effective dates)

    for i, month in enumerate(ds.months):
        m_outage, m_days, _down = month_values(ds, i, rows)
        uptime = _per_site_uptime(m_outage, m_days)
        key = month['start'].strftime('%Y-%m')
        member = np.isin(rows, month_scope_rows(ds, rows, selection.scope, month['start']))
        uptime = np.where(member, uptime, np.nan)
        eligible[key] = member
        end = month['start'] + timedelta(days=month['days'] - 1)
        periods.append((_period(key, month['label'], 'month', month['start'], end,
                                month['days'], month['days'], status=dates_status(ds, _month_dates(month['start']), units_of_rows(ds, rows))),
                        uptime))

    mtd_cols, _ = mtd_positions(ds, day)
    periods.append((_period('mtd', f'{ds.month_label} MTD', 'mtd', ds.dates[0], day,
                            (day - ds.dates[0]).days + 1, len(mtd_cols), partial=day < ds.dates[-1],
                            status=dates_status(ds, ds.dates, units_of_rows(ds, rows), day)),
                    site_uptime(ds.outage[np.ix_(rows, mtd_cols)])))

    month_end = ds.dates[-1].day
    units = units_of_rows(ds, rows)
    for number, (label, first, last) in enumerate(WEEKS, start=1):
        start, end = ds.dates[0].replace(day=first), ds.dates[0].replace(day=min(last, month_end))
        # A Provisional week (in progress or with missing unit-days) shows the figures it has up to the reporting date;
        # Complete only when it has ended and every day is covered (approved rule B-4).
        info = week_status(ds, first, last, units, until=day)
        cols = info['cols']
        uptime = site_uptime(ds.outage[np.ix_(rows, cols)]) if cols else np.full(len(rows), np.nan)
        periods.append((_period(f'w{number}', f'Wk-{number}', 'week', start, end, (end - start).days + 1, len(cols),
                                partial=not (info['complete'] and end <= day), status=info),
                        uptime))

    for d in ds.reported_dates:
        if d <= day:
            column = ds.position(d)
            periods.append((_period(d.isoformat(), d.strftime('%d %b'), 'day', d, d, 1, 1, status=dates_status(ds, [d], units)),
                            site_uptime(ds.outage[rows, column][:, None])))

    ids = [bucket_ids(uptime) for _, uptime in periods]
    sites = ds.sites.iloc[rows]

    def summarise(positions: np.ndarray, report_type, circle) -> dict:
        values = {p['key']: bucket_values(period_ids, uptime, positions if p['key'] not in eligible else positions[eligible[p['key']][positions]])
                  for (p, uptime), period_ids in zip(periods, ids)}
        return {'report_type': report_type, 'circle': circle, 'sites_in_scope': len(positions), 'values': values}

    groups = [
        summarise(np.searchsorted(rows, frame.index.to_numpy()), report_type, circle)
        for (report_type, circle), frame in sites.groupby(['report_type', 'circle'], sort=True)
    ]
    total = summarise(np.arange(len(rows)), None, None)
    period_list = [p for p, _ in periods]
    chosen = resolve_periods(period_list, total['values'], period, compare)
    for row in (*groups, total):
        row['comparison'] = compare_values(row['values'].get(chosen['period']), row['values'].get(chosen['compare'])) \
            if chosen['period'] and chosen['compare'] else None
    return {
        'reporting_date': day.isoformat(),
        'thresholds': [{'id': b, 'label': label, 'workbook_label': wb} for b, label, wb, _ in BUCKETS if b in THRESHOLDS],
        # All five buckets with their bounds: lower bound inclusive, upper exclusive (workbook Bucket formula).
        'buckets': [
            {'id': b, 'label': label, 'workbook_label': wb, 'lower': lower, 'upper': BUCKETS[i + 1][3] if i + 1 < len(BUCKETS) else None}
            for i, (b, label, wb, lower) in enumerate(BUCKETS)
        ],
        'periods': period_list,
        'rows': groups,
        'total': total,
        # The period shown and its comparison (resolved here, so every change below uses the same two periods).
        'selection': chosen,
        'penalty': {'id': BELOW_PENALTY, 'label': 'Below 98.5% — Total', 'threshold': PENALTY_THRESHOLD, 'buckets': list(PENALTY_BUCKETS)},
        'monthly_comparison': _monthly_comparison(ds, rows, day, period_list, total),
    }


def _monthly_comparison(ds: Dataset, rows: np.ndarray, day: date, periods: list[dict], total: dict) -> dict:
    """Columns for the monthly comparison table: the latest full months with data (from the source's monthly
    totals), the previous month's same elapsed days (its daily columns) and the current month to date. A column
    the source cannot provide has status "missing" and a reason, never estimated values."""
    def column(key, label, kind, start, end, values, reason=None):
        return {'key': key, 'label': label, 'kind': kind, 'start': start, 'end': end, 'sites_in_scope': len(rows),
                'status': 'available' if values else 'missing', 'reason': None if values else reason, 'values': values}

    months = [p for p in periods if p['kind'] == 'month' and total['values'].get(p['key'])][-HISTORY_MONTHS:]
    columns = [column(p['key'], p['label'], 'month', p['start'], p['end'], total['values'][p['key']]) for p in months]
    meta, block = same_days_previous_month(ds, day)
    start = date.fromisoformat(f"{meta['key']}-01")
    end = start.replace(day=min(day.day, calendar.monthrange(start.year, start.month)[1]))
    values = None
    if meta['available'] and block is not None:
        uptime = site_uptime(block[rows])
        values = bucket_values(bucket_ids(uptime), uptime, np.arange(len(rows)))
    columns.append(column(f"{meta['key']}-mtd", f"{meta['label']} MTD", 'previous_mtd', start.isoformat(), end.isoformat(), values,
                          f"{meta['label']} has no daily data in the source for days 1–{day.day}, so its MTD cannot be computed."))
    mtd = next((p for p in periods if p['kind'] == 'mtd'), None)
    if mtd:
        columns.append(column('mtd', mtd['label'], 'mtd', mtd['start'], day.isoformat(), total['values'].get('mtd'),
                              'No site reported in the month to date.'))
    # Month to date against the previous month's same elapsed days (same scope and denominator); every entry is
    # None when the previous month has no daily data for those days (never the full month in its place).
    current = next((c for c in columns if c['kind'] == 'mtd'), None)
    before = next((c for c in columns if c['kind'] == 'previous_mtd'), None)
    mtd_comparison = compare_values(current['values'] if current else None, before['values'] if before else None)
    return {'elapsed_days': day.day, 'columns': columns,
            'mtd_comparison': {'current': current['key'] if current else None, 'previous': before['key'] if before else None,
                               'available': bool(current and before and current['values'] and before['values']),
                               # Sites with a value in each period: when they differ (e.g. a project without daily data
                               # for the previous month), the comparison covers different reporting populations.
                               'sites_reported': {'current': current['values']['sites_reported'] if current and current['values'] else None,
                                                  'previous': before['values']['sites_reported'] if before and before['values'] else None},
                               'values': mtd_comparison}}


def _period(key: str, label: str, kind: str, start: date, end: date, days: int, days_reported: int,
            partial: bool = False, status: dict | None = None) -> dict:
    """``partial``: the period is still in progress on the reporting date (MTD, current week). ``status``: Complete /
    Provisional with the missing unit-days (None: the source has no coverage information)."""
    return {'key': key, 'label': label, 'kind': kind, 'start': start.isoformat(), 'end': end.isoformat(),
            'days': days, 'days_reported': days_reported, 'partial': partial,
            'status': status['status'] if status else None, 'missing': status['missing'] if status else []}


def _month_dates(month: date) -> list[date]:
    return [month.replace(day=d) for d in range(1, calendar.monthrange(month.year, month.month)[1] + 1)]


def period_summary(ds: Dataset, selection: Selection, *, dates: list[date] | None = None,
                   month_keys: list[str] | None = None, label: str) -> dict:
    """Uptime, outage and threshold counts for a chosen trend period (KPI card).

    The period is either reporting dates (a range, picked days or weeks) or months
    ('YYYY-MM' keys; the current month's key means its days so far). Dates may also fall
    in an earlier month whose daily columns are in the workbook (``daily_history``), so a
    month to date can be compared with the same days of that month. Uptime pools all
    outage minutes over all site-days reported in the period; each site's own uptime over
    the period decides its bucket, as everywhere else.
    """
    # The population of the period: the sites effective at its end (population_eligible); a history-only period uses the
    # status effective then. Values before a site's effective date are left out (the dataset variant / population_view).
    base_rows = np.flatnonzero(base_mask(ds, selection))
    rows = population_rows(ds, base_rows, selection.scope, _period_dates(ds, dates, month_keys))
    view = population_view(ds, selection.scope)
    outage = np.zeros(len(rows))
    site_days = np.zeros(len(rows))
    down = np.zeros(len(rows), dtype=bool)  # outage > 0 on at least one reported day of the period
    current_key = ds.dates[0].strftime('%Y-%m')
    cols: list[int] = []
    months_used = 0
    if month_keys is not None:
        for i, month in enumerate(ds.months):
            if month['start'].strftime('%Y-%m') in month_keys:
                m_outage, m_days, m_down = month_values(view, i, rows)
                outage += m_outage
                site_days += m_days
                down |= m_down
                months_used += bool((m_days > 0).any())
        if current_key in month_keys:
            cols = [ds.position(d) for d in ds.reported_dates]
    else:
        cols = [ds.position(d) for d in sorted(set(dates or [])) if d in ds.reported_dates]
    blocks = [view.outage[np.ix_(rows, cols)]] if cols else []
    reported_dates = [ds.dates[c] for c in cols]
    if month_keys is None and dates:
        # Earlier months' daily columns: a day counts once any site reported on it.
        wanted = set(dates)
        for entry in view.daily_history:
            idx = [i for i, d in enumerate(entry['dates']) if d in wanted and not np.isnan(entry['outage'][:, i]).all()]
            if idx:
                blocks.append(entry['outage'][np.ix_(rows, idx)])
                reported_dates += [entry['dates'][i] for i in idx]
    for block in blocks:
        outage += np.nansum(block, axis=1)
        site_days += (~np.isnan(block)).sum(axis=1)
        down |= usd_mask(block)  # a missing value is neither down nor up
    if cols:
        months_used += month_keys is not None
    reported_dates.sort()

    with np.errstate(invalid='ignore', divide='ignore'):
        site_uptime_pct = np.where(site_days > 0, 100.0 * (1.0 - outage / (MINUTES_PER_DAY * site_days)), np.nan)
    ids = bucket_ids(site_uptime_pct)
    in_population = np.ones(len(rows), dtype=bool)
    return {
        'label': label,
        'kind': 'months' if month_keys is not None else 'dates',
        'days_reported': len(reported_dates),
        'months': months_used if month_keys is not None else None,
        'first_date': reported_dates[0].isoformat() if reported_dates else None,
        'last_date': reported_dates[-1].isoformat() if reported_dates else None,
        'sites_in_scope': len(rows),
        'sites_reported': int((site_days > 0).sum()),
        'uptime_pct': uptime_pct(float(outage.sum()), int(site_days.sum())),
        'outage_minutes': round(float(outage.sum()), 2),
        'sites_below_60': int((ids == 'lt_60').sum()),
        'sites_at_or_above_98_5': int((ids == 'gte_98_5').sum()),
        # Every bucket, by each site's own uptime over the period (sites without a value are in none).
        'buckets': bucket_counts(ids),
        # USD / NSLA (approved rule B-3) over the selected population of the period, from each site's effective date.
        'unique_sites_down': unique_sites_down(in_population, site_days > 0, down),
        'nsla_sites': _period_nsla(ds, rows, dates, month_keys, selection.scope),
        'definitions': {'unique_sites_down': usd_rule(selection.scope), 'nsla_sites': nsla_rule(selection.scope)},
    }


def _period_dates(ds: Dataset, dates, month_keys) -> list[date]:
    """Dates whose latest is the end of a trend period (for its population): the picked dates, or the months' starts."""
    if month_keys is None:
        return sorted(set(dates or []))
    out = [m['start'] for m in ds.months if m['start'].strftime('%Y-%m') in month_keys]
    if ds.dates and ds.dates[0].strftime('%Y-%m') in month_keys:
        out.append(ds.dates[0])
    return out


def _period_nsla(ds: Dataset, rows: np.ndarray, dates, month_keys, scope: str) -> dict:
    if month_keys is not None:
        history = [i for i, m in enumerate(ds.months) if m['start'].strftime('%Y-%m') in month_keys]
        current = ds.dates[0].strftime('%Y-%m') in month_keys
        if len(history) == 1 and not current:
            return {**nsla_count(*nsla_month(ds, rows, history[0], scope=scope)), 'rule': nsla_rule(scope)}
        dates = [d for i in history for d in _month_dates(ds.months[i]['start'])] + (list(ds.reported_dates) if current else [])
    return {**nsla_count(*nsla_dates(ds, rows, dates or [], scope=scope)), 'rule': nsla_rule(scope)}


def unique_sites_down(eligible: np.ndarray, reported: np.ndarray, usd: np.ndarray) -> dict:
    """USD count of a population (per-site rule usd_mask; usd_dates / usd_month): distinct sites of the population with
    outage > 0 on at least one reported day of their effective period, each site once (a row is one site of one
    project, so 4G and LWE sites never merge). ``eligible_sites``: every site of the population, with or without values;
    ``count`` None when none of them reported (missing data is never zero)."""
    eligible = np.asarray(eligible, dtype=bool)
    total, with_values = int(eligible.sum()), int((np.asarray(reported, dtype=bool) & eligible).sum())
    count = int((np.asarray(usd, dtype=bool) & eligible).sum()) if with_values else None
    return {'count': count, 'eligible_sites': total, 'sites_reported': with_values,
            'pct': round(100.0 * count / total, 2) if total and count is not None else None}


def month_options(ds: Dataset) -> list[dict]:
    """Months that can be selected for the trend, oldest first; keys are 'YYYY-MM'."""
    options = [{'key': m['start'].strftime('%Y-%m'), 'label': m['label']} for m in ds.months]
    options.append({'key': ds.dates[0].strftime('%Y-%m'), 'label': f'{ds.month_label} MTD'})
    return options


def monthly(ds: Dataset, selection: Selection, day: date, keys: set[str] | None = None) -> dict:
    """Monthly uptime from the workbook's monthly outage columns, plus the current month to date.

    ``uptime_pct`` excludes sites with a blank month (not reported). The workbook's
    Summ sheet instead counts blanks as zero outage over all sites in scope; that
    figure is returned as ``uptime_pct_blank_as_zero`` so the two can be compared.
    Scope flags are the current ones. ``overall`` pools every month shown into one
    figure for the whole period. ``keys`` ('YYYY-MM') restricts the months shown; the
    change is then measured against the previous month shown.
    """
    rows = np.flatnonzero(scope_mask(ds, selection))
    types = [selection.report_type] if selection.report_type else sorted(ds.sites['report_type'].unique())
    site_types = ds.sites['report_type'].to_numpy()
    type_rows = {t: rows[site_types[rows] == t] for t in types}
    totals = {t: [0.0, 0] for t in [None, *types]}  # outage minutes, site-days
    c_rows = circle_rows(ds, rows)
    units = units_of_rows(ds, np.flatnonzero(base_mask(ds, selection)))
    final = finalizations()

    def month_uptime(values: np.ndarray, days: int) -> float | None:
        """Like measure(), without adding to the period totals (circle series)."""
        return uptime_pct(float(np.nansum(values)), int((~np.isnan(values)).sum()) * (days if values.ndim == 1 else 1))

    def history(i: int, r: np.ndarray, key=False) -> float | None:
        """A history month of ``r`` from month_values (daily records where available); adds to the totals of ``key``."""
        m_outage, m_days, _down = month_values(ds, i, r)
        outage, site_days = float(m_outage.sum()), int(m_days.sum())
        if key is not False:
            totals[key][0] += outage
            totals[key][1] += site_days
        return uptime_pct(outage, site_days)

    def history_outage(i: int, r: np.ndarray) -> float | None:
        m_outage, m_days, _down = month_values(ds, i, r)
        return round(float(m_outage.sum()), 2) if (m_days > 0).any() else None

    def measure(values: np.ndarray, days: int, key) -> float | None:
        """values: [sites] month totals, or [sites, days] daily values for the current month."""
        outage = float(np.nansum(values))
        site_days = int((~np.isnan(values)).sum()) * (days if values.ndim == 1 else 1)
        totals[key][0] += outage
        totals[key][1] += site_days
        return uptime_pct(outage, site_days)

    months = []
    previous = None
    for i, month in enumerate(ds.months):
        key = month['start'].strftime('%Y-%m')
        if keys is not None and key not in keys:
            continue
        # The month's own population: sites eligible in it by their effective dates (approved rule B-5).
        m_rows = month_scope_rows(ds, rows, selection.scope, month['start'])
        m_types = {t: r[np.isin(r, m_rows)] for t, r in type_rows.items()}
        m_circles = {k: r[np.isin(r, m_rows)] for k, r in c_rows.items()}
        m_outage, m_days, _down = month_values(ds, i, m_rows)
        reported = int((m_days > 0).sum())
        value = history(i, m_rows, None)
        months.append({
            'key': key,
            'label': month['label'],
            'start': month['start'].isoformat(),
            'days': month['days'],
            'partial': False,
            'sites_in_scope': len(m_rows),
            'sites_reported': reported,
            'uptime_pct': value,
            'uptime_pct_blank_as_zero': uptime_pct(float(m_outage.sum()), len(m_rows) * month['days']) if reported else None,
            'change_pts': _change(value, previous),
            'by_report_type': {t: history(i, r, t) for t, r in m_types.items()},
            'outage_minutes': history_outage(i, m_rows),
            'outage_by_report_type': {t: history_outage(i, r) for t, r in m_types.items()},
            'by_circle': {k: history(i, r) for k, r in m_circles.items()},
            'outage_by_circle': {k: history_outage(i, r) for k, r in m_circles.items()},
            **month_status(ds, month['start'], units, day, final),
        })
        if value is not None:
            previous = value

    current_key = ds.dates[0].strftime('%Y-%m')
    if keys is None or current_key in keys:
        mtd_cols, _ = mtd_positions(ds, day)
        block = ds.outage[np.ix_(rows, mtd_cols)]
        value = measure(block, len(mtd_cols), None)
        months.append({
            'key': current_key,
            'label': f'{ds.month_label} MTD',
            'start': ds.dates[0].isoformat(),
            'days': len(mtd_cols),
            'partial': True,
            'sites_in_scope': len(rows),
            'sites_reported': int((~np.isnan(block)).any(axis=1).sum()),
            'uptime_pct': value,
            'uptime_pct_blank_as_zero': uptime_pct(float(np.nansum(block)), len(rows) * len(mtd_cols)) if block.size and not np.isnan(block).all() else None,
            'change_pts': _change(value, previous),
            'by_report_type': {t: measure(ds.outage[np.ix_(r, mtd_cols)], len(mtd_cols), t) for t, r in type_rows.items()},
            'outage_minutes': outage_total(block),
            'outage_by_report_type': {t: outage_total(ds.outage[np.ix_(r, mtd_cols)]) for t, r in type_rows.items()},
            'by_circle': {k: month_uptime(ds.outage[np.ix_(r, mtd_cols)], len(mtd_cols)) for k, r in c_rows.items()},
            'outage_by_circle': {k: outage_total(ds.outage[np.ix_(r, mtd_cols)]) for k, r in c_rows.items()},
            **month_status(ds, ds.dates[0], units, day, final),
        })

    with_data = [m for m in months if m['uptime_pct'] is not None]
    overall = {
        'start': with_data[0]['start'] if with_data else None,
        'end': _month_end(with_data[-1], day).isoformat() if with_data else day.isoformat(),
        'months': len(with_data),
        'uptime_pct': uptime_pct(*totals[None]),
        'by_report_type': {t: uptime_pct(*totals[t]) for t in types},
    }
    return {'reporting_date': day.isoformat(), 'report_types': types, 'months': months, 'overall': overall, 'circles': circle_list(c_rows)}


FINALIZATION_LABELS = {'complete': 'Complete', 'incomplete_missing_data': 'Incomplete — Missing Data'}


def finalizations() -> dict[date, str]:
    """{month: status} of the finalized months that are not reopened (sitedata.MonthFinalization)."""
    try:
        from apps.sitedata.models import MonthFinalization
        return dict(MonthFinalization.objects.filter(reopened_at__isnull=True).values_list('month', 'status'))
    except Exception:  # noqa: BLE001 - no database (pure calculations): no finalization information
        return {}


def month_status(ds: Dataset, month: date, units=None, until: date | None = None, final: dict | None = None) -> dict:
    """Status fields of a month entry: 'status' Complete / Provisional (every day of the month ended and covered,
    approved rule B-4; None without coverage information) and its missing unit-days; when the month is finalized and
    not reopened, 'finalization_status' ('complete' / 'incomplete_missing_data') and its label."""
    month = month.replace(day=1)
    status = dates_status(ds, _month_dates(month), units, until if month == ds.dates[0] else None)
    final = finalizations() if final is None else final
    state = final.get(month)
    return {'status': status['status'] if status else None, 'missing': status['missing'] if status else [],
            'finalization_status': state, 'finalization_label': FINALIZATION_LABELS.get(state) if state else None}


def _month_end(month: dict, day: date) -> date:
    """Last day a month entry covers: the reporting date for the current month to date."""
    return day if month['partial'] else date.fromisoformat(month['start']) + timedelta(days=month['days'] - 1)


def _change(value: float | None, previous: float | None) -> float | None:
    return None if value is None or previous is None else round(value - previous, 2)


TEAM_COLUMNS = {'ci': 'ci_name', 'ie': 'ie_name'}
UNASSIGNED = {'', '-', '0'}
UNASSIGNED_LABEL = 'Unassigned'


def team_counts(sites: pd.DataFrame) -> dict:
    """Distinct CIs and IEs named on these sites, and the sites with no CI / IE.

    Names are compared ignoring case and repeated spaces, so "A Kumar" and "a  kumar" are
    one person. Unassigned (blank, "-", "0") is not a person.
    """
    result = {}
    for key, column in (('ci', 'ci_name'), ('ie', 'ie_name')):
        names = team_names(sites[column])
        assigned = names[names != UNASSIGNED_LABEL]
        result[f'{key}_count'] = int(assigned.str.casefold().str.replace(r'\s+', ' ', regex=True).nunique())
        result[f'sites_without_{key}'] = int(len(names) - len(assigned))
    return result


def team_names(values: pd.Series) -> pd.Series:
    """CI / IE names as shown in the application; blank, "-" or "0" become "Unassigned"."""
    names = values.fillna('').astype(str).str.strip()
    return names.where(~names.isin(UNASSIGNED), UNASSIGNED_LABEL)


def team_performance(ds: Dataset, selection: Selection, day: date, group: str) -> dict:
    """Uptime per CI or IE (from the CI Name / IE Name columns), worst MTD first.

    A team is one name within one report type and circle. Each site belongs to the
    CI and IE named on its row, which is how responsibility is assigned.
    """
    rows = np.flatnonzero(scope_mask(ds, selection))
    column = ds.position(day)
    mtd_cols, _ = mtd_positions(ds, day)
    sites = ds.sites.iloc[rows].copy()
    sites['team'] = team_names(sites[TEAM_COLUMNS[group]])
    other = 'ie_name' if group == 'ci' else 'ci_name'
    sites['other'] = team_names(sites[other])
    site_mtd = site_uptime(ds.outage[np.ix_(rows, mtd_cols)])
    site_bucket = bucket_ids(site_mtd)

    teams = []
    for (report_type, circle, name), group_frame in sites.groupby(['report_type', 'circle', 'team'], sort=True):
        positions = np.searchsorted(rows, group_frame.index.to_numpy())
        group_rows = rows[positions]
        daily = ds.outage[group_rows, column]
        reported = int((~np.isnan(daily)).sum())
        mtd_block = ds.outage[np.ix_(group_rows, mtd_cols)]
        linked = sorted(set(group_frame['other']) - {UNASSIGNED_LABEL})
        teams.append({
            'report_type': report_type,
            'circle': circle,
            'name': name,
            'sites_in_scope': len(group_rows),
            'daily_uptime_pct': uptime_pct(float(np.nansum(daily)), reported),
            'daily_outage_minutes': round(float(np.nansum(daily)), 2),
            'mtd_uptime_pct': uptime_pct(*_window(mtd_block)),
            'mtd_outage_minutes': round(float(np.nansum(mtd_block)), 2),
            'sites_below_60_mtd': int((comparable(site_mtd[positions]) < 60).sum()),
            'buckets': bucket_counts(site_bucket[positions]),
            # For a CI: the IEs under it; for an IE: the CI(s) it reports to.
            'linked_names': linked,
        })
    teams.sort(key=lambda t: (t['mtd_uptime_pct'] is None, t['mtd_uptime_pct'] or 0))
    below = comparable(site_mtd) < 60
    unassigned = (sites['team'] == UNASSIGNED_LABEL).to_numpy()
    return {
        'reporting_date': day.isoformat(),
        'group': group,
        'totals': {
            # Distinct people: a CI or IE covering two circles has two rows but counts once.
            'teams': len({t['name'] for t in teams} - {UNASSIGNED_LABEL}),
            'teams_with_sites_below_60': len({t['name'] for t in teams if t['sites_below_60_mtd']} - {UNASSIGNED_LABEL}),
            'sites_in_scope': len(rows),
            'sites_below_60_mtd': int(below.sum()),
            'unassigned_sites': int(unassigned.sum()),
            'unassigned_sites_below_60_mtd': int((below & unassigned).sum()),
        },
        'teams': teams,
    }


# Fields the CI & IE Performance page cannot show from the source, with the reason (reported, never estimated).
CI_IE_UNSUPPORTED = (
    {'field': 'RCA-wise columns (PTPL Battery, PTPL OFC, PTPL Technical, PTPL Other, BSNL OFC, BSNL Media, '
              'BSNL Link, BSNL Other)',
     'reason': "The Up-Time Report has no RCA per site and month, the CI's / IE's Performance sheets have no RCA "
               'columns, and the RCA register does not use these PTPL / BSNL categories.'},
)


def _nsla_values(result: tuple[np.ndarray, np.ndarray, np.ndarray], positions: np.ndarray) -> dict | None:
    """NSLA sites (nsla_mask: sites of the selected population whose period uptime is below 98.5%) among ``positions``;
    ``population`` = the population's sites among them in the period, the denominator of ``nsla_pct``; ``None`` when
    none of them reported."""
    eligible, uptime, mask = (a[positions] for a in result)
    reported = int((eligible & ~np.isnan(uptime)).sum())
    if not reported:
        return None
    population = int(eligible.sum())
    nsla = int(mask.sum())
    return {'sites_reported': reported, 'nsla_sites': nsla, 'population': population,
            'nsla_pct': round(100.0 * nsla / population, 2) if population else None,
            'no_value': population - reported}


def team_monthly_nsla(ds: Dataset, selection: Selection, day: date, group: str, month: str | None = None) -> dict:
    """NSLA (nsla_mask: sites of the selected population whose period uptime is below 98.5%) per CI or IE for a
    reporting month and the months before it.

    People come from the CI Name / IE Name on each site's row, as on Team Performance. Each month's NSLA population is
    the selection's population in that month (matrix effective date), counted from the effective date; history months use their
    reported days (daily records), the current month its reported days up to ``day`` (month to date). A month without
    any reported value is left out; a person with no value in a month gets ``None`` there, never zero. Rows are in
    name order (then project and circle): there is no ranking.
    """
    rows = np.flatnonzero(scope_mask(ds, selection))
    periods: list[tuple[dict, tuple]] = []
    for i, entry in enumerate(ds.months):
        result = nsla_month(ds, rows, i, scope=selection.scope)
        if np.isnan(result[1]).all():
            continue
        end = entry['start'] + timedelta(days=entry['days'] - 1)
        periods.append(({'key': entry['start'].strftime('%Y-%m'), 'label': entry['label'], 'kind': 'month',
                         'start': entry['start'].isoformat(), 'end': end.isoformat()}, result))
    mtd_cols, _ = mtd_positions(ds, day)
    mtd = nsla_dates(ds, rows, [ds.dates[c] for c in mtd_cols], scope=selection.scope)
    if mtd_cols and not np.isnan(mtd[1]).all():
        periods.append(({'key': ds.dates[0].strftime('%Y-%m'), 'label': f'{ds.month_label} MTD', 'kind': 'mtd',
                         'start': ds.dates[0].isoformat(), 'end': day.isoformat()}, mtd))

    keys = [p['key'] for p, _ in periods]
    if month and month not in keys:
        raise ValueError(f"No data for month {month}. Months with data: {', '.join(keys) or 'none'}.")
    selected = keys.index(month) if month else len(keys) - 1
    shown = periods[max(0, selected - HISTORY_MONTHS + 1):selected + 1] if periods else []

    sites = ds.sites.iloc[rows].copy()
    sites['team'] = team_names(sites[TEAM_COLUMNS[group]])
    people = []
    for (report_type, circle, name), frame in sites.groupby(['report_type', 'circle', 'team'], sort=False):
        positions = np.searchsorted(rows, frame.index.to_numpy())
        people.append({
            'report_type': report_type, 'circle': circle, 'name': name, 'sites_in_scope': len(positions),
            'months': {p['key']: _nsla_values(result, positions) for p, result in shown},
        })
    # Unassigned sites last; otherwise by name, then project and circle (a person covering two circles has two rows).
    people.sort(key=lambda p: (p['name'] == UNASSIGNED_LABEL, p['name'].casefold(), p['report_type'], p['circle']))
    everyone = np.arange(len(rows))
    return {
        'group': group,
        'reporting_date': day.isoformat(),
        'months_available': [p for p, _ in periods],
        'reporting_month': keys[selected] if periods else None,
        # Oldest first; the last is the reporting month.
        'months': [p for p, _ in shown],
        'totals': {'people': len({p['name'] for p in people} - {UNASSIGNED_LABEL}), 'sites_in_scope': len(rows),
                   'months': {p['key']: _nsla_values(result, everyone) for p, result in shown}},
        'rows': people,
        'unsupported': list(CI_IE_UNSUPPORTED),
    }


# Circle-wise ranking safeguards: a person is ranked only with enough assigned sites, every one of them reported in
# the period; a circle names a top performer only when at least two people are eligible to compare.
RANK_MIN_SITES = 10
RANK_MIN_PEOPLE = 2


def _rank_people(rows: list[dict], key: str, assignments: dict[str, list[str]]) -> dict:
    """Ranking of one group (CI or IE) within one project and circle: lowest NSLA % first, equal shares tied
    (competition ranking: 1, 1, 3). Ineligible people are listed after, unranked, with the reason."""
    people = []
    for row in rows:
        value = row['months'].get(key)
        if row['name'] == UNASSIGNED_LABEL:
            reason = 'Sites without a named person are not ranked.'
        elif value is None:
            reason = 'No assigned site reported in the period.'
        elif value['no_value']:
            reason = f"Incomplete: {value['no_value']} of {value.get('population', row['sites_in_scope'])} assigned sites of the population have no value."
        elif value.get('population', row['sites_in_scope']) < RANK_MIN_SITES:
            reason = f'Fewer than {RANK_MIN_SITES} assigned sites; too small to compare fairly.'
        else:
            reason = None
        other = [a for a in assignments.get(row['name'], []) if a != f"{row['circle']} {row['report_type']}"]
        people.append({
            'name': row['name'], 'sites_in_scope': row['sites_in_scope'],
            'sites_reported': value['sites_reported'] if value else 0,
            'nsla_sites': value['nsla_sites'] if value else None,
            'nsla_pct': value['nsla_pct'] if value else None,
            'nsla_population': value.get('population', row['sites_in_scope']) if value else None,
            'eligible': reason is None, 'reason': reason, 'rank': None,
            # The same person's assignments elsewhere (each is ranked in its own circle and project).
            'other_assignments': None if row['name'] == UNASSIGNED_LABEL else other,
        })
    eligible = [p for p in people if p['eligible']]
    # Exact shares (cross-multiplied counts), so rounding never creates or breaks a tie.
    share = {id(p): Fraction(p['nsla_sites'], p['nsla_population']) for p in eligible}
    eligible.sort(key=lambda p: (share[id(p)], p['name'].casefold()))
    for i, p in enumerate(eligible):
        p['rank'] = eligible[i - 1]['rank'] if i and share[id(p)] == share[id(eligible[i - 1])] else i + 1
    others = sorted((p for p in people if not p['eligible']), key=lambda p: p['name'].casefold())
    top = [p['name'] for p in eligible if p['rank'] == 1] if len(eligible) >= RANK_MIN_PEOPLE else []
    if not people:
        status = 'none'
    elif len(eligible) < RANK_MIN_PEOPLE:
        status = 'insufficient'
    else:
        status = 'tie' if len(top) > 1 else 'ranked'
    return {
        'status': status,
        'reason': None if status in ('ranked', 'tie') else (
            'No one is assigned here.' if status == 'none' else
            f'{len(eligible)} of {len(people)} eligible; at least {RANK_MIN_PEOPLE} are needed to compare.'),
        'top': top, 'people_total': len(people), 'people_eligible': len(eligible),
        'ranking': eligible + others,
    }


def _pooled_nsla(values: list[dict | None], population: int | None = None) -> dict | None:
    """NSLA of a whole circle or project from its people's values (every site has exactly one CI row); the population
    is the selected population's sites of those values."""
    present = [v for v in values if v]
    reported = sum(v['sites_reported'] for v in present)
    if not reported:
        return None
    nsla = sum(v['nsla_sites'] for v in present)
    population = sum(v['population'] for v in present) if all('population' in v for v in present) else (population or 0)
    return {'sites_reported': reported, 'nsla_sites': nsla, 'population': population,
            'nsla_pct': round(100.0 * nsla / population, 2) if population else None, 'no_value': population - reported}


def _rank_circles(circles: list[dict], key: str) -> None:
    """Rank circles within each project by the reporting month's NSLA share (lower is better, ties share a rank,
    as the workbook's circle-wise NSLA sheet). A circle without a value in that month is not ranked."""
    for report_type in {c['report_type'] for c in circles}:
        valued = [c for c in circles if c['report_type'] == report_type and c['nsla'].get(key)]
        share = {id(c): Fraction(c['nsla'][key]['nsla_sites'], c['nsla'][key].get('population', c['sites_in_scope']))
                 for c in valued if c['nsla'][key].get('population', c['sites_in_scope'])}
        valued = [c for c in valued if id(c) in share]
        valued.sort(key=lambda c: (share[id(c)], c['circle']))
        for i, c in enumerate(valued):
            c['nsla_rank'] = valued[i - 1]['nsla_rank'] if i and share[id(c)] == share[id(valued[i - 1])] else i + 1


def circle_top_performers(ds: Dataset, selection: Selection, day: date, month: str | None = None) -> dict:
    """Best CI and best IE within each project and circle for a reporting month, by the lowest NSLA %.

    Builds on ``team_monthly_nsla`` (same scope, NSLA definition and month), so the figures match the
    CI & IE Performance page. CIs and IEs are ranked separately; circles and projects are never compared
    with each other.
    """
    groups = {g: team_monthly_nsla(ds, selection, day, g, month) for g in ('ci', 'ie')}
    key = groups['ci']['reporting_month']
    circles = []
    if key:
        by_circle: dict[tuple[str, str], dict[str, list[dict]]] = {}
        assignments: dict[str, dict[str, list[str]]] = {}
        for g, result in groups.items():
            assignments[g] = {}
            for row in result['rows']:
                by_circle.setdefault((row['report_type'], row['circle']), {'ci': [], 'ie': []})[g].append(row)
                assignments[g].setdefault(row['name'], []).append(f"{row['circle']} {row['report_type']}")
        for (report_type, circle), rows in sorted(by_circle.items(), key=lambda item: (item[0][1], item[0][0])):
            scope = sum(r['sites_in_scope'] for r in rows['ci'])
            circles.append({'report_type': report_type, 'circle': circle, 'sites_in_scope': scope,
                            # Circle-wise NSLA per month (the workbook's "NSLA Sites" sheet), from the same values.
                            'nsla': {m['key']: _pooled_nsla([r['months'].get(m['key']) for r in rows['ci']], scope)
                                     for m in groups['ci']['months']},
                            'nsla_rank': None,
                            'ci': _rank_people(rows['ci'], key, assignments['ci']),
                            'ie': _rank_people(rows['ie'], key, assignments['ie'])})
        _rank_circles(circles, key)
    month_info = next((m for m in groups['ci']['months'] if m['key'] == key), None)
    previous_mtd = _circle_previous_mtd(ds, selection, day, circles) if month_info and month_info['kind'] == 'mtd' else None
    return {
        'reporting_date': day.isoformat(),
        'months_available': groups['ci']['months_available'],
        'reporting_month': key,
        'month': month_info,
        # Monthly columns, oldest first; the last is the reporting month.
        'months': groups['ci']['months'],
        # The previous month's same elapsed days (e.g. Sep-26 MTD beside Oct-26 MTD); only for a month to date.
        'previous_mtd': previous_mtd,
        'rules': {'min_sites': RANK_MIN_SITES, 'min_people': RANK_MIN_PEOPLE, 'nsla_threshold_pct': PENALTY_THRESHOLD,
                  'nsla_rule': nsla_rule(selection.scope)},
        'circles': circles,
        'projects': [{'report_type': t, 'sites_in_scope': sum(c['sites_in_scope'] for c in circles if c['report_type'] == t),
                      'nsla': {m['key']: _pooled_nsla([c['nsla'][m['key']] for c in circles if c['report_type'] == t],
                                                      sum(c['sites_in_scope'] for c in circles if c['report_type'] == t))
                               for m in [*groups['ci']['months'], *([previous_mtd] if previous_mtd else [])]}}
                     for t in sorted({c['report_type'] for c in circles})],
    }


def _circle_previous_mtd(ds: Dataset, selection: Selection, day: date, circles: list[dict]) -> dict:
    """NSLA per circle over the previous month's days 1..N (N = the reporting date's day), from that month's daily
    columns, added to each circle's ``nsla`` under the column key. A circle without daily data there gets None
    (never the full month in its place); the column says why when no circle has data."""
    meta, block = same_days_previous_month(ds, day)
    key = f"{meta['key']}-mtd"
    rows = np.flatnonzero(scope_mask(ds, selection))
    previous = (ds.dates[0] - timedelta(days=1)).replace(day=1)
    dates = [previous.replace(day=d) for d in range(1, min(day.day, calendar.monthrange(previous.year, previous.month)[1]) + 1)]
    result = nsla_dates(ds, rows, dates, scope=selection.scope) if block is not None else (np.zeros(len(rows), dtype=bool), np.full(len(rows), np.nan), np.zeros(len(rows), dtype=bool))
    sites = ds.sites.iloc[rows]
    types, names = sites['report_type'].to_numpy(), sites['circle'].to_numpy()
    for c in circles:
        positions = np.flatnonzero((types == c['report_type']) & (names == c['circle']))
        c['nsla'][key] = _nsla_values(result, positions)
    available = any(c['nsla'][key] for c in circles)
    return {'key': key, 'label': f"{meta['label']} MTD", 'kind': 'previous_mtd', 'start': meta['start'], 'end': meta['end'],
            'available': available,
            'reason': None if available else f"{meta['label']} has no daily data in the source for days 1–{day.day}."}


def filter_team(table: pd.DataFrame, ci_name: str = '', ie_name: str = '') -> pd.DataFrame:
    if ci_name:
        table = table[table['ci_name'] == ci_name]
    if ie_name:
        table = table[table['ie_name'] == ie_name]
    return table


def site_table(ds: Dataset, selection: Selection, day: date) -> pd.DataFrame:
    """Per-site rows for the detail table, restricted to the selection's scope."""
    rows = np.flatnonzero(scope_mask(ds, selection))
    mtd_cols, _ = mtd_positions(ds, day)
    outage = ds.outage[rows, ds.position(day)]
    mtd = site_uptime(ds.outage[np.ix_(rows, mtd_cols)])
    table = ds.sites.iloc[rows][[
        'site_id', 'site_name', 'report_type', 'circle', 'oa', 'ba', 'on_air', 'om_start', 'eb',
    ]].copy()
    table['ie_name'] = team_names(ds.sites['ie_name'].iloc[rows])
    table['ci_name'] = team_names(ds.sites['ci_name'].iloc[rows])
    table['outage_minutes'] = outage
    table['daily_uptime_pct'] = 100.0 * (1.0 - outage / MINUTES_PER_DAY)
    table['mtd_uptime_pct'] = mtd
    table['bucket'] = bucket_ids(mtd)
    # Each site's bucket on the selected day alone (Threshold Analysis drill-down).
    table['daily_bucket'] = bucket_ids(site_uptime(outage[:, None]))
    # NSLA month to date (nsla_mask: a site of the selected population whose MTD uptime from its effective date is below
    # 98.5%).
    table['nsla'] = nsla_dates(ds, rows, [ds.dates[c] for c in mtd_cols], scope=selection.scope)[2]
    return table


def search_sites(table: pd.DataFrame, search: str = '', bucket: str | None = None,
                 bucket_basis: str = 'mtd') -> pd.DataFrame:
    if search:
        needle = search.casefold()
        hay = table[['site_id', 'site_name', 'oa', 'ba', 'ie_name', 'ci_name']].apply(lambda col: col.str.casefold())
        table = table[hay.apply(lambda col: col.str.contains(needle, regex=False)).any(axis=1)]
    if bucket:
        table = table[table['bucket' if bucket_basis == 'mtd' else 'daily_bucket'] == bucket]
    return table


def sort_sites(table: pd.DataFrame, field: str, descending: bool) -> pd.DataFrame:
    # Secondary key keeps pagination stable when the primary key has ties.
    keys = [field, 'site_id'] if field != 'site_id' else ['site_id']
    return table.sort_values(keys, ascending=[not descending, True][:len(keys)], na_position='last', kind='stable')


def site_detail(ds: Dataset, index: int, day: date) -> dict:
    site = ds.sites.iloc[index]
    values = ds.outage[index]
    mtd_cols, _ = mtd_positions(ds, day)
    mtd = site_uptime(ds.outage[[index]][:, mtd_cols])[0]
    return {
        'site': {
            'site_id': site['site_id'],
            'site_name': site['site_name'],
            'report_type': site['report_type'],
            'circle': site['circle'],
            'circle_as_in_workbook': site['circle_raw'],
            'oa': site['oa'],
            'ba': site['ba'],
            'eb': site['eb'],
            'on_air': bool(site['on_air']),
            'om_start': bool(site['om_start']),
            'ie_name': team_names(pd.Series([site['ie_name']])).iloc[0],
            'ci_name': team_names(pd.Series([site['ci_name']])).iloc[0],
            'source_row': int(site['source_row']),
        },
        'reporting_date': day.isoformat(),
        'mtd_uptime_pct': None if np.isnan(mtd) else round(float(mtd), 4),
        'mtd_bucket': bucket_ids(np.array([mtd]))[0],
        'daily': [
            {
                'date': d.isoformat(),
                'reported': d in ds.reported_dates and not np.isnan(values[i]),
                'outage_minutes': None if np.isnan(values[i]) else round(float(values[i]), 2),
                'uptime_pct': None if np.isnan(values[i]) else round(100.0 * (1 - values[i] / MINUTES_PER_DAY), 4),
            }
            for i, d in enumerate(ds.dates)
        ],
    }


def filter_options(ds: Dataset) -> dict:
    sites = ds.sites
    latest = ds.latest_date
    first_reported = ds.reported_dates[0] if ds.reported_dates else None
    circles = (
        sites.groupby('circle')['report_type']
        .agg(lambda s: sorted(s.unique()))
        .to_dict()
    )
    counts = sites['circle'].value_counts().to_dict()
    return {
        'report_types': [
            {'value': t, 'label': t, 'site_count': int((sites['report_type'] == t).sum())}
            for t in sorted(sites['report_type'].unique())
        ],
        'circles': [
            {'value': c, 'label': c, 'report_types': circles[c], 'site_count': int(counts[c])}
            for c in sorted(circles)
        ],
        'scopes': [
            {'value': key, 'label': label, 'available': key != 'om_start' or ds.has_om_start}
            for key, label in SCOPES.items()
        ],
        'default_scope': DEFAULT_SCOPE,
        'buckets': [{'id': b, 'label': label, 'workbook_label': wb} for b, label, wb, _ in BUCKETS],
        'reporting_dates': [d.isoformat() for d in ds.reported_dates],
        'default_date': latest.isoformat() if latest else None,
        'months': month_options(ds),
        # Earlier months with daily columns in the workbook (for same-days comparisons).
        'daily_history': [
            {'key': h['key'], 'label': h['label'],
             'dates': [d.isoformat() for i, d in enumerate(h['dates']) if not np.isnan(h['outage'][:, i]).all()]}
            for h in ds.daily_history
        ],
        'default_trend_range': {
            'start': first_reported.isoformat() if first_reported else None,
            'end': latest.isoformat() if latest else None,
        },
        'month': {
            'label': ds.month_label,
            'start': ds.dates[0].isoformat(),
            'end': ds.dates[-1].isoformat(),
        },
    }


SEVERITY_RANK = {'critical': 0, 'warning': 1, 'info': 2}
# Short titles for workbook validation warnings shown as header alerts.
WARNING_TITLES = {
    'outage_out_of_range': '{count} daily outage values outside 0–1,440 minutes',
    'missing_dates': '{count} reporting dates missing before the latest date',
    'partial_dates': 'Some sites not reported on {count} dates',
    'duplicate_site': '{count} duplicate site rows in the workbook',
    'non_numeric_outage': '{count} non-numeric daily outage values',
    'formula_not_cached': '{count} formula cells have no calculated value',
    'outage_formula_not_cached': '{count} daily outage cells are uncalculated formulas',
    'month_total_mismatch': '{count} sites where the month total differs from the daily values',
    'blank_site_id': '{count} rows without a site ID were skipped',
    'unknown_project': '{count} rows with an unknown Project were skipped',
    'om_start_missing': 'O&M Start column missing; that scope is unavailable',
}


def missing_submission_alerts(ds: Dataset, pairs=None) -> list[dict]:
    """Approved rule B-7: one warning per reporting unit (technology + circle) active on the data layer's latest
    reporting date, within ``pairs`` (None: every unit), whose unit-day is not covered (no data at all, or below the
    coverage threshold), from the dataset's coverage table (apps.sitedata.reporting.date_status). Nothing when the
    source has no coverage information."""
    if not ds.unit_coverage:
        return []
    from apps.sitedata import reporting
    day = status_end(ds)
    if day is None:
        return []
    entries = ds.unit_coverage.get(day, {})
    units = {u for u in entries if pairs is None or u in pairs}
    missing = set(reporting.date_status(ds.unit_coverage, day, units)['missing_units'])
    items = []
    for (technology, circle) in sorted(units):
        if f'{technology} {circle}' not in missing:
            continue
        v = entries[(technology, circle)]
        detail = (f"No data received for {day:%d %b %Y}." if not v['with_data'] else
                  f"{v['with_data']:,} of {v['expected']:,} expected sites reported ({v['share']}%), below the coverage threshold of {v['threshold']}%.")
        items.append(_alert(f'missing_csv_{technology}_{circle}'.replace(' ', '_'), 'warning',
                            f'Missing CSV: {technology} {circle} {day.isoformat()}',
                            detail + ' Figures of this unit are Provisional; missing data is never counted as zero.', '/daily-ingestion'))
    return items


def alerts(ds: Dataset, today: date, pairs=None, scope: str = DEFAULT_SCOPE) -> list[dict]:
    """Operational and data-quality alerts for the latest reporting date, most important first.

    Uses only thresholds the workbook itself defines (60% bucket, a full day of outage)
    and facts about the data (age, coverage, validation warnings); nothing is invented.
    Operational alerts use the request's population (``scope``, default On-Air) across all report types; ``ds`` is that
    population's dataset variant. Missing-CSV alerts follow the reporting units (On-Air eligibility), not the population.
    """
    items: list[dict] = []
    latest = ds.latest_date
    pop = POPULATIONS.get(scope, 'sites')
    if latest:
        selection = Selection(None, None, scope)
        result = summary(ds, selection, latest)
        m = result['metrics']
        day = latest.strftime('%d %b')
        start = date.fromisoformat(result['mtd_window']['start']).strftime('%d %b')

        from .crosscheck import calculation_check  # imports this module

        # Listed first: if the figures disagree with the workbook, every other alert is in doubt.
        check = calculation_check(ds)
        if check['difference_count']:
            worst = check['differences'][0]
            unit = (lambda v: f'{v:,.0f}') if worst['unit'] == 'sites' else (lambda v: f'{v:.2f}%')
            items.append(_alert(
                'calculation_mismatch', 'critical',
                f"{check['difference_count']} workbook figure{'s differ' if check['difference_count'] > 1 else ' differs'}"
                " from the dashboard's calculation",
                f"Largest: {worst['sheet']}!{worst['cell']} {worst['description']}: workbook "
                f"{unit(worst['workbook'])}, dashboard {unit(worst['dashboard'])}.",
                '/data-source#calculation-check',
            ))
        if m['sites_down_full_day']:
            items.append(_alert(
                'sites_down_full_day', 'critical',
                f"{m['sites_down_full_day']:,} {pop} down all day on {day}",
                'Outage of 1,440 minutes or more on the latest reporting date.',
                f'/?date={latest.isoformat()}',
            ))
        if m['sites_below_60_mtd']:
            share = 100.0 * m['sites_below_60_mtd'] / m['sites_in_scope'] if m['sites_in_scope'] else 0
            items.append(_alert(
                'sites_below_60', 'critical',
                f"{m['sites_below_60_mtd']:,} {pop} below 60% uptime this month",
                f'{share:.1f}% of {pop}, month to date ({start}–{day}).',
                '/?bucket=lt_60',
            ))
        age = (today - latest).days
        if age > 1:
            items.append(_alert(
                'stale_data', 'warning',
                f'Latest data is from {day} ({age} days ago)',
                'Upload the newest consolidated workbook to bring the dashboard up to date.',
                '/workbook',
            ))
        if m['sites_missing']:
            items.append(_alert(
                'sites_not_reported', 'warning',
                f"{m['sites_missing']:,} {pop} not reported on {day}",
                f"Reporting coverage {m['coverage_pct']:.1f}%. Missing sites are excluded, not counted as 100%.",
                f'/?date={latest.isoformat()}',
            ))

    items += missing_submission_alerts(ds, pairs)

    for warning in ds.warnings:
        if warning['severity'] != 'warning':
            continue
        title = WARNING_TITLES.get(warning['code'], warning['message']).format(count=f"{warning['count']:,}")
        items.append(_alert(f"data_{warning['code']}", 'warning', title, warning['message'], '/data-source'))

    if latest:
        circles = [c for c in breakdown(ds, Selection(None, None, scope), latest)['circles']
                   if c['mtd_uptime_pct'] is not None]
        if len(circles) > 1:
            worst = min(circles, key=lambda c: c['mtd_uptime_pct'])
            kind = '4G' if worst['report_type'] == '4G Saturation' else worst['report_type']
            items.append(_alert(
                'lowest_circle', 'info',
                f"Lowest MTD uptime: {worst['circle']} · {kind} ({worst['mtd_uptime_pct']:.2f}%)",
                f"{worst['sites_in_scope']:,} {pop}, month to date.",
                f"/?report_type={worst['report_type'].replace(' ', '+')}&circle={worst['circle']}",
            ))

    items.sort(key=lambda a: SEVERITY_RANK[a['severity']])
    return items


def _alert(alert_id: str, severity: str, title: str, detail: str, link: str) -> dict:
    return {'id': alert_id, 'severity': severity, 'title': title, 'detail': detail, 'link': link}
