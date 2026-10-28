"""Compare the overlapping sites of two parsed workbooks (e.g. the consolidated file and the RJ, MP & OD report).

Nothing is merged here: the result lists every difference so a user can choose which file's
values to apply. A value present in one file and empty in the other is a difference too.
"""
from __future__ import annotations

from .parser import MONTH_FIELDS, ParsedWorkbook

ATTRIBUTE_FIELDS = ('site_name', 'oa', 'ba', 'on_air_raw', 'eb', 'od_eb_working_status', 'solar_logic_done',
                    'ie_name', 'ie_contact', 'ci_name', 'ci_contact')
MAX_EXAMPLES = 25


def _differs(a, b) -> bool:
    if isinstance(a, float) and isinstance(b, float):
        return abs(a - b) > 1e-6
    return a != b


def compare(primary: ParsedWorkbook, other: ParsedWorkbook) -> dict:
    projects = {s['project'] for s in other.sites.values()}
    keys_primary = {k for k in primary.sites if k[0] in projects}
    keys_other = set(other.sites)
    overlap = sorted(keys_primary & keys_other)
    fields: dict[str, dict] = {}
    conflicting_sites = set()

    def record(field: str, key, a, b, where: str = ''):
        entry = fields.setdefault(field, {'count': 0, 'examples': []})
        entry['count'] += 1
        conflicting_sites.add(key)
        if len(entry['examples']) < MAX_EXAMPLES:
            entry['examples'].append({'project': key[0], 'circle': key[1], 'site_id': primary.sites[key]['site_id'],
                                      'where': where, 'primary': a, 'reconciliation': b})

    for key in overlap:
        a_site, b_site = primary.sites[key], other.sites[key]
        for name in ATTRIBUTE_FIELDS:
            if _differs(a_site[name], b_site[name]):
                record(f'site.{name}', key, a_site[name], b_site[name])
        a_months, b_months = primary.monthly[key], other.monthly[key]
        for month in sorted(set(a_months) & set(b_months)):
            for name in MONTH_FIELDS:
                if name == 'om_start':
                    continue  # follows om_start_raw
                if _differs(a_months[month][name], b_months[month][name]):
                    label = month.strftime('%b-%y')
                    record(f'monthly.{label}.{name}', key, a_months[month][name], b_months[month][name], label)
        a_days, b_days = primary.daily[key], other.daily[key]
        for day in sorted(set(a_days) & set(b_days)):
            if _differs(a_days[day][0], b_days[day][0]):
                record(f"daily.{day.strftime('%b-%y')}.outage_minutes", key, a_days[day][0], b_days[day][0], day.isoformat())

    only_dates = sorted({d.isoformat() for k in overlap for d, (o, _) in other.daily[k].items()
                         if o is not None and primary.daily[k].get(d, (None,))[0] is None})
    return {
        'primary': primary.filename,
        'reconciliation': other.filename,
        'overlapping_sites': len(overlap),
        'only_in_primary': len(keys_primary - keys_other),
        'only_in_reconciliation': len(keys_other - keys_primary),
        'sites_with_differences': len(conflicting_sites),
        'differences': dict(sorted(fields.items(), key=lambda kv: -kv[1]['count'])),
        # Dates with values in the second file that the primary file leaves empty (e.g. one more reported day).
        'dates_only_in_reconciliation': only_dates,
    }
