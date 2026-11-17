"""Who may do what in the BSNL Module (Users & Roles modules ``bsnl_reports`` and ``bsnl_letters``).

Data is always limited to the user's (project, circle) pairs for the action. A Circle email or letter is one shared
document, so creating, sending or approving it needs the action on EVERY project of the Circle (or of the chosen site
category); the All India summary needs the action on every pair (Admin / NOC Lead / an all-circles role).
"""
from __future__ import annotations

from rest_framework.exceptions import NotFound, PermissionDenied

from apps.accounts.access import can, pairs_for

REPORTS, LETTERS = 'bsnl_reports', 'bsnl_letters'


def circle_projects(circle_code: str) -> list[str]:
    from apps.organization.models import ProjectCircle
    return sorted(ProjectCircle.objects.filter(circle__code=circle_code, is_active=True, project__is_active=True)
                  .values_list('project__key', flat=True))


def covers(user, module: str, action: str, circle_code: str | None, project: str = '') -> bool:
    pairs = pairs_for(user, module, action)
    if pairs is None:
        return True
    if circle_code is None:  # All India
        return False
    needed = [project] if project else circle_projects(circle_code)
    return bool(needed) and all((p, circle_code) in pairs for p in needed)


def require(user, module: str, action: str, circle_code: str | None = None, project: str = '', *, whole: bool = True) -> None:
    """``whole``: the action must cover the whole Circle (see the module notes); otherwise any pair is enough."""
    if not can(user, module, action):
        raise PermissionDenied('You do not have permission for this BSNL Module action.')
    if whole and not covers(user, module, action, circle_code, project):
        if circle_code is None:
            raise PermissionDenied('The All India summary needs access to every circle.')
        raise PermissionDenied('You need this permission on every project of the circle (or choose one site category).')


def letter_visible(user, letter) -> None:
    if not covers(user, LETTERS, 'view', letter.circle.code, letter.project):
        raise NotFound('No such letter.')
