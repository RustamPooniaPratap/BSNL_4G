"""The dashboard dataset limited to a user's project/circle pairs.

Every dashboard endpoint computes from the dataset this returns, so KPIs, charts, tables, searches, filter options,
site details and exports of a restricted user only ever contain sites of their assigned pairs. Workbook-wide facts
(validation warnings, reference sheets) are left out of a restricted copy.
"""
from __future__ import annotations

import dataclasses

import numpy as np

from .workbook import Dataset


def restrict(ds: Dataset, pairs: set[tuple[str, str]] | None) -> Dataset:
    if pairs is None:
        return ds
    key = frozenset(pairs)
    cache = ds._memo.setdefault('restricted', {})
    if key not in cache:
        sites = ds.sites
        mask = np.fromiter(((t, c) in key for t, c in zip(sites['report_type'], sites['circle'])), dtype=bool, count=len(sites))
        rows = mask.nonzero()[0]
        cache[key] = dataclasses.replace(
            ds, sites=sites.iloc[rows].reset_index(drop=True), outage=ds.outage[rows],
            monthly_outage=None if ds.monthly_outage is None else ds.monthly_outage[rows],
            daily_history=tuple({**h, 'outage': h['outage'][rows]} for h in ds.daily_history),
            warnings=(), reference_sheets=(), reference_formulas={}, _positions={})
    return cache[key]
