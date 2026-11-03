"""All KPI's: read-only calculations for the optional All KPI's module (see README.md in this folder).

Everything is computed from existing data through existing interfaces, without changing them:
- Sites and daily outage: the dashboard dataset (``uptimedb.datasource.current_dataset``), limited to the user's
  project/circle pairs (``dashboard.scope.restrict``). Daily values of earlier months come from its ``daily_history``,
  so weekly and monthly figures are derived from the canonical daily records (never ``SiteMonthlyPerformance`` totals).
- O&M Start: ``SiteMonthlyPerformance.om_start`` of each day's own month, read directly. A month without O&M Start
  values is "not available": no other month's flags are carried forward.
- Shared formulas reused as they are: ``metrics.uptime_pct`` (outage-weighted availability), ``metrics.bucket_ids``
  (threshold buckets), ``metrics.WEEKS``, ``metrics.team_names``; RCA: ``rca.services.filtered`` and the approved
  Final Bucket mapping ``rca.breakdown.FINAL_BUCKET_CATEGORIES``.

Definitions specific to this module (approved for All KPI's):
- USD Sites: distinct O&M Start sites with outage > 0 on at least one day of the period.
- NSLA Sites: distinct O&M Start sites with daily availability strictly below 98.5% on at least one day (exactly 98.5%
  does not qualify; a missing value never does).
- Availability, outage and threshold buckets: On-Air sites (the dashboard's default population); a missing value is
  "not reported", never 0% or 0 minutes.
"""
from __future__ import annotations

import calendar
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd
from rest_framework.exceptions import ValidationError

from apps.dashboard.metrics import BUCKET_IDS, BUCKETS, MINUTES_PER_DAY, WEEKS, bucket_ids, team_names, uptime_pct
from apps.dashboard.scope import restrict
from apps.uptimedb.parser import site_key

NSLA_THRESHOLD = 98.5
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


def dataset(user):
    """The dashboard dataset limited to the user's Dashboard View pairs (the same rule as every dashboard page)."""
    from apps.accounts.access import pairs_for
    from apps.uptimedb.datasource import current_dataset
    return restrict(current_dataset(), pairs_for(user, 'dashboard', 'view'))


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


def om_start_by_month(ds, months: set[date]) -> dict[date, dict[tuple, bool] | None]:
    """O&M Start of each site for each month, from that month's own Site Master monthly values (None: no data).
    Kept on the dataset object, which is rebuilt after every import, so a month is read once per dataset."""
    from apps.uptimedb.models import SiteMonthlyPerformance
    memo = ds._memo.setdefault('allkpis_om_start', {})
    for month in months - memo.keys():
        rows = SiteMonthlyPerformance.objects.filter(month=month, om_start__isnull=False).values_list(
            'site__project', 'site__circle', 'site__site_key', 'om_start')
        memo[month] = {(p, c, k): v for p, c, k, v in rows} or None
    return {m: memo[m] for m in months}


def per_site(ds, rows: np.ndarray, dates: list[date]) -> pd.DataFrame:
    """One row per site: its outage over the period, reported days, USD / NSLA flags and its period availability."""
    sites = ds.sites.iloc[rows]
    block = outage_block(ds, rows, dates)
    months = {d.replace(day=1) for d in dates}
    om = om_start_by_month(ds, months)
    keys = list(zip(sites['report_type'], sites['circle'], sites['site_id'].map(site_key)))
    # O&M Start = Yes for the site in each day's own month (False when that month has no O&M Start data).
    day_flags = [om[d.replace(day=1)] or {} for d in dates]
    om_yes = np.array([[bool(f.get(k)) for f in day_flags] for k in keys], dtype=bool).reshape(len(rows), len(dates))
    reported = ~np.isnan(block)
    with np.errstate(invalid='ignore'):
        down = reported & (block > 0)
        availability = np.round(100.0 * (1.0 - block / MINUTES_PER_DAY), 6)
        below = reported & (availability < NSLA_THRESHOLD)
    on_air = sites['on_air'].to_numpy(dtype=bool)
    out_sum = np.where(reported, block, 0.0).sum(axis=1)
    days = reported.sum(axis=1)
    with np.errstate(invalid='ignore', divide='ignore'):
        site_avail = np.where(days > 0, 100.0 * (1.0 - out_sum / (MINUTES_PER_DAY * np.maximum(days, 1))), np.nan)
    latest_month = max(months) if months else None
    latest_flags = om.get(latest_month) if latest_month else None
    return pd.DataFrame({
        'row': rows, 'site_id': sites['site_id'].to_numpy(), 'site_name': sites['site_name'].to_numpy(),
        'project': sites['report_type'].to_numpy(), 'circle': sites['circle'].to_numpy(),
        'ci': team_names(sites['ci_name']).to_numpy(), 'ie': team_names(sites['ie_name']).to_numpy(), 'oa': sites['oa'].to_numpy(),
        'on_air': on_air, 'outage': out_sum, 'days': days, 'expected_days': len(dates), 'availability': site_avail,
        'bucket': bucket_ids(site_avail),
        # O&M Start in the latest month of the period (None: that month has no O&M Start data).
        'om_start': [None if latest_flags is None else bool(latest_flags.get(k)) for k in keys],
        'usd': (down & om_yes).any(axis=1), 'nsla': (below & om_yes).any(axis=1),
    })


def om_status(ds, dates: list[date]) -> dict:
    months = sorted({d.replace(day=1) for d in dates})
    om = om_start_by_month(ds, set(months))
    missing = [m for m in months if om[m] is None]
    return {'months': [m.strftime('%Y-%m') for m in months], 'missing_months': [m.strftime('%b %Y') for m in missing],
            'available': bool(months) and len(missing) < len(months), 'complete': not missing}


def aggregate(table: pd.DataFrame, om: dict) -> dict:
    """KPIs of a group of sites (the whole selection, a circle, a CI, an IE)."""
    active = table[table['on_air']]
    outage = float(active['outage'].sum())
    site_days = int(active['days'].sum())
    expected = int(len(active) * (active['expected_days'].iloc[0] if len(active) else 0))
    valued = active[active['days'] > 0]
    counts = Counter(valued['bucket'])
    om_ok = om['available']
    om_latest_known = table['om_start'].notna().any() if len(table) else False
    return {
        'total_sites': int(len(table)), 'on_air_sites': int(table['on_air'].sum()),
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


def _filtered_table(ds, sel: Selection, dates: list[date]) -> pd.DataFrame:
    table = per_site(ds, site_rows(ds, sel), dates)
    if sel.buckets:
        table = table[table['bucket'].isin(sel.buckets)]
    return table


def period_label(start: date, end: date) -> str:
    return start.strftime('%d %b %Y') if start == end else f'{start:%d %b %Y} – {end:%d %b %Y}'


def summary(params, user) -> dict:
    ds = dataset(user)
    sel = selection(params, ds)
    if sel.start is None:
        return {'period': None, 'current': None, 'previous': None, 'notes': ['No daily performance data is available.']}
    dates = period_dates(ds, sel.start, sel.end)
    om = om_status(ds, dates)
    current = aggregate(_filtered_table(ds, sel, dates), om)
    # Comparison: the same number of days immediately before (only dates with data).
    span = (sel.end - sel.start).days + 1
    p_end, p_start = sel.start - timedelta(days=1), sel.start - timedelta(days=span)
    p_dates = period_dates(ds, p_start, p_end)
    p_om = om_status(ds, p_dates)
    previous = aggregate(_filtered_table(ds, sel, p_dates), p_om) if p_dates else None
    return {
        'period': {'start': sel.start.isoformat(), 'end': sel.end.isoformat(), 'label': period_label(sel.start, sel.end), 'days_with_data': len(dates),
                   'days_in_period': span},
        'previous_period': {'start': p_start.isoformat(), 'end': p_end.isoformat(), 'label': period_label(p_start, p_end), 'days_with_data': len(p_dates)},
        'current': current, 'previous': previous, 'om_start': om, 'previous_om_start': p_om,
        'pending': {
            'site_handover_status': 'Pending clarification: Site Handover Status is not defined yet.',
            'rca_ownership': 'Not configured: no approved mapping from Final Buckets to Own / Customer / Third Party / Pending.',
        },
    }


def _months_with_data(ds) -> list[date]:
    return sorted({d.replace(day=1) for d in daily_columns(ds)})


def trends(params, user) -> dict:
    ds = dataset(user)
    sel = selection(params, ds)
    granularity = params.get('granularity') or 'day'
    if granularity not in ('day', 'week', 'month'):
        raise ValidationError({'granularity': 'Choose day, week or month.'})
    if sel.start is None:
        return {'granularity': granularity, 'points': []}
    available = list(daily_columns(ds))
    periods: list[tuple[str, str, list[date]]] = []
    if granularity == 'day':
        periods = [(d.isoformat(), d.strftime('%d %b'), [d]) for d in period_dates(ds, sel.start, sel.end)]
    elif granularity == 'week':
        months = sorted({d.replace(day=1) for d in period_dates(ds, sel.start, sel.end)})
        for m in months:
            last = calendar.monthrange(m.year, m.month)[1]
            for name, first, end in WEEKS:
                days = [d for d in available if d.replace(day=1) == m and first <= d.day <= min(end, last) and sel.start <= d <= sel.end]
                if days:
                    periods.append((f'{m:%Y-%m}-{name}', f'{name} {m:%b %Y}', days))
    else:  # every month with daily data (whole months; the latest may be month to date)
        for m in _months_with_data(ds):
            days = [d for d in available if d.replace(day=1) == m]
            last = calendar.monthrange(m.year, m.month)[1]
            periods.append((m.strftime('%Y-%m'), f'{m:%b %Y}' + ('' if len(days) == last else ' (MTD)'), days))
    rows = site_rows(ds, sel)
    points = []
    for key, label, days in periods:
        table = per_site(ds, rows, days)
        if sel.buckets:
            table = table[table['bucket'].isin(sel.buckets)]
        k = aggregate(table, om_status(ds, days))
        points.append({'key': key, 'label': label, 'start': days[0].isoformat(), 'end': days[-1].isoformat(), 'days': len(days), **{
            f: k[f] for f in ('availability_pct', 'outage_minutes', 'outage_hours', 'usd_sites', 'nsla_sites', 'below_98_5_sites', 'below_60_sites',
                              'coverage_pct', 'missing_site_days')}})
    return {'granularity': granularity, 'points': points}


LEVELS = {'circle': ['project', 'circle'], 'ci': ['project', 'circle', 'ci'], 'ie': ['project', 'circle', 'ci', 'ie']}


def hierarchy(params, user) -> dict:
    """Circle → CI/Cluster → IE rows (each with the KPIs of its sites); the level's parent comes from the filters."""
    ds = dataset(user)
    sel = selection(params, ds)
    level = params.get('level') or 'circle'
    if level not in LEVELS:
        raise ValidationError({'level': 'Choose circle, ci or ie.'})
    if sel.start is None:
        return {'level': level, 'rows': []}
    dates = period_dates(ds, sel.start, sel.end)
    om = om_status(ds, dates)
    table = _filtered_table(ds, sel, dates)
    rows = []
    for values, group in table.groupby(LEVELS[level], sort=True):
        values = dict(zip(LEVELS[level], values if isinstance(values, tuple) else (values,)))
        key = {'circle': values['circle'], 'ci': f"{values['circle']}{SEP}{values.get('ci', '')}",
               'ie': f"{values['circle']}{SEP}{values.get('ci', '')}{SEP}{values.get('ie', '')}"}[level]
        rows.append({**values, 'key': key, **aggregate(group, om)})
    return {'level': level, 'rows': rows, 'om_start': om}


SITE_SORTS = {'site_id', 'circle', 'ci', 'ie', 'availability', 'outage', 'days'}


def _text(value) -> str:
    """A text cell; blank (None or a pandas NaN) is ''."""
    return '' if value is None or (isinstance(value, float) and np.isnan(value)) else str(value)


def sites(params, user) -> dict:
    """Site-wise table (server-side search, sort and paging)."""
    ds = dataset(user)
    sel = selection(params, ds)
    if sel.start is None:
        return {'total': 0, 'page': 1, 'pages': 1, 'rows': []}
    dates = period_dates(ds, sel.start, sel.end)
    om = om_status(ds, dates)
    table = _filtered_table(ds, sel, dates)
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
        'usd': bool(r.usd) if om['available'] else None, 'nsla': bool(r.nsla) if om['available'] else None,
    } for r in chunk.itertuples()]
    return {'total': total, 'page': page, 'page_size': PAGE_SIZE, 'pages': max(1, -(-total // PAGE_SIZE)), 'rows': out, 'om_start': om}


def rca(params, user) -> dict:
    """RCA records of the period and site filters: the ten approved Final Buckets (existing mapping) and Not mapped."""
    from apps.accounts.access import pairs_for
    from apps.rca import services
    from apps.rca.breakdown import COLUMNS, FINAL_BUCKET_CATEGORIES
    from django.db.models import Count, Sum

    ds = dataset(user)
    sel = selection(params, ds)
    if sel.start is None:
        return {'buckets': [], 'records': 0}
    qs = services.filtered({'date_from': sel.start.isoformat(), 'date_to': sel.end.isoformat()}, pairs_for(user, 'rca_summary', 'view'))
    if sel.projects:
        qs = qs.filter(project__in=sel.projects)
    if sel.circles:
        qs = qs.filter(circle__in=sel.circles)
    if sel.cis or sel.ies or sel.sites or sel.buckets:  # CI / IE / site / availability filters: the matching Site Master sites
        table = _filtered_table(ds, sel, period_dates(ds, sel.start, sel.end))
        qs = qs.filter(site_key__in=[site_key(s) for s in table['site_id']])
    labels = [label for label, _ in COLUMNS]
    by_bucket, by_circle, unmapped = Counter(), {}, Counter()
    minutes = Counter()
    for r in qs.values('circle', 'final_bucket_key', 'final_bucket').annotate(n=Count('id'), m=Sum('outage_minutes')):
        column = FINAL_BUCKET_CATEGORIES.get(r['final_bucket_key']) if r['final_bucket_key'] else None
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
    }


def filters(params, user) -> dict:
    """Filter options from the user's sites, cascading: project and circle → CI → IE → site."""
    from apps.rca.breakdown import COLUMNS
    ds = dataset(user)
    sel = selection(params, ds)
    s = ds.sites
    by_circle = s.iloc[site_rows(ds, sel, ignore=('circle', 'ci', 'ie', 'site'))]
    by_ci = s.iloc[site_rows(ds, sel, ignore=('ci', 'ie', 'site'))]
    by_ie = s.iloc[site_rows(ds, sel, ignore=('ie', 'site'))]
    by_site = s.iloc[site_rows(ds, sel, ignore=('site',))]
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
    }
