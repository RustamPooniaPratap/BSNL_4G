"""The approved RCA bucketization (confirmed 30 Oct 2026): each Final Bucket and its valid sub-buckets (Bucket - 2).

This module is the one place the classification is kept. The importer, the correction command, the RCA filters and the
summaries read it from here; no workbook is needed at runtime.

A record is classified by its pair (Final Bucket, Bucket - 2), never by the sub-bucket alone: "Fluctuation" is valid
under BSNL Media, DMW and HFCL. Names are kept exactly as approved.

Matching (``resolve``) is deliberately narrow. A source value matches an approved name only when the two are equal
ignoring case, spaces and punctuation ("Iaasp Power" is "IaaSP Power", "BSNL-OFC" is "BSNL OFC"). A sub-bucket is
matched only within its own approved Final Bucket. Anything else (typos, other words, a sub-bucket under another
parent, blanks) is left as written and reported, never reassigned or put in Others.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

APPROVED: dict[str, tuple[str, ...]] = {
    'IaaSP Power': ('CCU fault', 'EB power cut', 'Solar Panel fault', 'RM fail', 'MPPT issue', 'Contactor faulty', 'Power cable faulty',
                    'LVD issue', 'Backplane faulty', 'High V & Low V'),
    'IaaSP Others': ('Shadow issue', 'EB Cable fault', 'EB tx. Faulty', 'EB Bill not paid', 'IaaSP Theft', 'CT payment issue', 'Owner issue',
                     'Natural Calamity', 'Tech Delay', 'IaaSP Link'),
    'IaaSP Battery': ('Battery issue', 'BB Theft', 'Low back Up', 'BMS faulty'),
    'IaaSP OFC': ('Incremental Fibre',),
    'BSNL OFC': ('SSA OFC', 'BSNL OFC', 'ETR OFC', 'BBNL OFC', 'WTR OFC', 'NTR', 'CNTX', 'JCNL', 'Maha IT', 'Pace OFC'),
    'BSNL Media': ('Nokia mini link', 'NEC Mini link', 'CPAN issue', 'Maan Media issue', 'BSNL Link', 'Vsat Media', 'BSNL Hub', 'BSNL Others',
                   'Fluctuation'),
    'Others': ('4G Sat. link site', 'IP site link', 'Others site link', 'ATC site link', 'Non IaaSP Theft'),
    'TCS': ('RAC Card', 'CEF Card', 'CEF12 Card', 'FTU', 'RRH Hardware', 'RRH Cable', 'RRH Cipri Cable', 'BBU', 'Partial band', 'S1 Link'),
    'DMW': ('Ceragon Radio', 'DMW Cipri Cable', 'DMW Power cable', 'DMW RSL Issue', 'DMW pole mount Issue', 'Fluctuation', 'Cascading Cable'),
    'HFCL': ('HFCL Radio', 'HFCL Switch', 'HFCL POE', 'HFCL Power cable', 'HFCL RSL Issue', 'HFCL Pole mount Issue', 'HFCL Port', 'HFCL MCX0',
             'Fluctuation'),
}
# Source placeholders for "no value" (as the parser treats them): never a category.
BLANK = {'', '-', '--', 'na', 'n/a', '#n/a', 'nil', 'null', 'none', '0'}


def match_key(value: str) -> str:
    """Case, spaces and punctuation ignored: the only equivalence the classification applies."""
    return re.sub(r'[^0-9a-z&]+', '', str(value or '').casefold())


_FINALS = {match_key(f): f for f in APPROVED}
_CHILDREN = {f: {match_key(c): c for c in children} for f, children in APPROVED.items()}


@dataclass(frozen=True)
class Resolution:
    final_bucket: str
    bucket_2: str
    status: str  # approved | final_only | unapproved | blank


STATUS_LABELS = {
    'approved': 'Approved Final Bucket and Bucket - 2',
    'final_only': 'Approved Final Bucket; Bucket - 2 is not one of its approved sub-buckets',
    'unapproved': 'Final Bucket is not in the approved classification',
    'blank': 'Final Bucket or Bucket - 2 is blank',
}


def is_blank(value: str) -> bool:
    return str(value or '').strip().casefold() in BLANK


def resolve(final_bucket: str, bucket_2: str) -> Resolution:
    """The approved spelling of a pair where it matches exactly (see the module notes); otherwise the values as written."""
    final = _FINALS.get(match_key(final_bucket)) if not is_blank(final_bucket) else None
    if final is None:
        status = 'blank' if is_blank(final_bucket) else 'unapproved'
        return Resolution(final_bucket, bucket_2, status)
    child = _CHILDREN[final].get(match_key(bucket_2)) if not is_blank(bucket_2) else None
    if child is None:
        return Resolution(final, bucket_2, 'blank' if is_blank(bucket_2) else 'final_only')
    return Resolution(final, child, 'approved')


def is_approved_final(value: str) -> bool:
    return match_key(value) in _FINALS and not is_blank(value)


def classification() -> list[dict]:
    """The approved classification for the API (filters and the frontend never keep their own list)."""
    return [{'final_bucket': f, 'bucket_2': list(children)} for f, children in APPROVED.items()]
