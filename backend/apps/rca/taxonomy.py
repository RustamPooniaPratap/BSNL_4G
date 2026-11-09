"""The approved RCA taxonomy (final, 4 Nov 2026): the 10 Final Buckets and the Sub Buckets (Bucket - 2) of each.

This module is the one definition of the taxonomy in the application. The upload validation (preview and import), the
manual record form, the RCA filters, summaries and reports, the Circle-wise Root Cause Breakdown and All KPI's read it
from here; the frontend receives it from the API (``classification()`` in the RCA options) and keeps no list of its own.
Names are exactly as approved, including "Natural Clamity" and "Ceragoan Radio".

A record is classified by its pair (Final Bucket, Sub Bucket), never by the Sub Bucket alone: "Fluctuation" is valid
under BSNL Media, DMW and HFCL.

Matching: leading and trailing spaces are ignored, and so is letter case. Nothing else: no punctuation or spelling
equivalence, no aliases. A value is never renamed, corrected or remapped; the record keeps the value as uploaded.

Validation (``resolve``):
- Final Bucket blank, or not one of the 10: the record is rejected.
- Sub Bucket of the record's own Final Bucket: approved.
- Sub Bucket that is an approved Sub Bucket of another Final Bucket only: a classification mismatch, the record is rejected.
- Sub Bucket blank, or not an approved Sub Bucket of any Final Bucket: a warning; the record is kept.
"""
from __future__ import annotations

from dataclasses import dataclass

APPROVED: dict[str, tuple[str, ...]] = {
    'IaaSP Power': ('CCU fault', 'EB power cut', 'Solar Panel fault', 'RM fail', 'MPPT issue', 'Contactor faulty', 'Power cable faulty',
                    'LVD issue', 'Backplane faulty', 'High V & Low V'),
    'IaaSP Others': ('Shadow issue', 'EB Cable fault', 'EB tx. Faulty', 'EB Bill not paid', 'IaaSP Theft', 'CT payment issue', 'Owner issue',
                     'Natural Clamity', 'Tech Delay', 'IaaSP Link'),
    'IaaSP Battery': ('Battery issue', 'BB Theft', 'Low back Up', 'BMS faulty'),
    'IaaSP OFC': ('Incremental Fibre',),
    'BSNL OFC': ('SSA OFC', 'BSNL OFC', 'ETR OFC', 'BBNL OFC', 'WTR OFC', 'NTR', 'CNTX', 'JCNL', 'Maha IT', 'Pace OFC'),
    'BSNL Media': ('Nokia mini link', 'NEC Mini link', 'CPAN issue', 'Maan Media issue', 'BSNL Link', 'Vsat Media', 'BSNL Hub', 'BSNL Others',
                   'Fluctuation'),
    'Others': ('4G Sat. link site', 'IP site link', 'Others site link', 'ATC site link', 'Non IaaSP Theft'),
    'TCS': ('RAC Card', 'CEF Card', 'CEF12 Card', 'FTU', 'RRH Hardware', 'RRH Cable', 'RRH Cipri Cable', 'BBU', 'Partial band', 'S1 Link'),
    'DMW': ('Ceragoan Radio', 'DMW Cipri Cable', 'DMW Power cable', 'DMW RSL Issue', 'DMW pole mount Issue', 'Fluctuation', 'Cascading Cable'),
    'HFCL': ('HFCL Radio', 'HFCL Switch', 'HFCL POE', 'HFCL Power cable', 'HFCL RSL Issue', 'HFCL Pole mount Issue', 'HFCL Port', 'HFCL MCX0',
             'Fluctuation'),
}
# Source placeholders for "no value" (as the parser treats them): never a category.
BLANK = {'', '-', '--', 'na', 'n/a', '#n/a', 'nil', 'null', 'none', '0'}


def match_key(value) -> str:
    """The comparison form of a value: leading and trailing spaces and letter case ignored, nothing else."""
    return str(value or '').strip().casefold()


_FINALS = {match_key(f): f for f in APPROVED}
_CHILDREN = {f: {match_key(c): c for c in children} for f, children in APPROVED.items()}
_OWNERS: dict[str, tuple[str, ...]] = {}
for _final, _children in APPROVED.items():
    for _child in _children:
        _OWNERS[match_key(_child)] = (*_OWNERS.get(match_key(_child), ()), _final)


@dataclass(frozen=True)
class Resolution:
    """The approved names a pair matches (None where it matches none) and its status; the values themselves are not changed."""
    final_bucket: str | None
    bucket_2: str | None
    status: str  # approved | final_only | unapproved | blank | mismatch
    # Final Buckets the Sub Bucket is approved under, when it is not approved under the record's own Final Bucket.
    other_final_buckets: tuple[str, ...] = ()


STATUS_LABELS = {
    'approved': 'Approved Final Bucket and Sub Bucket',
    'final_only': 'Approved Final Bucket; Sub Bucket is not one of its approved Sub Buckets',
    'unapproved': 'Final Bucket is not in the approved taxonomy',
    'blank': 'Final Bucket or Sub Bucket is blank',
}


def is_blank(value) -> bool:
    return match_key(value) in BLANK


def approved_final(value) -> str | None:
    """The approved Final Bucket a value is (spaces and case ignored), or None."""
    return None if is_blank(value) else _FINALS.get(match_key(value))


def is_approved_final(value) -> bool:
    return approved_final(value) is not None


def finals_of_sub_bucket(value) -> tuple[str, ...]:
    """The Final Buckets a Sub Bucket is approved under (empty when it is not an approved Sub Bucket)."""
    return () if is_blank(value) else _OWNERS.get(match_key(value), ())


def resolve(final_bucket, bucket_2) -> Resolution:
    """Classify a (Final Bucket, Sub Bucket) pair against the taxonomy (see the module notes)."""
    final = approved_final(final_bucket)
    if final is None:
        return Resolution(None, None, 'blank' if is_blank(final_bucket) else 'unapproved')
    if is_blank(bucket_2):
        return Resolution(final, None, 'blank')
    child = _CHILDREN[final].get(match_key(bucket_2))
    if child is not None:
        return Resolution(final, child, 'approved')
    owners = finals_of_sub_bucket(bucket_2)
    if owners:
        return Resolution(final, None, 'mismatch', owners)
    return Resolution(final, None, 'final_only')


def count_status(status: str) -> str:
    """The classification count a status belongs to (STATUS_LABELS): a mismatch counts with the unapproved Sub Buckets."""
    return 'final_only' if status == 'mismatch' else status


def status_label(status: str) -> str:
    if status == 'mismatch':
        return 'Sub Bucket belongs to another Final Bucket (classification mismatch)'
    return STATUS_LABELS[status]


def classification() -> list[dict]:
    """The approved taxonomy for the API: the frontend's dropdowns and filters use this list and keep no list of their own."""
    return [{'final_bucket': f, 'bucket_2': list(children)} for f, children in APPROVED.items()]
