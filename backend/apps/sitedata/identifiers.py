"""Identifier keys and resolution of raw identifiers to one Site."""
from __future__ import annotations

import re

from .models import IdentifierConflict, LweMappingIdentifier, Site, SiteIdentifier


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

    def _programme(self):
        """Every identifier key the programme knows, whatever its kind: key -> sites (sitedata_siteidentifier), and the
        keys of sitedata_identifierconflict (active or resolved) and of the LWE mapping history
        (sitedata_lwemappingidentifier). Loaded on first use."""
        if not hasattr(self, '_by_key'):
            self._by_key: dict[str, set[int]] = {}
            for key, site_id in SiteIdentifier.objects.values_list('key', 'site_id'):
                self._by_key.setdefault(key, set()).add(site_id)
            self._conflict_keys = set(IdentifierConflict.objects.values_list('key', flat=True))
            self._history_keys = set(LweMappingIdentifier.objects.values_list('key', flat=True).distinct())
        return self._by_key, self._conflict_keys, self._history_keys

    def sites_of_key(self, raw) -> list[Site]:
        """Sites holding the key as an identifier of any kind (deterministic order)."""
        by_key, _, _ = self._programme()
        return [self.sites[i] for i in sorted(by_key.get(key_of(raw), ()))]

    def known_where(self, raw) -> str:
        """Why the key is known to the programme without naming a site ('' when it is not known at all)."""
        key = key_of(raw)
        _, conflicts, history = self._programme()
        if key in conflicts:
            return 'an identifier conflict of the Consolidation Matrix'
        if key in history:
            return 'an LWE Band ID mapping (earlier or rejected row)'
        return ''
