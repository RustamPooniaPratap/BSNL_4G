"""The portal's roles, stored as Django Groups.

- Admin: every page, CSV arrival tracking, team performance, user management and the
  administrative operations (workbook upload, raw files, email).
- NOC Lead: what a CI may open, plus uploading the consolidated RCA workbook and seeing their own
  RCA uploads and results. Nothing else of Admin's (no team performance, CSV arrival tracking,
  user management or other users' uploads).
- CI: the operational dashboards and the data-entry pages only.

Superusers (created with ``manage.py createsuperuser``) count as Admin. A user in
neither group has no role and is refused everywhere (deny by default).
"""
from django.contrib.auth.models import Group

ADMIN = 'admin'
NOC_LEAD = 'noc_lead'
CI = 'ci'
ROLES = {ADMIN: 'Admin', NOC_LEAD: 'NOC Lead', CI: 'CI'}  # role id -> group name
GROUP_NAMES = set(ROLES.values())


def role_of(user) -> str | None:
    if not user or not user.is_authenticated or not user.is_active:
        return None
    if user.is_superuser:
        return ADMIN
    names = {g.name for g in user.groups.all()}
    for role in (ADMIN, NOC_LEAD, CI):  # one role per user; the highest wins if groups overlap
        if ROLES[role] in names:
            return role
    return None


def can_upload_rca(user) -> bool:
    """Admins and NOC Leads upload the consolidated RCA workbook."""
    return role_of(user) in (ADMIN, NOC_LEAD)


def set_role(user, role: str) -> None:
    """Put the user in exactly one portal role group (other, non-portal groups are kept)."""
    if role not in ROLES:
        raise ValueError(f'Unknown role: {role}')
    portal_groups = Group.objects.filter(name__in=GROUP_NAMES)
    user.groups.remove(*portal_groups)
    group, _ = Group.objects.get_or_create(name=ROLES[role])
    user.groups.add(group)
