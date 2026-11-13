"""All KPI's: read-only calculations for the optional All KPI's module (see README.md in this folder).

Everything is computed from existing data through existing interfaces, without changing them:
- Sites and daily outage: the new data layer (``sitedata.dashboard_source``: Consolidation Matrix sites, the central
  daily table, complete continuous reporting dates), limited to the user's Dashboard project/circle pairs. Weekly and
  monthly figures are derived from the daily records.
- Population (request parameter ``scope``: on_air | om_start, default on_air; anything else is HTTP 400): every figure
  (site counts, availability, outage, buckets, USD, NSLA, trends, hierarchy, the site table and the filter options)
  counts exactly the selected population, day by day from each site's matrix effective date (never for days before it):
  a period's population is the sites effective on its last date. Without O&M Start dates in the matrix the O&M Start
  population is not available (never estimated). Every response carries the ``population`` block.
- Shared formulas reused as they are: ``metrics.uptime_pct`` (outage-weighted availability), ``metrics.bucket_ids``
  (threshold buckets), ``metrics.WEEKS``, ``metrics.team_names``; RCA: ``rca.services.filtered`` and the approved
  Final Bucket mapping ``rca.taxonomy.approved_final`` (the approved master, case and whitespace ignored).

USD and NSLA use the shared per-site rules of the dashboard (approved rule B-3, ``metrics.usd_dates`` / ``nsla_dates``)
over the selected population, exactly as the dashboard:
- USD Sites: distinct sites of the population with outage > 0 on at least one reported day of the period within their
  effective period.
- NSLA Sites: distinct sites of the population whose uptime over the period, pooled over their reported days from their
  effective date, is below 98.5% (exactly 98.5% does not qualify; one bad day does not, when the period uptime is >= 98.5%;
  a site without a value never does).
- A missing value is "not reported", never 0% or 0 minutes.
- ``on_air_sites`` / ``om_start_sites`` are status counts within the population (e.g. how many On-Air sites have started
  O&M), not populations of their own.
"""
from __future__ import annotations

import calendar
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd
from rest_framework.exceptions import ValidationError

from apps.dashboard import metrics
from apps.dashboard.metrics import BUCKET_IDS, BUCKETS, MINUTES_PER_DAY, WEEKS, bucket_ids, team_names, uptime_pct
from apps.dashboard.scope import restrict
from apps.dashboard.serializers import parse_scope
from apps.sitedata.identifiers import key_of as site_key

SEP = '::'  # separates the parts of a CI key (circle::CI) and an IE key (circle::CI::IE)
PAGE_SIZE = 50


@dataclass
class Selection:
    start: date
    end: date
    projects: set[str]
    circles: set[str]
    cis: set[str]
    ies: set[str]
    sites: set[str]
    buckets: set[str]
    final_buckets: set[str]


def _list(params, name: str) -> set[str]:
    return {v.strip() for v in (params.get(name) or '').split(',') if v.strip()}


def _date(value: str | None, name: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError({name: 'Give the date as YYYY-MM-DD.'}) from exc


def dataset(user, scope: str = metrics.DEFAULT_SCOPE):
    """The new layer's dataset of the population ``scope`` (its variant: values from each site's effective date) for the
    user's Dashboard pairs; the population of each day is applied in per_site."""
    from apps.accounts.access import pairs_for
    from apps.sitedata import dashboard_source
    return dashboard_source.dataset(pairs_for(user, 'dashboard', 'view'), scope)


def _scope(params) -> str:
    """The validated population of the request (default DEFAULT_SCOPE; invalid -> HTTP 400)."""
    return parse_scope(params.get('scope'))


def daily_columns(ds) -> dict[date, tuple[np.ndarray, int]]:
    """Every date with day-by-day data: (outage array of that month, column index). Current month and earlier months."""
    out = {}
    for entry in ds.daily_history:
        for i, d in enumerate(entry['dates']):
            if not np.isnan(entry['outage'][:, i]).all():
                out[d] = (entry['outage'], i)
    for d in ds.reported_dates:
        out[d] = (ds.outage, ds.position(d))
    return dict(sorted(out.items()))


def selection(params, ds) -> Selection:
    available = list(daily_columns(ds))
    start, end = _date(params.get('date_from'), 'date_from'), _date(params.get('date_to'), 'date_to')
    if available and not (start or end):  # default: the latest month with data, up to its latest date
        end = available[-1]
        start = end.replace(day=1)
    start, end = start or end, end or start
    if start and end and start > end:
        raise ValidationError({'date_from': 'The start date is after the end date.'})
    if start and end and (end - start).days > 370:
        raise ValidationError({'date_to': 'Choose at most about a year.'})
    return Selection(start, end, _list(params, 'project'), {c.upper() for c in _list(params, 'circle')}, _list(params, 'ci'), _list(params, 'ie'),
                     {s.upper() for s in _list(params, 'site')}, _list(params, 'bucket') & set(BUCKET_IDS), _list(params, 'final_bucket'))


def _ci_keys(sites: pd.DataFrame) -> pd.Series:
    return sites['circle'] + SEP + team_names(sites['ci_name'])


def _ie_keys(sites: pd.DataFrame) -> pd.Series:
    return _ci_keys(sites) + SEP + team_names(sites['ie_name'])


def site_rows(ds, sel: Selection, *, ignore: tuple[str, ...] = ()) -> np.ndarray:
    """Rows of the sites matching the site filters (project, circle, CI, IE, site), optionally ignoring some of them."""
    sites = ds.sites
    mask = np.ones(len(sites), dtype=bool)
    if sel.projects and 'project' not in ignore:
        mask &= sites['report_type'].isin(sel.projects).to_numpy()
    if sel.circles and 'circle' not in ignore:
        mask &= sites['circle'].isin(sel.circles).to_numpy()
    if sel.cis and 'ci' not in ignore:
        mask &= _ci_keys(sites).isin(sel.cis).to_numpy()
    if sel.ies and 'ie' not in ignore:
        mask &= _ie_keys(sites).isin(sel.ies).to_numpy()
    if sel.sites and 'site' not in ignore:
        mask &= sites['site_id'].str.upper().isin(sel.sites).to_numpy()
    return np.flatnonzero(mask)


def period_dates(ds, start: date, end: date) -> list[date]:
    return [d for d in daily_columns(ds) if start <= d <= end]


def outage_block(ds, rows: np.ndarray, dates: list[date]) -> np.ndarray:
    """Outage minutes [sites × dates] from the canonical daily records; NaN = not reported."""
    cols = daily_columns(ds)
    if not dates:
        return np.full((len(rows), 0), np.nan)
    return np.column_stack([cols[d][0][rows, cols[d][1]] for d in dates])


def _effective(sites: pd.DataFrame, column: str, dates: list[date], fallback: np.ndarray | None = None) -> np.ndarray:
    """[sites x dates]: True on the dates on or after the site's matrix date (``on_air_date`` / ``om_start_date``). A
    source without the date column uses ``fallback`` (the current flags) on every date, or False."""
    if column not in sites:
        flags = np.zeros(len(sites), dtype=bool) if fallback is None else np.asarray(fallback, dtype=bool)
        return np.repeat(flags[:, None], len(dates), axis=1)
    starts = sites[column].tolist()
    return np.array([[bool(s) and not pd.isna(s) and d >= s for d in dates] for s in starts], dtype=bool).reshape(len(sites), len(dates))


def per_site(ds, rows: np.ndarray, dates: list[date], scope: str = metrics.DEFAULT_SCOPE) -> pd.DataFrame:
    """One row per site of the population ``scope`` of the period (effective on its last date; no dates: the current
    population): its outage over the period from its effective date, reported days, USD / NSLA flags and its period
    availability. Sites outside the population are not rows."""
    rows = np.asarray(rows, dtype=int)
    sites = ds.sites.iloc[rows]
    all_values = outage_block(ds, rows, dates)
    current = metrics.population_flags(ds, scope)[rows]
    # The population day by day (Consolidation Matrix effective date of the selected population).
    pop_yes = _effective(sites, metrics.POPULATION_COLUMNS[scope][1], dates, current)
    member = pop_yes[:, -1] if len(dates) else current
    # Status flags on the last date (status counts within the population; never a population of their own).
    on_yes = _effective(sites, 'on_air_date', dates, sites['on_air'].to_numpy(dtype=bool))
    om_yes = _effective(sites, 'om_start_date', dates, sites['om_start'].to_numpy(dtype=bool))
    # USD / NSLA: the shared per-site rules over the population's values (metrics.usd_dates / nsla_dates).
    nsla = metrics.nsla_dates(ds, rows, dates, scope=scope)[2] & member
    usd = metrics.usd_dates(ds, rows, dates, scope=scope)[2] & member
    block = np.where(pop_yes, all_values, np.nan)  # a site's values before its effective date are left out
    reported = ~np.isnan(block)
    on_air = on_yes[:, -1] if len(dates) else sites['on_air'].to_numpy(dtype=bool)
    out_sum = np.where(reported, block, 0.0).sum(axis=1)
    days = reported.sum(axis=1)
    with np.errstate(invalid='ignore', divide='ignore'):
        site_avail = np.where(days > 0, 100.0 * (1.0 - out_sum / (MINUTES_PER_DAY * np.maximum(days, 1))), np.nan)
    om_known = bool(getattr(ds, 'has_om_start', False)) and 'om_start_date' in sites
    om_last = om_yes[:, -1] if len(dates) else np.zeros(len(rows), dtype=bool)
    table = pd.DataFrame({
        'row': rows, 'site_id': sites['site_id'].to_numpy(), 'site_name': sites['site_name'].to_numpy(),
        'project': sites['report_type'].to_numpy(), 'circle': sites['circle'].to_numpy(),
        'ci': team_names(sites['ci_name']).to_numpy(), 'ie': team_names(sites['ie_name']).to_numpy(), 'oa': sites['oa'].to_numpy(),
        # Expected days: the site's effective days of the period (days before its effective date are not expected).
        'on_air': on_air, 'outage': out_sum, 'days': days, 'expected_days': pop_yes.sum(axis=1), 'availability': site_avail,
        'bucket': bucket_ids(site_avail),
        # O&M Start on the last date of the period (None: the matrix has no O&M Start dates).
        'om_start': [bool(v) if om_known else None for v in om_last],
        'usd': usd, 'nsla': nsla,
    })
    return table[member].reset_index(drop=True)


def population_status(ds, scope: str, dates: list[date]) -> dict:
    """The ``population`` block of a period: {scope, label, available} (the O&M Start population needs the matrix O&M
    Start dates; never estimated)."""
    known = scope != 'om_start' or bool(getattr(ds, 'has_om_start', False))
    return {**metrics.population(scope), 'available': bool(dates) and known}


def om_status(ds, dates: list[date]) -> dict:
    """O&M Start availability for the period: from the matrix O&M Start dates (all months, or none)."""
    months = sorted({d.replace(day=1) for d in dates})
    known = bool(getattr(ds, 'has_om_start', False))
    missing = [] if known else months
    return {'months': [m.strftime('%Y-%m') for m in months], 'missing_months': [m.strftime('%b %Y') for m in missing],
            'available': bool(months) and known, 'complete': known}


def aggregate(table: pd.DataFrame, pop: dict) -> dict:
    """KPIs of a group of sites of the population (the whole selection, a circle, a CI, an IE): ``table`` holds only
    population sites (per_site)."""
    active = table
    outage = float(active['outage'].sum())
    site_days = int(active['days'].sum())
    expected = int(active['expected_days'].sum())
    valued = active[active['days'] > 0]
    counts = Counter(valued['bucket'])
    om_ok = pop['available']
    om_latest_known = table['om_start'].notna().any() if len(table) else False
    return {
        # The population's sites; on_air_sites / om_start_sites: status counts within it.
        'total_sites': int(len(table)), 'population_sites': int(len(table)), 'on_air_sites': int(table['on_air'].sum()),
        'om_start_sites': int((table['om_start'] == True).sum()) if om_latest_known else None,  # noqa: E712
        'availability_pct': uptime_pct(outage, site_days),
        'outage_minutes': round(outage, 2) if site_days else None, 'outage_hours': round(outage / 60, 2) if site_days else None,
        'usd_sites': int(table['usd'].sum()) if om_ok and site_days else None,
        'nsla_sites': int(table['nsla'].sum()) if om_ok and site_days else None,
        'above_98_5_sites': int(counts.get('gte_98_5', 0)), 'below_98_5_sites': int(len(valued) - counts.get('gte_98_5', 0)),
        'below_60_sites': int(counts.get('lt_60', 0)), 'sites_with_values': int(len(valued)),
        'buckets': {b: int(counts.get(b, 0)) for b in BUCKET_IDS},
        'missing_site_days': max(expected - site_days, 0), 'expected_site_days': expected, 'reported_site_days': site_days,
        'coverage_pct': round(100.0 * site_days / expected, 2) if expected else None,
        'sites_missing_any_day': int((active['days'] < active['expected_days']).sum()),
        'sites_without_any_value': int((active['days'] == 0).sum()),
    }


def _filtered_table(ds, sel: Selection, dates: list[date], scope: str = metrics.DEFAULT_SCOPE) -> pd.DataFrame:
    table = per_site(ds, site_rows(ds, sel), dates, scope)
    if sel.buckets:
        table = table[table['bucket'].isin(sel.buckets)]
    return table


def period_label(start: date, end: date) -> str:
    return start.strftime('%d %b %Y') if start == end else f'{start:%d %b %Y} – {end:%d %b %Y}'


def summary(params, user) -> dict:
    scope = _scope(params)
    ds = dataset(user, scope)
    sel = selection(params, ds)
    if sel.start is None:
        return {'period': None, 'current': None, 'previous': None, 'notes': ['No daily performance data is available.'],
                'population': metrics.population(scope)}
    dates = period_dates(ds, sel.start, sel.end)
    om = om_status(ds, dates)
    pop = population_status(ds, scope, dates)
    current = aggregate(_filtered_table(ds, sel, dates, scope), pop)
    # Comparison: the same number of days immediately before (only dates with data).
    span = (sel.end - sel.start).days + 1
    p_end, p_start = sel.start - timedelta(days=1), sel.start - timedelta(days=span)
    p_dates = period_dates(ds, p_start, p_end)
    p_om = om_status(ds, p_dates)
    previous = aggregate(_filtered_table(ds, sel, p_dates, scope), population_status(ds, scope, p_dates)) if p_dates else None
    return {
        'period': {'start': sel.start.isoformat(), 'end': sel.end.isoformat(), 'label': period_label(sel.start, sel.end), 'days_with_data': len(dates),
                   'days_in_period': span},
        'previous_period': {'start': p_start.isoformat(), 'end': p_end.isoformat(), 'label': period_label(p_start, p_end), 'days_with_data': len(p_dates)},
        'current': current, 'previous': previous, 'om_start': om, 'previous_om_start': p_om, 'population': pop,
        'definitions': {'usd_sites': metrics.usd_rule(scope), 'nsla_sites': metrics.nsla_rule(scope)},
        'pending': {
            'rca_ownership': 'Not configured: no approved mapping from Final Buckets to Own / Customer / Third Party / Pending.',
        },
    }


def _months_with_data(ds) -> list[date]:
    return sorted({d.replace(day=1) for d in daily_columns(ds)})


def trends(params, user) -> dict:
    scope = _scope(params)
    ds = dataset(user, scope)
    sel = selection(params, ds)
    granularity = params.get('granularity') or 'day'
    if granularity not in ('day', 'week', 'month'):
        raise ValidationError({'granularity': 'Choose day, week or month.'})
    if sel.start is None:
        return {'granularity': granularity, 'points': [], 'population': metrics.population(scope)}
    available = list(daily_columns(ds))
    # (key, label, dates with data, calendar dates of the period for its Complete / Provisional status)
    periods: list[tuple[str, str, list[date], list[date]]] = []
    if granularity == 'day':
        periods = [(d.isoformat(), d.strftime('%d %b'), [d], [d]) for d in period_dates(ds, sel.start, sel.end)]
    elif granularity == 'week':
        months = sorted({d.replace(day=1) for d in period_dates(ds, sel.start, sel.end)})
        for m in months:
            last = calendar.monthrange(m.year, m.month)[1]
            for name, first, end in WEEKS:
                days = [d for d in available if d.replace(day=1) == m and first <= d.day <= min(end, last) and sel.start <= d <= sel.end]
                if days:
                    week = [m.replace(day=n) for n in range(first, min(end, last) + 1)]
                    periods.append((f'{m:%Y-%m}-{name}', f'{name} {m:%b %Y}', days, week))
    else:  # every month with daily data (whole months; the latest may be month to date)
        for m in _months_with_data(ds):
            days = [d for d in available if d.replace(day=1) == m]
            last = calendar.monthrange(m.year, m.month)[1]
            periods.append((m.strftime('%Y-%m'), f'{m:%b %Y}' + ('' if len(days) == last else ' (MTD)'), days,
                            [m.replace(day=n) for n in range(1, last + 1)]))
    rows = site_rows(ds, sel)
    units = metrics.units_of_rows(ds, rows)
    points = []
    for key, label, days, calendar_days in periods:
        table = per_site(ds, rows, days, scope)  # the population of each period (effective on its last day)
        if sel.buckets:
            table = table[table['bucket'].isin(sel.buckets)]
        k = aggregate(table, population_status(ds, scope, days))
        # Approved rule B-4: a period is Complete only when it has ended and every day is covered for the selection's
        # reporting units; otherwise Provisional (its figures are shown). None without coverage information.
        status = metrics.dates_status(ds, calendar_days, units)
        points.append({'key': key, 'label': label, 'start': days[0].isoformat(), 'end': days[-1].isoformat(), 'days': len(days),
                       'status': status['status'] if status else None, 'missing': status['missing'] if status else [], **{
            f: k[f] for f in ('availability_pct', 'outage_minutes', 'outage_hours', 'usd_sites', 'nsla_sites', 'below_98_5_sites', 'below_60_sites',
                              'coverage_pct', 'missing_site_days', 'total_sites')}})
    return {'granularity': granularity, 'points': points, 'population': metrics.population(scope)}


LEVELS = {'circle': ['project', 'circle'], 'ci': ['project', 'circle', 'ci'], 'ie': ['project', 'circle', 'ci', 'ie']}


def hierarchy(params, user) -> dict:
    """Circle → CI/Cluster → IE rows (each with the KPIs of its sites); the level's parent comes from the filters."""
    scope = _scope(params)
    ds = dataset(user, scope)
    sel = selection(params, ds)
    level = params.get('level') or 'circle'
    if level not in LEVELS:
        raise ValidationError({'level': 'Choose circle, ci or ie.'})
    if sel.start is None:
        return {'level': level, 'rows': [], 'population': metrics.population(scope)}
    dates = period_dates(ds, sel.start, sel.end)
    om = om_status(ds, dates)
    pop = population_status(ds, scope, dates)
    table = _filtered_table(ds, sel, dates, scope)
    rows = []
    for values, group in table.groupby(LEVELS[level], sort=True):
        values = dict(zip(LEVELS[level], values if isinstance(values, tuple) else (values,)))
        key = {'circle': values['circle'], 'ci': f"{values['circle']}{SEP}{values.get('ci', '')}",
               'ie': f"{values['circle']}{SEP}{values.get('ci', '')}{SEP}{values.get('ie', '')}"}[level]
        rows.append({**values, 'key': key, **aggregate(group, pop)})
    return {'level': level, 'rows': rows, 'om_start': om, 'population': pop}


SITE_SORTS = {'site_id', 'circle', 'ci', 'ie', 'availability', 'outage', 'days'}


def _text(value) -> str:
    """A text cell; blank (None or a pandas NaN) is ''."""
    return '' if value is None or (isinstance(value, float) and np.isnan(value)) else str(value)


def sites(params, user) -> dict:
    """Site-wise table of the population (server-side search, sort and paging)."""
    scope = _scope(params)
    ds = dataset(user, scope)
    sel = selection(params, ds)
    if sel.start is None:
        return {'total': 0, 'page': 1, 'pages': 1, 'rows': [], 'population': metrics.population(scope)}
    dates = period_dates(ds, sel.start, sel.end)
    om = om_status(ds, dates)
    pop = population_status(ds, scope, dates)
    table = _filtered_table(ds, sel, dates, scope)
    q = (params.get('q') or '').strip().casefold()
    if q:
        table = table[table['site_id'].str.casefold().str.contains(q, regex=False) | table['site_name'].fillna('').str.casefold().str.contains(q, regex=False)]
    sort = params.get('sort') or 'availability'
    if sort.lstrip('-') not in SITE_SORTS:
        raise ValidationError({'sort': 'Unknown sort field.'})
    table = table.sort_values([sort.lstrip('-'), 'site_id'], ascending=[not sort.startswith('-'), True], na_position='last', kind='stable')
    try:
        page = max(1, int(params.get('page') or 1))
    except ValueError as exc:
        raise ValidationError({'page': 'Give a page number.'}) from exc
    total = len(table)
    chunk = table.iloc[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]
    labels = {b: label for b, label, *_ in BUCKETS}
    out = [{
        'site_id': r.site_id, 'site_name': _text(r.site_name), 'project': r.project, 'circle': r.circle, 'ci': r.ci, 'ie': r.ie, 'oa': _text(r.oa),
        'on_air': bool(r.on_air), 'om_start': r.om_start, 'availability_pct': None if np.isnan(r.availability) else round(float(r.availability), 4),
        'outage_minutes': round(float(r.outage), 2) if r.days else None, 'outage_hours': round(float(r.outage) / 60, 2) if r.days else None,
        'days_reported': int(r.days), 'days_expected': int(r.expected_days), 'bucket': _text(r.bucket) or None, 'bucket_label': labels.get(_text(r.bucket)),
        'usd': bool(r.usd) if pop['available'] else None, 'nsla': bool(r.nsla) if pop['available'] else None,
    } for r in chunk.itertuples()]
    return {'total': total, 'page': page, 'page_size': PAGE_SIZE, 'pages': max(1, -(-total // PAGE_SIZE)), 'rows': out, 'om_start': om,
            'population': pop}


def rca(params, user) -> dict:
    """RCA records of the period and site filters: the ten approved Final Buckets (existing mapping) and Not mapped.

    The records are not limited by the population unless a site-based filter (CI, IE, site, availability bucket) is set:
    those match the population's sites (``scope``) of the period, as the other All KPI's figures."""
    from apps.accounts.access import pairs_for
    from apps.rca import services
    from apps.rca import taxonomy
    from apps.rca.breakdown import COLUMNS
    from django.db.models import Count, Sum

    scope = _scope(params)
    ds = dataset(user, scope)
    sel = selection(params, ds)
    if sel.start is None:
        return {'buckets': [], 'records': 0, 'population': metrics.population(scope)}
    qs = services.filtered({'date_from': sel.start.isoformat(), 'date_to': sel.end.isoformat()}, pairs_for(user, 'rca_summary', 'view'))
    if sel.projects:
        qs = qs.filter(project__in=sel.projects)
    if sel.circles:
        qs = qs.filter(circle__in=sel.circles)
    if sel.cis or sel.ies or sel.sites or sel.buckets:  # CI / IE / site / availability filters: the matching Site Master sites
        table = _filtered_table(ds, sel, period_dates(ds, sel.start, sel.end), scope)
        qs = qs.filter(site_key__in=[site_key(s) for s in table['site_id']])
    labels = [label for label, _ in COLUMNS]
    by_bucket, by_circle, unmapped = Counter(), {}, Counter()
    minutes = Counter()
    for r in qs.values('circle', 'final_bucket_key', 'final_bucket').annotate(n=Count('id'), m=Sum('outage_minutes')):
        column = taxonomy.approved_final(r['final_bucket_key']) if r['final_bucket_key'] else None
        if sel.final_buckets and (column or 'Not mapped') not in sel.final_buckets:
            continue
        name = column or 'Not mapped'
        by_bucket[name] += r['n']
        minutes[name] += r['m'] or 0
        by_circle.setdefault(r['circle'], Counter())[name] += r['n']
        if not column:
            unmapped[r['final_bucket'] or '(blank)'] += r['n']
    total = sum(by_bucket.values())
    return {
        'period': {'start': sel.start.isoformat(), 'end': sel.end.isoformat(), 'label': period_label(sel.start, sel.end)},
        'records': total,
        'buckets': [{'bucket': b, 'records': by_bucket.get(b, 0), 'outage_minutes': round(minutes.get(b, 0), 2),
                     'share_pct': round(100.0 * by_bucket.get(b, 0) / total, 1) if total else None} for b in labels],
        'not_mapped': {'records': by_bucket.get('Not mapped', 0), 'values': [{'final_bucket': k, 'records': v} for k, v in unmapped.most_common()]},
        'by_circle': [{'circle': c, 'records': sum(v.values()), 'buckets': {b: v.get(b, 0) for b in labels}} for c, v in sorted(by_circle.items())],
        'ownership': {'configured': False, 'message': 'Not configured: no approved mapping from Final Buckets to Own / Customer / Third Party / Pending.'},
        'population': metrics.population(scope),
    }


def filters(params, user) -> dict:
    """Filter options from the user's sites of the population (``scope``; those in it on the last date of the selected
    period), cascading: project and circle → CI → IE → site."""
    from apps.rca.breakdown import COLUMNS
    scope = _scope(params)
    ds = dataset(user, scope)
    sel = selection(params, ds)
    in_pop = np.zeros(len(ds.sites), dtype=bool)
    every = np.arange(len(ds.sites))
    days = period_dates(ds, sel.start, sel.end) if sel.start else []
    members = per_site(ds, every, days, scope)['row'].to_numpy() if days else every[metrics.population_flags(ds, scope)]
    in_pop[members] = True
    s = ds.sites[in_pop]
    def matching(ignore):
        rows = site_rows(ds, sel, ignore=ignore)
        return ds.sites.iloc[rows[in_pop[rows]]]
    by_circle = matching(('circle', 'ci', 'ie', 'site'))
    by_ci = matching(('ci', 'ie', 'site'))
    by_ie = matching(('ie', 'site'))
    by_site = matching(('site',))
    dates = list(daily_columns(ds))
    cis = sorted({(c, n) for c, n in zip(by_ci['circle'], team_names(by_ci['ci_name']))})
    ies = sorted({(c, ci, ie) for c, ci, ie in zip(by_ie['circle'], team_names(by_ie['ci_name']), team_names(by_ie['ie_name']))})
    return {
        'dates': [d.isoformat() for d in dates],
        'default_period': {'start': sel.start.isoformat(), 'end': sel.end.isoformat()} if sel.start else None,
        'projects': sorted(set(s['report_type'])),
        'circles': sorted(set(by_circle['circle'])),
        'cis': [{'key': f'{c}{SEP}{n}', 'label': n, 'circle': c} for c, n in cis],
        'ies': [{'key': f'{c}{SEP}{ci}{SEP}{ie}', 'label': ie, 'ci': ci, 'circle': c} for c, ci, ie in ies],
        'sites': [{'key': sid.upper(), 'label': f'{sid} · {name}' if name else sid} for sid, name in
                  sorted(zip(by_site['site_id'], by_site['site_name'].fillna('').astype(str)))[:2000]],
        'site_count': int(len(by_site)),
        'buckets': [{'key': b, 'label': label} for b, label, *_ in BUCKETS],
        'final_buckets': [label for label, _ in COLUMNS] + ['Not mapped'],
        'scopes': [{'value': k, 'label': label} for k, label in metrics.SCOPES.items()],
        'default_scope': metrics.DEFAULT_SCOPE,
        'population': metrics.population(scope),
    }
