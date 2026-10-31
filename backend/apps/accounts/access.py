"""Permission resolution: may this user do (module, action), and on which project/circle pairs?

Rules (checked on the server for every request; the frontend only uses the answers to choose what to show):

1. The user must be signed in and active.
2. Admin: every module and action of the catalogue, every project and circle (plus the Admin-only pages).
   NOC Lead: the fixed NOC Lead permissions on every project and circle.
3. Everyone else: only active assignments grant anything. An assignment grants its role's (module, action)
   permissions on its scope: one circle of a project, or the entire project (every circle associated with that
   project in Organization). Nothing else: no assignment means no access.
4. An assignment does not grant when it is inactive, past its ``valid_until`` date, its role is inactive, its project
   is inactive, or (for a circle assignment) its project/circle association or circle is inactive.
5. Permissions combine per pair only: (module, action) is allowed on a pair when one applicable assignment covering
   that pair grants it. A project-wide View therefore never gives Upload/Edit/Export; a circle-specific editor role adds
   its permissions to that circle only. There are no deny rules, so nothing can be "bypassed" by another assignment;
   to restrict a user, remove or deactivate the assignment that grants too much.
6. Data whose project/circle is not associated in Organization is never inside a restricted user's scope.

Results are cached on the user object for the current request only, so changes apply on the next request.
"""
from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Q
from django.utils import timezone

from . import catalog
from .roles import ADMIN, NOC_LEAD, role_of

Pair = tuple[str, str]
_CACHE = '_portal_access_cache'


@dataclass(frozen=True)
class Grant:
    module: str
    action: str
    project: str
    circle: str
    assignment: int
    role: str
    project_wide: bool


def forget(user) -> None:
    """Drop the cached grants (after changing the user's assignments within the same request or test)."""
    if user is not None:
        user.__dict__.pop(_CACHE, None)


def assignment_problem(a) -> str:
    """Why an assignment grants nothing today ('' when it applies)."""
    if a.status != a.Status.ACTIVE:
        return 'Assignment inactive'
    if a.valid_until and a.valid_until < timezone.localdate():
        return f'Expired on {a.valid_until.isoformat()}'
    if not a.role.is_active:
        return 'Role inactive'
    if not a.project.is_active:
        return 'Project inactive'
    pc = a.project_circle
    if pc is not None and not (pc.is_active and pc.circle.is_active):
        return 'Project/circle association inactive'
    return ''


def _load(user) -> list[Grant]:
    from apps.organization.models import ProjectCircle

    from .models import AccessAssignment
    rows = list(AccessAssignment.objects.filter(user=user).select_related('role', 'project', 'project_circle__circle')
                .prefetch_related('role__permissions'))
    wide = {a.project_id for a in rows if a.project_circle_id is None}
    circles: dict[int, list[str]] = {}
    if wide:
        for pc in ProjectCircle.objects.filter(project_id__in=wide, is_active=True, circle__is_active=True).select_related('circle'):
            circles.setdefault(pc.project_id, []).append(pc.circle.code)
    out = []
    for a in rows:
        if assignment_problem(a):
            continue
        codes = circles.get(a.project_id, []) if a.project_circle_id is None else [a.project_circle.circle.code]
        for p in a.role.permissions.all():
            if catalog.is_known(p.module, p.action):
                out += [Grant(p.module, p.action, a.project.key, c, a.pk, a.role.name, a.project_circle_id is None) for c in codes]
    return out


def grants(user) -> list[Grant]:
    if not user or not user.is_authenticated or not user.is_active:
        return []
    cached = user.__dict__.get(_CACHE)
    if cached is None:
        cached = user.__dict__[_CACHE] = _load(user)
    return cached


def global_permissions(user) -> set[tuple[str, str]]:
    """(module, action) the user has on every project and circle through the Admin or NOC Lead role."""
    return global_permissions_of(role_of(user))


def global_permissions_of(role: str | None) -> set[tuple[str, str]]:
    if role == ADMIN:
        return {(m, a) for m, spec in catalog.MODULES.items() for a in spec['actions']}
    if role == NOC_LEAD:
        return set(catalog.NOC_LEAD_PERMISSIONS)
    return set()


def has_assignments(user) -> bool:
    return bool(grants(user))


def pairs_for(user, module: str, action: str) -> set[Pair] | None:
    """None: every project and circle. Otherwise the pairs on which the user may do this (possibly none)."""
    if (module, action) in global_permissions(user):
        return None
    return {(g.project, g.circle) for g in grants(user) if g.module == module and g.action == action}


def can(user, module: str, action: str, project: str | None = None, circle: str | None = None) -> bool:
    """With no project: on any pair. With a project only: on any circle of it."""
    pairs = pairs_for(user, module, action)
    if pairs is None:
        return True
    if project is None:
        return bool(pairs)
    if circle is None:
        return any(p == project for p, _ in pairs)
    return (project, str(circle).upper()) in pairs


def permissions(user) -> dict[str, list[str]]:
    """module -> actions the user has somewhere (for the frontend's menus)."""
    out: dict[str, set[str]] = {}
    for m, a in global_permissions(user) | {(g.module, g.action) for g in grants(user)}:
        out.setdefault(m, set()).add(a)
    return {m: sorted(a) for m, a in sorted(out.items())}


def scopes(user) -> dict[str, list[dict] | None]:
    """'module.action' -> pairs (None = every project and circle), for the frontend's selectors."""
    out = {}
    for m, actions in permissions(user).items():
        for a in actions:
            pairs = pairs_for(user, m, a)
            out[f'{m}.{a}'] = None if pairs is None else [{'project': p, 'circle': c} for p, c in sorted(pairs)]
    return out


def pairs_q(pairs: set[Pair] | None, project_field: str = 'project', circle_field: str = 'circle') -> Q:
    """A query filter for records inside ``pairs`` (None: no filter; empty: nothing)."""
    if pairs is None:
        return Q()
    if not pairs:
        return Q(pk__in=[])
    q = Q()
    for p, c in pairs:
        q |= Q(**{project_field: p, circle_field: c})
    return q


def explain(user, project: str, circle: str, module: str) -> dict:
    """Access Preview: which actions of ``module`` the user has on (project, circle), and what grants or blocks them."""
    from .models import AccessAssignment
    circle = str(circle or '').upper()
    role = role_of(user)
    by_global = global_permissions(user)
    active = [g for g in grants(user) if g.module == module and g.project == project and g.circle == circle]
    blocked = []
    for a in AccessAssignment.objects.filter(user=user, project__key=project).select_related('role', 'project', 'project_circle__circle'):
        if a.project_circle_id and a.project_circle.circle.code != circle:
            continue
        problem = assignment_problem(a)
        if problem:
            blocked.append({'assignment': a.pk, 'role': a.role.name, 'scope': 'Entire project' if a.project_circle_id is None else f'Circle {circle}',
                            'reason': problem})
    actions = []
    for key, description in catalog.MODULES[module]['actions'].items():
        via = []
        if (module, key) in by_global:
            via.append({'assignment': None, 'role': catalog_role_label(role), 'scope': 'Every project and circle (built-in role)'})
        via += [{'assignment': g.assignment, 'role': g.role, 'scope': 'Entire project' if g.project_wide else f'Circle {circle}'}
                for g in active if g.action == key]
        actions.append({'action': key, 'label': catalog.ACTION_LABELS[key], 'description': description, 'allowed': bool(via) and user.is_active,
                        'granted_by': via})
    return {'user': user.get_username(), 'is_active': user.is_active, 'project': project, 'circle': circle, 'module': module,
            'module_label': catalog.MODULES[module]['label'], 'actions': actions, 'not_applying': blocked}


def catalog_role_label(role: str | None) -> str:
    return {ADMIN: 'Admin', NOC_LEAD: 'NOC Lead'}.get(role or '', '')
