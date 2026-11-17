"""Application-wide responsibility classification from the BSNL Final Bucket mapping."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from apps.rca import taxonomy

from .models import Bucket, RcaBucketMapping

logger = logging.getLogger(__name__)
UNCLASSIFIED = 'Unclassified'


@dataclass(frozen=True)
class BucketClassification:
    ownership: str
    bucket_2: str
    mapped_bucket: str


def normalize_responsibility_bucket(value) -> str | None:
    key = re.sub(r'\s+', '', str(value or '')).casefold()
    return next((choice for choice in (*Bucket.values, UNCLASSIFIED)
                 if re.sub(r'\s+', '', choice).casefold() == key), None)


def load_bucket_mapping() -> dict[str, str]:
    """Load valid normalized Final Bucket keys once for the current request."""
    mapping: dict[str, str] = {}
    conflicts: set[str] = set()
    for final_bucket, bucket in RcaBucketMapping.objects.order_by('pk').values_list('final_bucket', 'bucket'):
        final = taxonomy.approved_final(final_bucket)
        responsibility = normalize_responsibility_bucket(bucket)
        if final is None or responsibility is None:
            logger.warning('Ignoring invalid RCA responsibility mapping for Final Bucket %r.', final_bucket)
            continue
        key = taxonomy.match_key(final)
        existing = mapping.get(key)
        if existing is not None and existing != responsibility:
            conflicts.add(key)
            logger.warning('Conflicting RCA responsibility mappings exist for Final Bucket %r.', final)
        else:
            mapping[key] = responsibility
    for key in conflicts:
        mapping.pop(key, None)
    return mapping


def get_bucket_classification(final_bucket, mapping: dict[str, str] | None = None) -> BucketClassification:
    """Resolve both responsibility fields from the same current mapping; invalid or missing values are Unclassified."""
    canonical = taxonomy.approved_final(final_bucket)
    resolved = (mapping if mapping is not None else load_bucket_mapping()).get(taxonomy.match_key(canonical), UNCLASSIFIED) \
        if canonical else UNCLASSIFIED
    if normalize_responsibility_bucket(resolved) is None:
        resolved = UNCLASSIFIED
    return BucketClassification(ownership=resolved, bucket_2=resolved, mapped_bucket=resolved)


def mapping_for_approved_finals(mapping: dict[str, str] | None = None) -> dict[str, str]:
    """Return canonical labels and their resolved categories for legacy BSNL consumers."""
    source = mapping if mapping is not None else load_bucket_mapping()
    return {final: get_bucket_classification(final, source).mapped_bucket for final in taxonomy.APPROVED}


def responsibility_buckets() -> tuple[str, ...]:
    return (*Bucket.values, UNCLASSIFIED)


def responsibility_label(bucket: str) -> str:
    return 'Third Party' if normalize_responsibility_bucket(bucket) == Bucket.THIRD_PARTY else bucket


def responsibility_options() -> list[dict[str, str]]:
    return [{'value': bucket, 'label': responsibility_label(bucket)} for bucket in responsibility_buckets()]


def filter_by_responsibility(queryset, selected, mapping: dict[str, str] | None = None):
    """Filter a queryset by current responsibility mapping without querying once per RCA record."""
    requested = {normalized for value in selected if (normalized := normalize_responsibility_bucket(value))}
    if not requested:
        return queryset.none()
    source = mapping if mapping is not None else load_bucket_mapping()
    final_keys = queryset.order_by().values_list('final_bucket_key', flat=True).distinct()
    matching = [key for key in final_keys if get_bucket_classification(key, source).mapped_bucket in requested]
    return queryset.filter(final_bucket_key__in=matching) if matching else queryset.none()


def grouped_responsibility_totals(queryset, mapping: dict[str, str] | None = None) -> dict[str, dict[str, float | int]]:
    """Aggregate RCA counts and original outage minutes by current mapped responsibility."""
    from django.db.models import Count, Sum

    source = mapping if mapping is not None else load_bucket_mapping()
    totals = {bucket: {'records': 0, 'outage_minutes': 0.0} for bucket in responsibility_buckets()}
    for row in queryset.order_by().values('final_bucket_key').annotate(records=Count('id'), minutes=Sum('outage_minutes')):
        bucket = get_bucket_classification(row['final_bucket_key'], source).mapped_bucket
        totals[bucket]['records'] += row['records']
        totals[bucket]['outage_minutes'] += row['minutes'] or 0.0
    return totals
