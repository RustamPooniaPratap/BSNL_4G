"""Identifier keys and resolution of raw identifiers to one Site."""
from __future__ import annotations

import re

from .models import IdentifierConflict, Site, SiteIdentifier


SEPARATOR = ';;'
VALID = re.compile(r'^(?=.*[A-Za-z0-9])[A-Za-z0-9._/-]+$')
# Placeholders written in empty cells (the same set the existing workbook parser treats as empty).
PLACEHOLDERS = {'-', '--', 'na', 'n/a', '#n/a', 'nil', 'null', 'none'}


def key_of(raw) -> str:
    """Matching key: trimmed, upper case, inner spaces collapsed (as the existing site keys)."""
    return re.sub(r'\s+', ' ', str(raw or '').strip()).upper()


def split_ids(cell) -> list[str]:
    """The identifiers of one cell (confirmed 4 Nov 2026): split on ";;", trim, drop empty tokens, keep every distinct
    identifier (first spelling). Placeholders such as "-" or "NA" are empty. A token with any other separator (e.g. a single
    ";") stays as written and is invalid."""
    out, seen = [], set()
    for token in str(cell or '').split(SEPARATOR):
        token = token.strip()
        if token and token.casefold() not in PLACEHOLDERS and key_of(token) not in seen:
            seen.add(key_of(token))
            out.append(token)
    return out


def is_valid_id(token: str) -> bool:
    """Letters, digits and . _ / - only (no separator left, no inner spaces)."""
    return bool(VALID.match(token))


class IdentifierIndex:
    """All identifiers in memory: (kind, key) -> Site, and the blocked (ambiguous) identifiers. Built once per analysis.
    A blocked identifier never resolves to a site."""

    def __init__(self):
        sites = {s.pk: s for s in Site.objects.all()}
        self.blocked: set[tuple[str, str]] = set(IdentifierConflict.objects.filter(active=True).values_list('kind', 'key'))
        self.by_kind: dict[tuple[str, str], Site] = {}
        for kind, key, site_id in SiteIdentifier.objects.values_list('kind', 'key', 'site_id'):
            if (kind, key) not in self.blocked:
                self.by_kind[(kind, key)] = sites[site_id]
        self.sites = sites

    def get(self, kind: str, raw) -> Site | None:
        return self.by_kind.get((kind, key_of(raw)))

    def is_blocked(self, kind: str, raw) -> bool:
        return (kind, key_of(raw)) in self.blocked
