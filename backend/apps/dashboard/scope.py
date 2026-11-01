"""The dashboard dataset limited to a user's project/circle pairs.

Every dashboard endpoint computes from the dataset this returns, so KPIs, charts, tables, searches, filter options,
site details and exports of a restricted user only ever contain sites of their assigned pairs. Workbook-wide facts
(validation warnings, reference sheets) are left out of a restricted copy.
"""
from __future__ import annotations

import dataclasses

import numpy as np

from .workbook import Dataset


def _subset(ds: Dataset, mask: np.ndarray) -> Dataset:
    rows = mask.nonzero()[0]
    return dataclasses.replace(
        ds, sites=ds.sites.iloc[rows].reset_index(drop=True), outage=ds.outage[rows],
        monthly_outage=None if ds.monthly_outage is None else ds.monthly_outage[rows],
        daily_history=tuple({**h, 'outage': h['outage'][rows]} for h in ds.daily_history),
        warnings=(), reference_sheets=(), reference_formulas={}, _positions={})


def restrict(ds: Dataset, pairs: set[tuple[str, str]] | None) -> Dataset:
    if pairs is None:
        return ds
    key = frozenset(pairs)
    cache = ds._memo.setdefault('restricted', {})
    if key not in cache:
        sites = ds.sites
        cache[key] = _subset(ds, np.fromiter(((t, c) in key for t, c in zip(sites['report_type'], sites['circle'])),
                                            dtype=bool, count=len(sites)))
    return cache[key]


def restrict_team(ds: Dataset, group: str, name: str, project: str, circle: str) -> Dataset:
    """Only the sites of one CI or IE: the CI Name / IE Name on the site row (normalised as on CI & IE Performance, so
    "Unassigned" means no name) within one project and circle. A person is identified by all four values: the same
    name under another project or circle is another row of the NSLA table and is not included."""
    from .metrics import TEAM_COLUMNS, team_names
    key = (group, name, project, circle)
    cache = ds._memo.setdefault('team', {})
    if key not in cache:
        sites = ds.sites
        mask = ((team_names(sites[TEAM_COLUMNS[group]]) == name) & (sites['report_type'] == project) & (sites['circle'] == circle)).to_numpy()
        cache[key] = _subset(ds, mask)
    return cache[key]
