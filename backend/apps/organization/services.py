"""Read side of the organization, used by every module that needs projects, circles or circle aliases.

- ``catalog()``: projects, circles and their associations for selectors and validation.
- ``AliasResolver``: a source's circle code or name to the canonical circle code, within the project when known.
  Unknown codes resolve to None: they are reported, never turned into new circles.
- ``check_pairs()``: which project/circle pairs of an import are not set up in the organization.
- ``record()``: one entry in the change history.
"""
from __future__ import annotations

import re

from django.db.models import Count

from .models import Circle, CircleAlias, OrganizationChange, Project, ProjectCircle


EMPTY_USAGE = {'sites': 0, 'on_air_sites': 0, 'daily': 0, 'monthly': 0, 'uploads': 0, 'rca': 0, 'rca_expected': 0, 'escalation': 0, 'users': 0}


def alias_key(raw: str) -> str:
    return re.sub(r'\s+', ' ', str(raw or '').strip()).casefold()


# --- Catalog ---------------------------------------------------------------------------------------

def project_keys(active_only: bool = False) -> list[str]:
    qs = Project.objects.all()
    if active_only:
        qs = qs.filter(is_active=True)
    return list(qs.values_list('key', flat=True))


def circle_codes(active_only: bool = False) -> set[str]:
    qs = Circle.objects.all()
    if active_only:
        qs = qs.filter(is_active=True)
    return set(qs.values_list('code', flat=True))


def associations(active_only: bool = True) -> list[tuple[str, str]]:
    """(project key, circle code) pairs; active ones only need an active project, circle and association."""
    qs = ProjectCircle.objects.select_related('project', 'circle')
    if active_only:
        qs = qs.filter(is_active=True, project__is_active=True, circle__is_active=True)
    return [(pc.project.key, pc.circle.code) for pc in qs]


def is_associated(project: str, circle: str, active_only: bool = True) -> bool:
    return (project, circle) in set(associations(active_only))


def catalog() -> dict:
    """What every portal user may know about the organization (no user access, no history)."""
    projects = list(Project.objects.all())
    circles = list(Circle.objects.all())
    links = list(ProjectCircle.objects.select_related('project', 'circle'))
    return {
        'projects': [{'key': p.key, 'code': p.code, 'name': p.name, 'is_active': p.is_active} for p in projects],
        'circles': [{'code': c.code, 'name': c.name, 'is_active': c.is_active} for c in circles],
        'associations': [{'project': pc.project.key, 'circle': pc.circle.code,
                          'is_active': pc.is_active and pc.project.is_active and pc.circle.is_active} for pc in links],
    }


def merge_filter_options(options: dict) -> dict:
    """Dashboard filter options (built from the data) plus every active association, so a circle set up in the
    Organization is selectable for its projects before it has data. ``has_data`` tells them apart; nothing is counted
    for a circle without data. A circle with records stays listed for historical reporting even when its association
    is inactive or removed; ``configured_for`` lists the projects it is actively associated with."""
    active: dict[str, set[str]] = {}
    for project, circle in associations(active_only=True):
        active.setdefault(circle, set()).add(project)
    circles = {c['value']: {**c, 'has_data': True, 'data_report_types': c['report_types'], 'configured_for': sorted(active.get(c['value'], ()))}
               for c in options['circles']}
    for code, projects in active.items():
        if code in circles:
            circles[code]['report_types'] = sorted(set(circles[code]['report_types']) | projects)
        else:
            circles[code] = {'value': code, 'label': f'{code} (no data yet)', 'report_types': sorted(projects), 'data_report_types': [],
                             'site_count': 0, 'has_data': False, 'configured_for': sorted(projects)}
    types = {t['value']: {**t, 'has_data': True} for t in options['report_types']}
    for key in project_keys(active_only=True):
        types.setdefault(key, {'value': key, 'label': f'{key} (no data yet)', 'site_count': 0, 'has_data': False})
    order = {k: i for i, k in enumerate(project_keys())}
    return {**options, 'circles': [circles[c] for c in sorted(circles)],
            'report_types': sorted(types.values(), key=lambda t: (order.get(t['value'], len(order)), t['value']))}


# --- Circle aliases --------------------------------------------------------------------------------

class AliasResolver:
    """Canonical circle code of a circle as one source writes it. Loaded once per use (one file, one request)."""

    def __init__(self, source: str):
        self.source = source
        self.codes = {c.casefold(): c for c in Circle.objects.values_list('code', flat=True)}
        self.source_wide: dict[str, str] = {}
        self.per_project: dict[tuple[str, str], str] = {}
        for raw_key, code, project in (CircleAlias.objects.filter(source=source, is_active=True)
                                       .values_list('raw_key', 'circle__code', 'project__key')):
            if project:
                self.per_project[(project, raw_key)] = code
            else:
                self.source_wide[raw_key] = code

    def resolve(self, raw: str, project: str | None = None) -> str | None:
        """Project alias, then source-wide alias, then the canonical code itself; None when unknown."""
        key = alias_key(raw)
        if not key:
            return None
        if project and (project, key) in self.per_project:
            return self.per_project[(project, key)]
        if key in self.source_wide:
            return self.source_wide[key]
        return self.codes.get(key)

    def is_known(self, raw: str, project: str | None = None) -> bool:
        return self.resolve(raw, project) is not None


def alias_problems(aliases: list[CircleAlias] | None = None) -> dict[int, list[str]]:
    """Per alias id: why it needs attention (shadowed by a project alias, or written like another circle's code)."""
    rows = aliases if aliases is not None else list(CircleAlias.objects.select_related('project', 'circle'))
    codes = {c.casefold(): c for c in Circle.objects.values_list('code', flat=True)}
    active = [a for a in rows if a.is_active]
    problems: dict[int, list[str]] = {}
    for a in active:
        other = codes.get(a.raw_key)
        if other and other != a.circle.code:
            problems.setdefault(a.id, []).append(f'"{a.raw_code}" is also the code of circle {other}.')
        if a.project_id is None:
            for b in active:
                if b.project_id and b.source == a.source and b.raw_key == a.raw_key and b.circle_id != a.circle_id:
                    problems.setdefault(a.id, []).append(
                        f'For {b.project.key} the project alias maps "{a.raw_code}" to {b.circle.code} instead.')
    return problems


# --- Imports ---------------------------------------------------------------------------------------

def check_pairs(pairs) -> dict:
    """Project/circle pairs of an import that the organization does not cover (each blocks the import)."""
    pairs = sorted(set(pairs))
    projects = {p.key: p for p in Project.objects.all()}
    circles = {c.code: c for c in Circle.objects.all()}
    links = {(pc.project.key, pc.circle.code): pc for pc in ProjectCircle.objects.select_related('project', 'circle')}
    out = {'unknown_projects': [], 'unknown_circles': [], 'proposed_associations': [], 'inactive': []}
    for project, circle in pairs:
        if project not in projects:
            out['unknown_projects'].append(project)
        elif circle not in circles:
            out['unknown_circles'].append({'project': project, 'circle': circle})
        elif (project, circle) not in links:
            out['proposed_associations'].append({'project': project, 'circle': circle})
        elif not (links[(project, circle)].is_active and projects[project].is_active and circles[circle].is_active):
            out['inactive'].append({'project': project, 'circle': circle})
    out['unknown_projects'] = sorted(set(out['unknown_projects']))
    out['blocking'] = any(out[k] for k in ('unknown_projects', 'unknown_circles', 'proposed_associations'))
    return out


def blocking_message(check: dict) -> str:
    parts = []
    if check['unknown_projects']:
        parts.append('unknown project ' + ', '.join(check['unknown_projects']))
    if check['unknown_circles']:
        parts.append('circles not in the Organization: ' + ', '.join(f"{u['circle']} ({u['project']})" for u in check['unknown_circles']))
    if check['proposed_associations']:
        parts.append('circles not associated with their project: ' + ', '.join(f"{u['circle']} under {u['project']}"
                                                                              for u in check['proposed_associations']))
    return ('Set up the Organization first (Administration > Organization): ' + '; '.join(parts) + '.') if parts else ''


# --- Usage (what history refers to a project, circle or association) --------------------------------

def usage_by_pair() -> dict[tuple[str, str], dict]:
    """Sites, daily and monthly records, raw uploads, RCA records and expected RCA units, escalation-matrix sites and
    user grants per (project, circle). Zero means none stored."""
    from apps.rca.models import RcaRecord, RcaRequiredSubmission
    from apps.uptimedb.models import DataImportBatch, EscalationSite, SiteDailyPerformance, SiteMonthlyPerformance, UptimeSite

    from .models import UserCircleAccess

    out: dict[tuple[str, str], dict] = {}

    def add(rows, name, p='project', c='circle'):
        for r in rows:
            out.setdefault((r[p], r[c]), dict(EMPTY_USAGE))[name] = r['n']

    add(UptimeSite.objects.order_by().values('project', 'circle').annotate(n=Count('id')), 'sites')
    add(UptimeSite.objects.filter(on_air=True).order_by().values('project', 'circle').annotate(n=Count('id')), 'on_air_sites')
    add(SiteDailyPerformance.objects.order_by().values('site__project', 'site__circle').annotate(n=Count('id')), 'daily', 'site__project', 'site__circle')
    add(SiteMonthlyPerformance.objects.order_by().values('site__project', 'site__circle').annotate(n=Count('id')), 'monthly', 'site__project', 'site__circle')
    add(DataImportBatch.objects.filter(kind=DataImportBatch.Kind.RAW_DAILY_CSV).order_by().values('project', 'circle').annotate(n=Count('id')), 'uploads')
    add(RcaRecord.objects.order_by().values('project', 'circle').annotate(n=Count('id')), 'rca')
    add(RcaRequiredSubmission.objects.order_by().values('project', 'circle').annotate(n=Count('id')), 'rca_expected')
    add(EscalationSite.objects.order_by().values('project', 'circle').annotate(n=Count('id')), 'escalation')
    add(UserCircleAccess.objects.order_by().values('project_circle__project__key', 'project_circle__circle__code').annotate(n=Count('id')),
        'users', 'project_circle__project__key', 'project_circle__circle__code')
    return out


# --- History ---------------------------------------------------------------------------------------

def record(entity_type: str, entity, action: str, *, previous=None, new=None, actor=None, reason: str = '', label: str | None = None) -> None:
    OrganizationChange.objects.create(
        entity_type=entity_type, entity_id=str(getattr(entity, 'pk', entity)), entity_label=(label or str(entity))[:120],
        action=action, previous=previous, new=new, actor=actor if getattr(actor, 'pk', None) else None,
        actor_name=actor.get_username() if getattr(actor, 'pk', None) else 'system', reason=(reason or '')[:500])
