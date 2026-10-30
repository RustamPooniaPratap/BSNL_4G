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


# Users allowed to upload consolidated RCA workbooks besides Admins (a plain Django group, managed on Users & Roles).
RCA_CONSOLIDATED_GROUP = 'RCA Consolidated Uploaders'


def can_upload_rca(user) -> bool:
    """Admins and NOC Leads: every RCA upload of their own, the period workbooks and the uploads list (all circles)."""
    return role_of(user) in (ADMIN, NOC_LEAD)


def can_upload_consolidated_rca(user) -> bool:
    """Admins, and portal users an Admin put in the RCA Consolidated Uploaders group. Uploading circle files gives no
    right to upload a consolidated workbook."""
    role = role_of(user)
    if role == ADMIN:
        return True
    return role is not None and user.groups.filter(name=RCA_CONSOLIDATED_GROUP).exists()


def can_upload_circle_rca(user, project: str | None = None, circle: str | None = None) -> bool:
    """Admins and NOC Leads for every project and circle; a CI user only for the project/circle pairs granted to them
    (Organization > User Access). Without a project and circle: whether the user may upload any circle file."""
    from .scope import allowed_pairs
    role = role_of(user)
    if role in (ADMIN, NOC_LEAD):
        return True
    if role != CI:
        return False
    pairs = allowed_pairs(user) or set()
    return bool(pairs) if project is None else (project, (circle or '').upper()) in pairs


def set_rca_consolidated(user, allowed: bool) -> None:
    group, _ = Group.objects.get_or_create(name=RCA_CONSOLIDATED_GROUP)
    if allowed:
        user.groups.add(group)
    else:
        user.groups.remove(group)


def set_role(user, role: str) -> None:
    """Put the user in exactly one portal role group (other, non-portal groups are kept)."""
    if role not in ROLES:
        raise ValueError(f'Unknown role: {role}')
    portal_groups = Group.objects.filter(name__in=GROUP_NAMES)
    user.groups.remove(*portal_groups)
    group, _ = Group.objects.get_or_create(name=ROLES[role])
    user.groups.add(group)
