"""The data of every 4G / LWE dashboard page: the new data layer (sitedata), never the old uptimedb tables.

Used by the Dashboard (4G / LWE overview), Threshold Analysis, Buckets and site records, the CI / IE and Top Performer
pages, the exports, All KPI's and Site Portfolio, so the same sites, dates and rules apply everywhere:

- sites and their attributes: the Consolidation Matrix (sitedata_site, dashboard reporting scope);
- daily values: sitedata_dailysiteperformance (source precedence applied at import: correction > Uptime Master > raw
  CSV); monthly history: sitedata_monthlysiteperformance and the daily records of earlier months;
- reporting month: the latest month whose 1st is complete (dataset.reporting_month); MTD: the continuous run of
  complete dates (portfolio.continuous);
- On-Air and O&M Start: each site counts from its matrix effective date. The scope picks the variant of the dataset:
  "on_air" and "om_start" leave out a site's values before its date (portfolio.VARIANTS); every other scope uses "all".

The calculations are the shared dashboard.metrics functions. When the new layer has no data the page shows the error;
nothing falls back to another source.
"""
from __future__ import annotations

from apps.dashboard.scope import restrict
from apps.dashboard.workbook import Dataset

from . import portfolio

SOURCE_LABEL = portfolio.SOURCE_LABEL


def load(variant: str = 'all') -> Dataset:
    """The unrestricted dataset of the new layer for "all", "on_air" or "om_start" (the one entry point)."""
    return portfolio.portfolio_dataset(variant)


def variant_of(scope: str | None) -> str:
    return scope if scope in portfolio.VARIANTS else 'all'


def dataset(pairs=None, scope: str | None = None) -> Dataset:
    """The dataset for a user's project / circle pairs (None: all) and a scope, with the continuous complete reporting
    dates of the "all" variant (so every scope uses the same dates)."""
    base = portfolio.continuous(restrict(load('all'), pairs))
    variant = variant_of(scope)
    if variant == 'all':
        return base
    return portfolio.with_dates_of(restrict(load(variant), pairs), base)


def continuity(ds: Dataset) -> dict:
    return portfolio.continuity(ds)
