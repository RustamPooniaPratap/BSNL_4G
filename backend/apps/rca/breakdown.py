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

# Daily availability threshold for NSLA: strictly below 98.5%.
# 1440 minutes * (1 - 0.985) = 21.6 minutes. Outage strictly > 21.6 min means availability < 98.5%.
NSLA_OUTAGE_MINUTES_THRESHOLD = 21.6


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
    """Total Sites, O&M Start Sites, USD Sites and NSLA Sites (<98.5%) per circle: site master and daily performance data.

    Business Rules:
    - Total Sites: Active On-Air sites in scope.
    - O&M Start Sites: Active On-Air sites classified as O&M Start in the Site Master.
    - USD Sites: COUNT(DISTINCT O&M Start site_key WHERE outage_minutes > 0 on at least one day in the period).
      Non-O&M Start sites are excluded. Zero-outage sites are excluded. Counted once per period.
    - NSLA Sites: COUNT(DISTINCT O&M Start site_key WHERE daily availability < 98.5% on at least one day in the period).
      Availability < 98.5% equates strictly to daily outage > 21.6 minutes.
      Exactly 98.5% does not qualify. Above 98.5% does not qualify. Missing availability does not qualify.
      Only O&M Start sites are eligible. Counted once per period.
    - Missing Availability: O&M Start sites lacking availability data for the period are identified for notifications
      and excluded from NSLA.
    - Scope Independence: The 4 site KPI columns are independent of the RCA breakdown toggle.
    """
    from datetime import date as _date, timedelta
    import numpy as np

    from apps.dashboard.metrics import Selection, scope_mask
    from apps.dashboard.scope import restrict
    from apps.dashboard.workbook import WorkbookError
    from apps.uptimedb.datasource import current_dataset

    try:
        ds = restrict(current_dataset(), pairs)
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
    from .sitescope import dashboard_scope, parse
    scope = dashboard_scope(parse(params.get('site_scope')))  # the same Site Scope as the RCA records

    # Total active sites in scope
    mask_total = scope_mask(ds, Selection(project, None, scope))
    rows_total = np.flatnonzero(mask_total)

    # O&M Start site population (USD and NSLA are strictly evaluated within this population)
    mask_om = scope_mask(ds, Selection(project, None, 'on_air_om_start'))
    rows_om = np.flatnonzero(mask_om)

    # Gather outage blocks for O&M Start sites across all requested dates
    cols = [ds.position(d) for d in dates if d in ds.reported_dates]
    blocks = [ds.outage[np.ix_(rows_om, cols)]] if cols else []
    wanted = set(dates)
    for entry in ds.daily_history:
        idx = [i for i, d in enumerate(entry['dates']) if d in wanted and not np.isnan(entry['outage'][:, i]).all()]
        if idx:
            blocks.append(entry['outage'][np.ix_(rows_om, idx)])

    if blocks:
        full = np.hstack(blocks)
        reported_days = full.shape[1]
    else:
        full = np.full((len(rows_om), 0), np.nan)
        reported_days = 0

    # Business evaluations per O&M Start site:
    # 1. USD: positive outage minutes (> 0) on at least one reported day.
    usd_mask = ((full > 0) & (~np.isnan(full))).any(axis=1) if reported_days > 0 else np.zeros(len(rows_om), dtype=bool)

    # 2. NSLA: daily availability strictly below 98.5% (> 21.6 min outage) on at least one day.
    # Exactly 98.5% (= 21.6 min) does not qualify. Above 98.5% (< 21.6 min) does not qualify.
    # Missing availability (NaN) does not qualify.
    nsla_mask = ((full > NSLA_OUTAGE_MINUTES_THRESHOLD) & (~np.isnan(full))).any(axis=1) if reported_days > 0 else np.zeros(len(rows_om), dtype=bool)

    # 3. Missing availability: O&M Start sites with missing data in the period (for notifications, deduplicated per site)
    missing_sites = []
    if reported_days > 0:
        missing_idx = np.flatnonzero(np.isnan(full).any(axis=1))
        for idx in missing_idx:
            site_row = rows_om[idx]
            missing_sites.append({
                'site_id': str(ds.sites['site_id'].iloc[site_row]),
                'circle': str(ds.sites['circle'].iloc[site_row]),
            })

    missing_by_circle = dict(Counter(s['circle'] for s in missing_sites))
    missing_availability = {
        'count': len(missing_sites),
        'by_circle': missing_by_circle,
        'sample': missing_sites[:100],
    }

    # Set of eligible NSLA site identifiers (for matching RCA records when NSLA RCA toggle is active)
    nsla_site_keys = set(ds.sites['site_id'].iloc[rows_om[nsla_mask]]) if reported_days > 0 else set()

    site_circles = ds.sites['circle'].to_numpy()

    def measure(circle: str | None) -> dict:
        if circle:
            c_total_mask = mask_total & (site_circles == circle)
            total_count = int(c_total_mask.sum())
            c_om_idx = (site_circles[rows_om] == circle)
            om_count = int(c_om_idx.sum())
            c_reported = reported_days > 0 and c_om_idx.any() and (~np.isnan(full[c_om_idx])).any()
            usd_count = int(usd_mask[c_om_idx].sum()) if c_reported else None
            nsla_count = int(nsla_mask[c_om_idx].sum()) if c_reported else None
        else:
            total_count = len(rows_total)
            om_count = len(rows_om)
            tot_reported = reported_days > 0 and len(rows_om) > 0 and (~np.isnan(full)).any()
            usd_count = int(usd_mask.sum()) if tot_reported else None
            nsla_count = int(nsla_mask.sum()) if tot_reported else None

        if scope == 'on_air_om_not_started':
            om_count = 0
            usd_count = 0 if reported_days > 0 else None
            nsla_count = 0 if reported_days > 0 else None

        return {
            'total_sites': total_count,
            'om_start_sites': om_count,
            'usd_sites': usd_count,
            'nsla_sites': nsla_count,
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
        'rows': {c: measure(c) for c in circles},
        'total': total,
        'nsla_site_keys': nsla_site_keys,
        'missing_availability': missing_availability,
    }
