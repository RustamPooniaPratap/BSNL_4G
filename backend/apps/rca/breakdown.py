"""Circle-wise Root Cause Breakdown (RCA Summary): RCA records per circle and Final Bucket reporting category.

The layout follows the RCA workbook's "RCA Analysis - Updated" table. In the workbook every column counts the
"RCA Backup" rows whose **Final Bucket** equals the column header with "-" read as a space, ignoring case
(COUNTIFS), and BSNL-Link counted the "Iaasp Link" rows, which the Iaasp Link column also counts (the same records
twice). Rules here:

- ``FINAL_BUCKET_CATEGORIES`` is the one mapping from Final Bucket (case and spacing ignored, ``parser.text_key``)
  to a column. It holds the workbook rule for each column plus the equivalents confirmed on 29 Oct 2026:
  Above 98.5% / Others / Other Media / NC -> Others; BSNL OFC / SSA OFC -> BSNL OFC; BBNL Media / BBNL OFC -> BBNL OFC;
  Iaasp Others / Iaasp Other -> Iaasp Others. Nothing else is inferred from similar spelling.
- A record is counted in one column only. BSNL-Link is shown but left empty (pending the updated workbook), because
  its workbook rule conflicts with Iaasp Link.
- Final Bucket values that map to no column (and blank values) are never put in Others: they are counted under
  "Not mapped", listed with their raw values, and kept out of the Grand Total, so every record is accounted for.
- Rows: one per circle (projects combined, as the workbook keys rows on the circle), for every circle of the selected
  project in the site master and every circle with records. A circle without records has empty cells, not zeros.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from django.db.models import Count, Max, QuerySet

from .parser import text_key

# (column label, Final Bucket values counted in it, as written in the workbook or confirmed). None: shown, not filled.
COLUMNS: tuple[tuple[str, tuple[str, ...] | None], ...] = (
    ('PTPL-Battery', ('PTPL Battery',)),
    ('PTPL-OFC', ('PTPL OFC',)),
    ('PTPL-Techn', ('PTPL Techn',)),
    ('PTPL-Others', ('PTPL Others',)),
    ('BSNL-OFC', ('BSNL OFC', 'SSA OFC')),
    ('BSNL-Media', ('BSNL Media',)),
    ('BSNL-Link', None),  # the workbook counts "Iaasp Link" here and again under Iaasp Link: pending the updated workbook
    ('BSNL-Others', ('BSNL Others',)),
    ('BBNL-OFC', ('BBNL OFC', 'BBNL Media')),
    ('DMW', ('DMW',)),
    ('HFCL', ('HFCL',)),
    ('Iaasp Link', ('Iaasp Link',)),
    ('Iaasp OFC', ('Iaasp OFC',)),
    ('Iaasp Others', ('Iaasp Others', 'Iaasp Other')),
    ('Iaasp Power', ('Iaasp Power',)),
    ('TCS', ('TCS',)),
    ('Tech Delay', ('Tech Delay',)),
    ('Theft', ('Theft',)),
    ('Vsat', ('Vsat',)),
    ('Others', ('Others', 'Other Media', 'Above 98.5%', 'NC')),
)
PENDING = tuple(label for label, values in COLUMNS if values is None)
FINAL_BUCKET_CATEGORIES: dict[str, str] = {text_key(value): label for label, values in COLUMNS if values for value in values}
NOT_MAPPED = 'Not mapped'
BLANK_LABEL = '(blank)'


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
