"""Shared rules of the BSNL Module: responsibility buckets, reporting periods, formatting and RCA rows.

Buckets (reference ``autoBucket`` / ``bucketOf``, adapted to the portal's approved RCA taxonomy, decision 17 Nov 2026):
an RCA record's approved Final Bucket (apps.rca.taxonomy) is mapped by RcaBucketMapping; a blank Final Bucket is
Unclassified; a Final Bucket outside the approved taxonomy or without a valid mapping is Unclassified too.

Periods (reference ``d1Start`` / ``weekRange``), on the portal's daily data instead of outage timestamps:
- D-1: the latest complete reporting date of the data (the reference uses the last full day of the dump).
- Weekly: the last Monday-Sunday week ending on or before the D-1 date.
- The previous period has the same length and ends the day before; month to date runs from the 1st of the period's
  month to the period end.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from apps.rca import taxonomy

from .classification import get_bucket_classification, load_bucket_mapping
from .models import Bucket

BUCKETS = (Bucket.OWN, Bucket.CUSTOMER, Bucket.THIRD_PARTY, Bucket.PENDING, Bucket.UNCLASSIFIED)
# The decision of 17 Nov 2026 (BSNL-attributable Final Buckets); seeded by migration 0002 and editable afterwards.
DEFAULT_CUSTOMER_FINALS = ('BSNL OFC', 'BSNL Media')
MONTHS = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')
DAILY_HOUR, WEEKLY_HOUR, WEEKLY_DAY = 9, 10, 0  # Daily 09:00 IST; Weekly Monday (weekday 0) 10:00 IST
TIMEZONE = 'Asia/Kolkata'


def bucket_map() -> dict[str, str]:
    """Load the normalized authoritative mapping once for a report/request."""
    return load_bucket_mapping()


def bucket_of(final_bucket: str, mapping: dict[str, str]) -> str:
    return get_bucket_classification(final_bucket, mapping).mapped_bucket


# --- Periods ---------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Period:
    start: date
    end: date  # inclusive

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def dates(self) -> list[date]:
        return [self.start + timedelta(days=i) for i in range(self.days)]

    def previous(self) -> 'Period':
        return Period(self.start - timedelta(days=self.days), self.start - timedelta(days=1))

    def month_to_date(self) -> 'Period':
        return Period(self.start.replace(day=1), self.end)


def d1_period(latest: date) -> Period:
    return Period(latest, latest)


def week_period(latest: date) -> Period:
    """Monday-Sunday week ending on the latest Sunday on or before ``latest`` (reference weekRange)."""
    sunday = latest - timedelta(days=(latest.weekday() + 1) % 7)
    return Period(sunday - timedelta(days=6), sunday)


def report_period(report_type: str, latest: date) -> Period:
    return d1_period(latest) if report_type == 'D-1' else week_period(latest)


# --- Formatting (reference fmt / dShort) -------------------------------------------------------------------------------

def fmt(value, decimals: int = 0) -> str:
    """Indian digit grouping (en-IN), '–' for no value."""
    if value is None or value != value:  # None or NaN
        return '–'
    text = f'{abs(float(value)):.{decimals}f}'
    whole, _, frac = text.partition('.')
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ','.join(groups + [tail])
    sign = '-' if float(value) < 0 and float(text) != 0 else ''
    return sign + whole + (f'.{frac}' if frac else '')


def whole_minutes(value: float | int | Decimal | None) -> int:
    """Round a non-negative outage duration to the nearest whole minute, with half minutes rounded up."""
    number = Decimal(str(value or 0))
    if not number.is_finite():
        return 0
    return int(number.quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def d_short(day: date) -> str:
    return f'{day.day} {MONTHS[day.month - 1]}'


def d_long(day: date) -> str:
    return f'{d_short(day)} {day.year}'


# --- RCA rows --------------------------------------------------------------------------------------------------------

def rca_rows(period: Period, *, circles: list[str] | None = None, projects: list[str] | None = None, pairs=None) -> list[dict]:
    """Active RCA records of the period (reporting_date within it), limited to circles / projects and to ``pairs``
    ((project, circle) the user may see; None = all). Each row carries its responsibility bucket and outage minutes."""
    from apps.accounts.access import pairs_q
    from apps.rca.models import RcaRecord

    qs = RcaRecord.objects.filter(reporting_date__gte=period.start, reporting_date__lte=period.end)
    if circles is not None:
        qs = qs.filter(circle__in=circles)
    if projects:
        qs = qs.filter(project__in=projects)
    if pairs is not None:
        qs = qs.filter(pairs_q(pairs, 'project', 'circle'))
    mapping = bucket_map()
    out = []
    for r in qs.order_by('reporting_date', 'site_key', 'occurrence', 'id').values(
            'id', 'reporting_date', 'project', 'circle', 'site_id', 'site_key', 'site_name', 'outage_minutes',
            'final_bucket', 'bucket_2', 'rca_text'):
        r['bucket'] = bucket_of(r['final_bucket'], mapping)
        r['hours'] = (r['outage_minutes'] or 0.0) / 60.0
        r['final'] = taxonomy.approved_final(r['final_bucket']) or (r['final_bucket'] or '').strip()
        r['cause'] = (r['bucket_2'] or '').strip() or r['final'] or 'Not specified'
        out.append(r)
    return out
