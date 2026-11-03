"""RCA Overview service: 4 KPI attribution cards (Own, Customer, Third Party, Pending)
and 4-tab table (Circle-wise, CI-wise, IE-wise, Site-wise) with the exact 8 confirmed columns.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

import numpy as np
from django.db.models import Count, Q, Sum

from apps.dashboard.metrics import Selection, mtd_positions, site_uptime
from apps.dashboard.scope import restrict
from apps.dashboard.workbook import WorkbookError
from apps.uptimedb.datasource import current_dataset
from apps.uptimedb.models import EscalationSite
from . import parser, services, sitescope
from .models import RcaRecord


def categorize_bucket(final_bucket: str) -> str:
    """Categorize an RCA Final Bucket into Own, Customer, Third Party, or Pending."""
    fb = (final_bucket or '').strip().casefold()
    if not fb or fb in ('-', '--', 'na', 'n/a', 'blank', 'null', 'none', 'others', 'other media', 'other', 'bb'):
        return 'Pending'
    if any(k in fb for k in ('iaasp', 'theft')):
        return 'Third Party'
    if any(k in fb for k in ('bsnl', 'bbnl', 'vsat', 'etr', 'ssa', 'cpan')):
        return 'Customer'
    if any(k in fb for k in ('tcs', 'hfcl', 'dmw', 'ceragon', 'ptpl', 'tech delay')):
        return 'Own'
    return 'Pending'


def compute_kpis(rca_qs) -> dict[str, Any]:
    """Calculate the 4 KPI cards above the table."""
    kpis = {
        'own': {'records': 0, 'outage_minutes': 0.0, 'share_pct': 0.0},
        'customer': {'records': 0, 'outage_minutes': 0.0, 'share_pct': 0.0},
        'third_party': {'records': 0, 'outage_minutes': 0.0, 'share_pct': 0.0},
        'pending': {'records': 0, 'outage_minutes': 0.0, 'share_pct': 0.0},
        'total_records': 0,
        'total_minutes': 0.0,
    }
    for r in rca_qs.values('final_bucket').annotate(cnt=Count('id'), mins=Sum('outage_minutes')):
        cat = categorize_bucket(r['final_bucket'])
        key = 'third_party' if cat == 'Third Party' else cat.lower()
        kpis[key]['records'] += r['cnt']
        kpis[key]['outage_minutes'] += (r['mins'] or 0.0)
        kpis['total_records'] += r['cnt']
        kpis['total_minutes'] += (r['mins'] or 0.0)

    tot_m = kpis['total_minutes']
    for key in ('own', 'customer', 'third_party', 'pending'):
        kpis[key]['outage_minutes'] = round(kpis[key]['outage_minutes'], 1)
        kpis[key]['share_pct'] = round(100.0 * kpis[key]['outage_minutes'] / tot_m, 1) if tot_m > 0 else 0.0
    kpis['total_minutes'] = round(kpis['total_minutes'], 1)
    return kpis


def get_rca_overview(params: dict[str, Any], pairs: list[tuple[str, str]] | None = None) -> dict[str, Any]:
    """Build the complete RCA Overview payload: 4 KPI cards and tab data."""
    tab = (params.get('tab') or 'circle').lower()
    if tab not in ('circle', 'ci', 'ie', 'ne', 'site'):
        tab = 'circle'
    page = max(int(params.get('page') or 1), 1)
    page_size = max(min(int(params.get('page_size') or 25), 100), 10)
    search_q = (params.get('q') or '').strip().casefold()

    # 1. RCA filtered records for KPIs and attribution split
    rca_qs = services.filtered(params, pairs)
    kpis = compute_kpis(rca_qs)

    # Site-level RCA attribution split { site_key: { 'Own': mins, 'Customer': mins, ... } }
    site_attribution = defaultdict(lambda: defaultdict(float))
    for r in rca_qs.values('site_key', 'final_bucket').annotate(mins=Sum('outage_minutes')):
        cat = categorize_bucket(r['final_bucket'])
        site_attribution[r['site_key']][cat] += (r['mins'] or 0.0)

    # 2. Uptime dataset and date scope
    try:
        ds = restrict(current_dataset(), pairs)
    except WorkbookError:
        ds = None

    if ds is None:
        return {
            'tab': tab,
            'kpis': kpis,
            'count': 0,
            'page': 1,
            'page_size': page_size,
            'pages': 1,
            'rows': [],
            'total_row': None,
        }

    # Date scope
    parse_d = lambda v: date.fromisoformat(v) if v else None
    day = parse_d(params.get('date'))
    start = parse_d(params.get('date_from'))
    end = parse_d(params.get('date_to'))
    if day:
        dates = [day]
    elif start or end:
        s_date = start or ds.dates[0]
        e_date = end or ds.latest_date or ds.dates[-1]
        dates = [s_date + timedelta(days=i) for i in range((e_date - s_date).days + 1)]
    else:
        latest = ds.latest_date or ds.dates[-1]
        dates = [d for d in ds.dates if d <= latest]

    date_indices = [ds.position(d) for d in dates if d in ds.dates]
    date_indices = [i for i in date_indices if i is not None]
    if not date_indices:
        date_indices, _ = mtd_positions(ds, ds.latest_date or ds.dates[-1])

    # Filter sites in ds
    project_filter = params.get('project') or None
    circle_filter = params.get('circle') or None
    scope_filter = sitescope.parse(params.get('site_scope'))

    mask = np.ones(len(ds.sites), dtype=bool)
    if project_filter:
        mask &= (ds.sites['report_type'] == project_filter)
    if circle_filter:
        mask &= (ds.sites['circle'] == circle_filter)
    if scope_filter == sitescope.OM_START:
        mask &= (ds.sites['om_start'] == True)  # noqa: E712
    elif scope_filter == sitescope.OM_NOT_STARTED:
        mask &= (ds.sites['om_start'] == False)  # noqa: E712

    site_indices = np.flatnonzero(mask)
    if len(site_indices) == 0:
        return {
            'tab': tab,
            'kpis': kpis,
            'count': 0,
            'page': 1,
            'page_size': page_size,
            'pages': 1,
            'rows': [],
            'total_row': None,
        }

    sub_sites = ds.sites.iloc[site_indices].copy()
    sub_outage = ds.outage[np.ix_(site_indices, date_indices)]
    uptimes = site_uptime(sub_outage)
    site_outage_mins = np.nansum(sub_outage, axis=1)

    # NE mapping from EscalationSite
    ne_map = dict(EscalationSite.objects.exclude(bts_id_b1='').values_list('site_key', 'bts_id_b1'))

    def calc_row(entity_id: str, name: str, detail: str, indices: list[int]) -> dict[str, Any]:
        count = len(indices)
        om_count = int(sub_sites.iloc[indices]['om_start'].sum())
        row_uptimes = uptimes[indices]
        valid_u = row_uptimes[~np.isnan(row_uptimes)]
        uptime_val = round(float(np.mean(valid_u)), 2) if len(valid_u) > 0 else None
        gap_val = round(uptime_val - 98.5, 2) if uptime_val is not None else None
        outage_val = round(float(np.sum(site_outage_mins[indices])), 1)

        if uptime_val is None:
            status = 'N/A'
        elif uptime_val > 98.5:
            status = 'Meeting SLA'
        else:
            status = 'Not Meeting SLA'

        own_m = cust_m = third_m = pend_m = 0.0
        for idx in indices:
            sk = str(sub_sites.iloc[idx]['site_id']).strip().upper()
            att = site_attribution.get(sk, {})
            own_m += att.get('Own', 0.0)
            cust_m += att.get('Customer', 0.0)
            third_m += att.get('Third Party', 0.0)
            pend_m += att.get('Pending', 0.0)

        tot_split_m = own_m + cust_m + third_m + pend_m
        if tot_split_m > 0:
            split = {
                'own': round(100.0 * own_m / tot_split_m, 1),
                'customer': round(100.0 * cust_m / tot_split_m, 1),
                'third_party': round(100.0 * third_m / tot_split_m, 1),
                'pending': round(100.0 * pend_m / tot_split_m, 1),
                'own_min': round(own_m, 1),
                'customer_min': round(cust_m, 1),
                'third_party_min': round(third_m, 1),
                'pending_min': round(pend_m, 1),
            }
        else:
            split = None

        return {
            'id': entity_id,
            'name': name,
            'detail': detail,
            'site_count': count,
            'om_start_sites': om_count,
            'uptime_pct': uptime_val,
            'target': '> 98.5%',
            'gap': gap_val,
            'outage_min': outage_val,
            'status': status,
            'split': split,
        }

    all_rows = []

    if tab == 'circle':
        circle_groups = defaultdict(list)
        for i, c in enumerate(sub_sites['circle']):
            circle_groups[c].append(i)
        for c in sorted(circle_groups):
            all_rows.append(calc_row(c, c, '', circle_groups[c]))

    elif tab == 'ci':
        ci_groups = defaultdict(list)
        ci_meta = {}
        for i, (_, row) in enumerate(sub_sites.iterrows()):
            ci_name = str(row['ci_name'] or '').strip() or 'Unassigned'
            key = (ci_name, row['circle'])
            ci_groups[key].append(i)
            ci_meta[key] = (ci_name, row['circle'])
        for key in sorted(ci_groups, key=lambda k: (k[1], k[0])):
            ci_name, circle = ci_meta[key]
            all_rows.append(calc_row(f'{ci_name}___{circle}', ci_name, circle, ci_groups[key]))

    elif tab in ('ie', 'ne'):
        ie_groups = defaultdict(list)
        ie_meta = {}
        for i, (_, row) in enumerate(sub_sites.iterrows()):
            sk = str(row['site_id']).strip().upper()
            ie_name = ne_map.get(sk) or str(row['site_id']).strip()
            ie_groups[ie_name].append(i)
            ie_meta[ie_name] = (ie_name, f"{row['site_name']} · {row['circle']}")
        for ie_name in sorted(ie_groups):
            all_rows.append(calc_row(ie_name, ie_name, ie_meta[ie_name][1], ie_groups[ie_name]))

    elif tab == 'site':
        for i, (_, row) in enumerate(sub_sites.iterrows()):
            sid = str(row['site_id']).strip()
            all_rows.append(calc_row(sid, sid, f"{row['site_name']} · {row['circle']}", [i]))

    # Search filtering
    if search_q:
        all_rows = [
            r for r in all_rows
            if search_q in r['name'].casefold() or search_q in r['detail'].casefold() or search_q in r['id'].casefold()
        ]

    # Total row across all filtered rows
    total_sites = sum(r['site_count'] for r in all_rows)
    total_om = sum(r['om_start_sites'] for r in all_rows)
    total_outage = round(sum(r['outage_min'] for r in all_rows), 1)
    all_uptimes = [r['uptime_pct'] for r in all_rows if r['uptime_pct'] is not None]
    total_uptime = round(float(np.mean(all_uptimes)), 2) if all_uptimes else None
    total_gap = round(total_uptime - 98.5, 2) if total_uptime is not None else None
    total_status = 'N/A' if total_uptime is None else ('Meeting SLA' if total_uptime > 98.5 else 'Not Meeting SLA')

    # Total attribution split
    tot_own = tot_cust = tot_third = tot_pend = 0.0
    for r in all_rows:
        if r['split']:
            tot_own += r['split'].get('own_min', 0.0)
            tot_cust += r['split'].get('customer_min', 0.0)
            tot_third += r['split'].get('third_party_min', 0.0)
            tot_pend += r['split'].get('pending_min', 0.0)
    sum_m = tot_own + tot_cust + tot_third + tot_pend
    total_split = {
        'own': round(100.0 * tot_own / sum_m, 1),
        'customer': round(100.0 * tot_cust / sum_m, 1),
        'third_party': round(100.0 * tot_third / sum_m, 1),
        'pending': round(100.0 * tot_pend / sum_m, 1),
        'own_min': round(tot_own, 1),
        'customer_min': round(tot_cust, 1),
        'third_party_min': round(tot_third, 1),
        'pending_min': round(tot_pend, 1),
    } if sum_m > 0 else None

    total_row = {
        'id': 'TOTAL',
        'name': 'Total',
        'detail': f'{len(all_rows)} {tab} records',
        'site_count': total_sites,
        'om_start_sites': total_om,
        'uptime_pct': total_uptime,
        'target': '> 98.5%',
        'gap': total_gap,
        'outage_min': total_outage,
        'status': total_status,
        'split': total_split,
    }

    # Pagination for NE and Site tabs (or all tabs if many rows)
    total_count = len(all_rows)
    total_pages = max(math.ceil(total_count / page_size), 1)
    if tab in ('ne', 'site'):
        start_idx = (page - 1) * page_size
        paged_rows = all_rows[start_idx:start_idx + page_size]
    else:
        # circle and ci have <= 50 rows, return all
        paged_rows = all_rows

    return {
        'tab': tab,
        'kpis': kpis,
        'count': total_count,
        'page': page,
        'page_size': page_size,
        'pages': total_pages,
        'rows': paged_rows,
        'total_row': total_row,
    }
