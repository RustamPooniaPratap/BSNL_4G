"""Project-specific resolution of a raw identifier to one approved master site (UptimeSite).

The site master in PostgreSQL is authoritative: a raw row is importable only if its identifier resolves to exactly
one master site of the selected project and circle. Master sites are never created here.

- 4G Saturation: the raw ``BTS IP ID`` is the master ``btsIpId`` (verified on the Odisha daily dump: 1,543 of the
  1,603 master OD sites appear under the same ID). Matching uses the master's normalised key.
- LWE: the raw IDs (e.g. JHDTJN001) differ from the master IDs (LWEJH0001) and the authoritative mapping and any
  2100 / 700 MHz band-selection rule have not been supplied, so every LWE row resolves to "mapping not configured".
  Supplying the mapping means implementing ``LweResolver.resolve``; the rest of the pipeline is shared.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..models import UptimeSite


def site_key(raw: str) -> str:
    """The master's matching key: trimmed, upper case, inner spaces collapsed (as UptimeSite.site_key)."""
    return re.sub(r'\s+', ' ', (raw or '').strip()).upper()


@dataclass(frozen=True)
class Resolution:
    site: UptimeSite | None
    code: str | None  # None when resolved; otherwise a reason code
    message: str = ''


class SiteResolver:
    """Resolve raw identifiers of one project and circle against the site master."""
    configured = True

    def __init__(self, project: str, circle: str):
        self.project, self.circle = project, circle

    def scope_size(self) -> int:
        return UptimeSite.objects.filter(project=self.project, circle=self.circle).count()

    def resolve(self, raw_id: str) -> Resolution:  # pragma: no cover - interface
        raise NotImplementedError


class FourGResolver(SiteResolver):
    def __init__(self, project: str, circle: str):
        super().__init__(project, circle)
        self._by_key: dict[str, list[UptimeSite]] = {}
        for site in UptimeSite.objects.only('id', 'project', 'circle', 'site_id', 'site_key', 'site_name'):
            self._by_key.setdefault(site.site_key, []).append(site)

    def resolve(self, raw_id: str) -> Resolution:
        key = site_key(raw_id)
        if not key:
            return Resolution(None, 'blank_site_id', 'BTS IP ID is blank.')
        candidates = self._by_key.get(key, [])
        in_scope = [s for s in candidates if s.project == self.project and s.circle == self.circle]
        if len(in_scope) == 1:
            return Resolution(in_scope[0], None)
        if len(in_scope) > 1:
            return Resolution(None, 'ambiguous_site', f'{raw_id} matches {len(in_scope)} master sites; none is chosen.')
        same_project = [s for s in candidates if s.project == self.project]
        if same_project:
            circles = ', '.join(sorted({s.circle for s in same_project}))
            return Resolution(None, 'other_circle', f'{raw_id} is a {self.project} site of circle {circles}, not {self.circle}.')
        if candidates:
            projects = ', '.join(sorted({s.project for s in candidates}))
            return Resolution(None, 'other_project', f'{raw_id} is a master site of {projects}, not {self.project}.')
        return Resolution(None, 'unknown_site', f'{raw_id} is not in the approved {self.project} site master (outside the project scope).')


class LweResolver(SiteResolver):
    """Not configured: the authoritative LWE ID mapping and band-selection rules are pending."""
    configured = False

    def resolve(self, raw_id: str) -> Resolution:
        if not site_key(raw_id):
            return Resolution(None, 'blank_site_id', 'BTS IP ID is blank.')
        return Resolution(None, 'lwe_mapping_not_configured',
                          'The LWE identifier mapping (raw BTS IP ID to master LWE site ID, and the 2100 / 700 MHz selection) '
                          'is not configured yet, so LWE rows cannot be imported.')


RESOLVERS = {'4G Saturation': FourGResolver, 'LWE': LweResolver}


def resolver_for(project: str, circle: str) -> SiteResolver:
    return RESOLVERS[project](project, circle)
