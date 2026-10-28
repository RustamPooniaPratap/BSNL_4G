"""The portal's two roles, stored as Django Groups.

- Admin: every page, CSV arrival tracking, team performance, user management and the
  administrative operations (workbook upload, raw files, email).
- CI: the operational dashboards and the data-entry pages only.

Superusers (created with ``manage.py createsuperuser``) count as Admin. A user in
neither group has no role and is refused everywhere (deny by default).
"""
from django.contrib.auth.models import Group

ADMIN = 'admin'
CI = 'ci'
ROLES = {ADMIN: 'Admin', CI: 'CI'}  # role id -> group name
GROUP_NAMES = set(ROLES.values())


def role_of(user) -> str | None:
    if not user or not user.is_authenticated or not user.is_active:
        return None
    if user.is_superuser:
        return ADMIN
    names = {g.name for g in user.groups.all()}
    if ROLES[ADMIN] in names:
        return ADMIN
    if ROLES[CI] in names:
        return CI
    return None


def set_role(user, role: str) -> None:
    """Put the user in exactly one portal role group (other, non-portal groups are kept)."""
    if role not in ROLES:
        raise ValueError(f'Unknown role: {role}')
    portal_groups = Group.objects.filter(name__in=GROUP_NAMES)
    user.groups.remove(*portal_groups)
    group, _ = Group.objects.get_or_create(name=ROLES[role])
    user.groups.add(group)
