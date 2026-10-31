"""Project/circle scope helpers kept for the existing callers (Organization › User Access, Users & Roles circles).

The source of truth is ``AccessAssignment`` (see ``access`` for the rules). "Granted pairs" are a user's circle
assignments with the built-in CI role, which is what Organization › User Access edits; Users & Roles › Access
Assignments edits every assignment, with any role. Both write the same table.

Legacy circle-only assignments (``AccountProfile.circles``, from before project-specific access) grant nothing: a circle
with no project cannot be mapped safely, so it is listed for review until an Admin assigns the projects explicitly.
"""
from __future__ import annotations

from . import access
from .models import AccountProfile

Pair = tuple[str, str]


def forget_profile(user) -> None:
    """Drop the cached profile and grants so the next read sees changes."""
    user._state.fields_cache.pop('portal_profile', None)
    user.__dict__.pop('portal_profile', None)
    access.forget(user)


def legacy_circles(user) -> list[str]:
    """Circle-only assignments waiting for review (they grant nothing)."""
    profile = getattr(user, 'portal_profile', None)
    return sorted({str(c).upper() for c in (profile.circles if profile else [])})


def ci_role():
    from .models import Role
    return Role.objects.get(system_key='ci')


def granted_pairs(user) -> list[Pair]:
    """The user's circle assignments with the built-in CI role (active or not)."""
    from .models import AccessAssignment
    rows = AccessAssignment.objects.filter(user=user, role__system_key='ci', project_circle__isnull=False).values_list(
        'project__key', 'project_circle__circle__code')
    return sorted(set(rows))


def allowed_pairs(user) -> set[Pair] | None:
    """None: every project and circle (Admin, NOC Lead). Otherwise every pair any applying assignment covers."""
    if access.global_permissions(user):
        return None
    return {(g.project, g.circle) for g in access.grants(user)}


def allowed_circles(user) -> set[str] | None:
    pairs = allowed_pairs(user)
    return None if pairs is None else {c for _, c in pairs}


def may_use(user, project: str, circle: str) -> bool:
    pairs = allowed_pairs(user)
    return pairs is None or (project, circle.upper()) in pairs


def assigned_circles(user) -> list[str]:
    return sorted({c for _, c in granted_pairs(user)} | set(legacy_circles(user)))


def set_pairs(user, pairs, *, actor=None, reason: str = '') -> tuple[list[Pair], list[Pair]]:
    """Replace the user's CI-role circle assignments with ``pairs`` (each an existing association) and clear legacy
    circle-only assignments. Other assignments are kept. Returns (added, removed); both histories record the change."""
    from apps.organization.models import ProjectCircle
    from apps.organization.services import record

    from .models import AccessAssignment
    from .services import log

    wanted = sorted(set(pairs))
    links = {(pc.project.key, pc.circle.code): pc for pc in ProjectCircle.objects.select_related('project', 'circle')}
    missing = [p for p in wanted if p not in links]
    if missing:
        raise ValueError('Not a project/circle association: ' + ', '.join(f'{c} under {p}' for p, c in missing))
    role = ci_role()
    before, legacy = granted_pairs(user), legacy_circles(user)
    added, removed = [p for p in wanted if p not in before], [p for p in before if p not in wanted]
    AccessAssignment.objects.filter(user=user, role=role, project_circle__in=[links[p] for p in removed]).delete()
    for p in added:
        AccessAssignment.objects.create(user=user, role=role, project=links[p].project, project_circle=links[p],
                                        granted_by=actor if getattr(actor, 'pk', None) else None)
    if legacy:
        AccountProfile.objects.filter(user=user).update(circles=[])
    forget_profile(user)
    if added or removed or legacy:
        record('user_access', user, 'access_changed', actor=actor, reason=reason, label=user.get_username(),
               previous={'pairs': [list(p) for p in before], 'legacy_circles': legacy}, new={'pairs': [list(p) for p in wanted], 'legacy_circles': []})
        log(actor, 'assignments_replaced', user=user, scope='CI role: ' + (', '.join(f'{c} ({p})' for p, c in wanted) or 'none'),
            details={'added': [list(p) for p in added], 'removed': [list(p) for p in removed], 'legacy_cleared': legacy, 'reason': reason})
    return added, removed


def set_circles(user, circles, *, actor=None, reason: str = '') -> None:
    """Circle-only form (older API clients): each circle under every project it is associated with today."""
    from apps.organization.services import associations
    wanted = {c.upper() for c in circles}
    set_pairs(user, [(p, c) for p, c in associations(active_only=False) if c in wanted], actor=actor, reason=reason)
