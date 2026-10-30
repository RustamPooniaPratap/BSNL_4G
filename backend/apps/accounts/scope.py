"""Which projects and circles a user may upload raw daily data for and export.

- Admin and NOC Lead: everything (``None`` = not limited).
- CI: the project/circle pairs an Admin granted (organization.UserCircleAccess), e.g. MP under 4G Saturation only.
  Access to a circle under one project never gives access to the same circle under another project.
- Legacy circle-only assignments (AccountProfile.circles, from before project-specific access) keep the access they
  always gave, the circle under every project, until an Admin reviews them in Organization > User Access. The
  migration converted those whose circle belongs to exactly one project; the others are flagged for review.
- A CI user with nothing granted gets an empty set (no upload or export), never unrestricted access.
- No portal role: nothing.

Every raw-upload and export endpoint checks this on the server; the frontend only uses it to choose what to show.
"""
from __future__ import annotations

from .models import AccountProfile
from .roles import ADMIN, CI, NOC_LEAD, role_of

Pair = tuple[str, str]


def forget_profile(user) -> None:
    """Drop the cached profile (Django keeps a reverse one-to-one in ``_state.fields_cache``) so the next read sees changes."""
    user._state.fields_cache.pop('portal_profile', None)
    user.__dict__.pop('portal_profile', None)


def legacy_circles(user) -> list[str]:
    """Circle-only assignments still waiting for review (they apply to every project)."""
    profile = getattr(user, 'portal_profile', None)
    return sorted({str(c).upper() for c in (profile.circles if profile else [])})


def granted_pairs(user) -> list[Pair]:
    """The explicit project/circle grants of the user."""
    from apps.organization.models import UserCircleAccess
    rows = UserCircleAccess.objects.filter(user=user).values_list('project_circle__project__key', 'project_circle__circle__code')
    return sorted(set(rows))


def allowed_pairs(user) -> set[Pair] | None:
    """None: every project and circle. Otherwise the (project, circle) pairs the user may use (possibly none)."""
    role = role_of(user)
    if role in (ADMIN, NOC_LEAD):
        return None
    if role != CI:
        return set()
    pairs = set(granted_pairs(user))
    legacy = legacy_circles(user)
    if legacy:
        from apps.organization.services import project_keys
        pairs |= {(p, c) for c in legacy for p in project_keys()}
    return pairs


def allowed_circles(user) -> set[str] | None:
    """Circles with access under at least one project (for display; checks use ``may_use``)."""
    pairs = allowed_pairs(user)
    return None if pairs is None else {c for _, c in pairs}


def may_use(user, project: str, circle: str) -> bool:
    pairs = allowed_pairs(user)
    return pairs is None or (project, circle.upper()) in pairs


def assigned_circles(user) -> list[str]:
    """Circles of the user's grants and legacy assignments (shown on Users & Roles)."""
    return sorted({c for _, c in granted_pairs(user)} | set(legacy_circles(user)))


def set_pairs(user, pairs, *, actor=None, reason: str = '') -> tuple[list[Pair], list[Pair]]:
    """Replace the user's grants with ``pairs`` (each an existing association) and clear legacy assignments, which the
    explicit grants now replace. Returns (added, removed); the change is recorded in the organization history."""
    from apps.organization.models import ProjectCircle, UserCircleAccess
    from apps.organization.services import record

    wanted = sorted(set(pairs))
    links = {(pc.project.key, pc.circle.code): pc for pc in ProjectCircle.objects.select_related('project', 'circle')}
    missing = [p for p in wanted if p not in links]
    if missing:
        raise ValueError('Not a project/circle association: ' + ', '.join(f'{c} under {p}' for p, c in missing))
    before, legacy = granted_pairs(user), legacy_circles(user)
    added, removed = [p for p in wanted if p not in before], [p for p in before if p not in wanted]
    UserCircleAccess.objects.filter(user=user, project_circle__in=[links[p] for p in removed]).delete()
    for p in added:
        UserCircleAccess.objects.create(user=user, project_circle=links[p], granted_by=actor if getattr(actor, 'pk', None) else None)
    if legacy:
        AccountProfile.objects.filter(user=user).update(circles=[])
    forget_profile(user)
    if added or removed or legacy:
        record('user_access', user, 'access_changed', actor=actor, reason=reason, label=user.get_username(),
               previous={'pairs': [list(p) for p in before], 'legacy_circles': legacy}, new={'pairs': [list(p) for p in wanted], 'legacy_circles': []})
    return added, removed


def set_circles(user, circles, *, actor=None, reason: str = '') -> None:
    """Circle-only form (Users & Roles, older API clients): grants each circle under every project it is associated
    with today, as explicit grants. A project associated with the circle later is not granted automatically."""
    from apps.organization.services import associations
    wanted = {c.upper() for c in circles}
    set_pairs(user, [(p, c) for p, c in associations(active_only=False) if c in wanted], actor=actor, reason=reason)
