"""Circle-wise Root Cause Breakdown (RCA Summary): RCA records per circle and Final Bucket.

The columns are the 10 approved Final Buckets of the taxonomy (apps.rca.taxonomy), in its order, with the approved
names. A record is counted in the column of its Final Bucket (spaces and case ignored, ``parser.text_key``); no other
value is read as a Final Bucket (no aliases or equivalents).

- A record is counted in one column only.
- Final Bucket values that are not approved (and blank values) are never put in Others: they are counted under
  "Not mapped", listed with their raw values, and kept out of the Grand Total, so every record is accounted for.
- Rows: one per circle (projects combined, as the workbook keys rows on the circle), for every circle of the selected
  project in the site master and every circle with records. A circle without records has empty cells, not zeros.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from django.db.models import Count, Max, QuerySet

from . import taxonomy
from .parser import text_key

# (column label, Final Bucket values counted in it): the approved Final Buckets, each counting only itself.
COLUMNS: tuple[tuple[str, tuple[str, ...] | None], ...] = tuple((final, (final,)) for final in taxonomy.APPROVED)
PENDING = tuple(label for label, values in COLUMNS if values is None)
FINAL_BUCKET_CATEGORIES: dict[str, str] = {text_key(value): label for label, values in COLUMNS if values for value in values}
NOT_MAPPED = 'Not mapped'
BLANK_LABEL = '(blank)'

# NSLA / USD: the shared dashboard rules over the selected population (apps.dashboard.metrics.nsla_dates / usd_dates,
# approved rule B-3).


def category_of(final_bucket: str) -> str | None:
    """The reporting column of a Final Bucket value, or None when it maps to no column."""
    key = text_key(final_bucket)
    return FINAL_BUCKET_CATEGORIES.get(key) if key else None


def _pct(part: int, whole: int) -> float | None:
    return round(100.0 * part / whole, 2) if whole else None


def breakdown(qs: QuerySet, *, circles: list[str], through: str | None) -> dict:
    """Counts per circle and column from the already filtered records (one grouped query)."""
    counts: dict[str, Counter] = defaultdict(Counter)
    raw_labels: dict[str, str] = {}
    unmapped: Counter = Counter()
    unmapped_by_circle: Counter = Counter()
    for row in qs.values('circle', 'final_bucket_key').annotate(records=Count('id'), label=Max('final_bucket')):
        column = FINAL_BUCKET_CATEGORIES.get(row['final_bucket_key']) if row['final_bucket_key'] else None
        if column:
            counts[row['circle']][column] += row['records']
        else:
            key = row['final_bucket_key'] or ''
            raw_labels.setdefault(key, row['label'] if key else BLANK_LABEL)
            unmapped[key] += row['records']
            unmapped_by_circle[row['circle']] += row['records']
    labels = [label for label, _ in COLUMNS]
    rows = []
    for circle in sorted(set(circles) | set(counts) | set(unmapped_by_circle)):
        has_records = circle in counts or circle in unmapped_by_circle
        values = {label: (None if label in PENDING or not has_records else counts[circle][label]) for label in labels}
        rows.append({'circle': circle, 'has_records': has_records, 'counts': values,
                     'grand_total': sum(counts[circle].values()) if has_records else None,
                     'not_mapped': unmapped_by_circle[circle] if has_records else None})
    totals = {label: (None if label in PENDING else sum(c[label] for c in counts.values())) for label in labels}
    grand_total = sum(v for v in totals.values() if v)
    return {
        'through': through,
        'columns': [{'label': label, 'pending': label in PENDING,
                     'final_buckets': list(values) if values else []} for label, values in COLUMNS],
        'rows': rows,
        'totals': totals,
        'grand_total': grand_total,
        'percent_of_total': {label: (None if v is None else _pct(v, grand_total)) for label, v in totals.items()},
        'not_mapped': {'records': sum(unmapped.values()),
                       'values': [{'final_bucket': raw_labels[k], 'records': n} for k, n in unmapped.most_common()]},
        'records': grand_total + sum(unmapped.values()),
        'empty': grand_total + sum(unmapped.values()) == 0,
    }


def site_metrics(params, pairs, circles: list[str], rca_dates: tuple[_date | None, _date | None] | None = None) -> dict | None:
    """Total Sites, O&M Start Sites, USD Sites and NSLA Sites (<98.5%) per circle: the sitedata dashboard dataset.

    Population and Site Scope (how they combine):
    - ``scope`` (on_air | om_start, default on_air; anything else is HTTP 400) is the site POPULATION of every site figure
      here, as on every site-metric page: the population's sites of the period (effective by its last date), each counted
      from its effective date (the dataset variant of the population).
    - ``site_scope`` (all | om_start | om_not_started, unchanged) is the RCA record filter (sitescope); for the site
      columns it narrows the population to its sites that are / are not O&M Start in the period (Consolidation Matrix O&M
      Start Date on or before the end of the period's last month). So population On-Air + site scope O&M Start = the On-Air
      sites that have started O&M; population O&M Start + site scope O&M Not Started is empty (0 sites, USD / NSLA None).

    Business Rules (approved rule B-3, the dashboard's metrics.usd_dates / nsla_dates):
    - Total Sites: the sites of the population (and site scope) of the selected project.
    - O&M Start Sites: a status count, those of them that are O&M Start in the period.
    - USD Sites: distinct sites of the population with outage > 0 on at least one reported day of their effective period.
    - NSLA Sites: sites of the population whose uptime over the period, pooled over their reported days from the effective
      date, is below 98.5% (exactly 98.5% does not qualify; one bad day does not when the period uptime is >= 98.5%;
      missing data never qualifies). USD / NSLA are None (never 0) when none of the sites reported.
    - Missing Availability: sites of the population lacking availability data on a reported day of the period.
    - Scope Independence: The 4 site KPI columns are independent of the RCA breakdown toggle.
    - ``nsla_site_keys``: {(technology, key_of(site_id))} of the NSLA sites, to match RCA records by project and site key.
    """
    from datetime import date as _date, timedelta
    import numpy as np

    from apps.dashboard import metrics
    from apps.dashboard.metrics import Selection, base_mask
    from apps.dashboard.serializers import parse_scope
    from apps.sitedata.identifiers import key_of
    from apps.dashboard.workbook import WorkbookError
    from apps.sitedata.dashboard_source import dataset
    from . import sitescope

    population = parse_scope(params.get('scope'))
    site_scope = sitescope.parse(params.get('site_scope'))  # the same Site Scope as the RCA records
    try:
        ds = dataset(pairs, population)
    except WorkbookError:
        return None
    parse = lambda v: _date.fromisoformat(v) if v else None  # noqa: E731 - validated already by services.filtered
    day, start, end = parse(params.get('date')), parse(params.get('date_from')), parse(params.get('date_to'))
    if day:
        dates, label = [day], day.isoformat()
    elif start or end:
        start, end = start or ds.dates[0], end or ds.latest_date or ds.dates[-1]
        dates, label = [start + timedelta(days=i) for i in range((end - start).days + 1)], f'{start.isoformat()} – {end.isoformat()}'
    elif rca_dates and rca_dates[0] and rca_dates[1] and (rca_dates[0] < ds.dates[0] or (rca_dates[1] - rca_dates[0]).days > 0):
        start, end = rca_dates[0], rca_dates[1]
        dates, label = [start + timedelta(days=i) for i in range((end - start).days + 1)], f'{start.isoformat()} – {end.isoformat()}'
    else:
        latest = ds.latest_date or ds.dates[-1]
        dates, label = [d for d in ds.dates if d <= latest], 'Month to date'
    project = params.get('project') or None
    if project in ('4G', '4G Satu', '4G Satu.'):
        project = '4G Saturation'

    # The population of the period (metrics.population_rows), narrowed by the Site Scope's O&M Start status in the period.
    base = np.flatnonzero(base_mask(ds, Selection(project, None, population)))
    rows = metrics.population_rows(ds, base, population, dates)
    om_flags = metrics.population_flags(ds, 'om_start', max(dates) if dates else None)
    if site_scope == sitescope.OM_START:
        rows = rows[om_flags[rows]]
    elif site_scope == sitescope.OM_NOT_STARTED:
        rows = rows[~om_flags[rows]]

    # Values of the period from each site's effective date (the population's view); days without data are not columns.
    full, _used = metrics.period_block(metrics.population_view(ds, population), rows, dates)
    reported_days = full.shape[1]
    _eligible, uptime, nsla = metrics.nsla_dates(ds, rows, dates, scope=population)
    _eligible, reported, usd = metrics.usd_dates(ds, rows, dates, scope=population)

    # Missing availability: population sites without a value on a reported day of the period (deduplicated per site).
    missing_sites = []
    if reported_days > 0:
        for idx in np.flatnonzero(np.isnan(full).any(axis=1)):
            site_row = rows[idx]
            missing_sites.append({'site_id': str(ds.sites['site_id'].iloc[site_row]), 'circle': str(ds.sites['circle'].iloc[site_row])})
    missing_availability = {
        'count': len(missing_sites),
        'by_circle': dict(Counter(s['circle'] for s in missing_sites)),
        'sample': missing_sites[:100],
    }

    # Identifiers of the NSLA sites (for matching RCA records when the NSLA RCA toggle is active)
    nsla_rows = rows[nsla]
    nsla_site_keys = {(t, key_of(s)) for t, s in zip(ds.sites['report_type'].to_numpy()[nsla_rows], ds.sites['site_id'].to_numpy()[nsla_rows])}

    row_circles = ds.sites['circle'].to_numpy()[rows]
    has_value = ~np.isnan(uptime)

    def measure(circle: str | None) -> dict:
        mine = row_circles == circle if circle else np.ones(len(rows), dtype=bool)
        return {
            'total_sites': int(mine.sum()),
            'om_start_sites': int(om_flags[rows][mine].sum()),
            'usd_sites': int(usd[mine].sum()) if reported[mine].any() else None,
            'nsla_sites': int(nsla[mine].sum()) if has_value[mine].any() else None,
            'days_reported': reported_days,
        }

    total = measure(params.get('circle') or None)
    return {
        'period': {
            'label': label,
            'first': dates[0].isoformat() if dates else None,
            'last': dates[-1].isoformat() if dates else None,
            'days_reported': total['days_reported'],
        },
        'population': metrics.population(population),
        'site_scope': site_scope,
        'rows': {c: measure(c) for c in circles},
        'total': total,
        'nsla_site_keys': nsla_site_keys,
        'definitions': {'usd_sites': metrics.usd_rule(population), 'nsla_sites': metrics.nsla_rule(population),
                        'om_start_sites': 'Status count: sites of the population that are O&M Start in the period.'},
        'missing_availability': missing_availability,
    }
