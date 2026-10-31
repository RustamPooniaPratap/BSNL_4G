"""Write side of roles, permissions and assignments (Users & Roles), each change recorded in the access history.

Only Admins reach these (the views check it). Built-in roles cannot be edited or deleted; an Admin cannot change their
own assignments; a custom role only ever holds catalogue permissions, never administrative ones.
"""
from __future__ import annotations

from django.db import transaction

from . import access, catalog
from .models import AccessAssignment, AccessEvent, Role, RolePermission


class AccessError(ValueError):
    """A refused change, with a message for the Admin (``field`` names the form field)."""

    def __init__(self, message: str, field: str = 'form'):
        super().__init__(message)
        self.field = field


def log(actor, action: str, *, user=None, target: str = '', scope: str = '', details: dict | None = None) -> None:
    real = actor if getattr(actor, 'pk', None) else None
    AccessEvent.objects.create(actor=real, actor_name=real.get_username() if real else 'system', target_user=user,
                               target_name=(target or (user.get_username() if user is not None else ''))[:150], action=action,
                               scope=scope[:200], details=details or {})


def scope_label(a: AccessAssignment) -> str:
    return f'{a.project.key} · ' + ('entire project' if a.project_circle_id is None else a.project_circle.circle.code)


# --- Roles -----------------------------------------------------------------------------------------

def _clean_permissions(items) -> list[tuple[str, str]]:
    out = set()
    for item in items or []:
        module, action = (item.get('module'), item.get('action')) if isinstance(item, dict) else (None, None)
        if not catalog.is_known(str(module), str(action)):
            raise AccessError(f'Unknown permission: {module}.{action}.', 'permissions')
        out.add((module, action))
    return sorted(out)


def _set_permissions(role: Role, perms: list[tuple[str, str]]) -> None:
    RolePermission.objects.filter(role=role).delete()
    RolePermission.objects.bulk_create([RolePermission(role=role, module=m, action=a) for m, a in perms])


def _editable(role: Role) -> None:
    if role.is_system:
        raise AccessError(f'{role.name} is a built-in role: it cannot be changed or deleted. Clone it to make a custom role.')


def _name(name: str, role: Role | None = None) -> str:
    name = ' '.join(str(name or '').split())
    if not 2 <= len(name) <= 60:
        raise AccessError('Use 2 to 60 characters.', 'name')
    if Role.objects.filter(name__iexact=name).exclude(pk=getattr(role, 'pk', None)).exists():
        raise AccessError('A role with this name exists.', 'name')
    return name


@transaction.atomic
def create_role(actor, name: str, description: str = '', permissions=None) -> Role:
    perms = _clean_permissions(permissions)
    role = Role.objects.create(name=_name(name), description=str(description or '')[:300], created_by=actor)
    _set_permissions(role, perms)
    log(actor, 'role_created', target=role.name, details={'permissions': [f'{m}.{a}' for m, a in perms]})
    return role


@transaction.atomic
def update_role(actor, role: Role, *, name=None, description=None, permissions=None, is_active=None) -> Role:
    _editable(role)
    before = sorted(role.permissions.values_list('module', 'action'))
    changes = {}
    if name is not None and name != role.name:
        changes['name'] = {'from': role.name, 'to': _name(name, role)}
        role.name = changes['name']['to']
    if description is not None and description != role.description:
        role.description = str(description)[:300]
        changes['description'] = 'changed'
    if is_active is not None and is_active != role.is_active:
        role.is_active = bool(is_active)
        changes['is_active'] = role.is_active
    role.save()
    if permissions is not None:
        perms = _clean_permissions(permissions)
        if perms != [tuple(p) for p in before]:
            _set_permissions(role, perms)
            log(actor, 'role_permissions_changed', target=role.name,
                details={'added': [f'{m}.{a}' for m, a in perms if (m, a) not in before],
                         'removed': [f'{m}.{a}' for m, a in before if (m, a) not in perms]})
    if 'is_active' in changes:
        log(actor, 'role_activated' if role.is_active else 'role_deactivated', target=role.name)
    if {'name', 'description'} & changes.keys():
        log(actor, 'role_updated', target=role.name, details={k: v for k, v in changes.items() if k != 'is_active'})
    return role


@transaction.atomic
def clone_role(actor, role: Role, name: str) -> Role:
    perms = sorted(role.permissions.values_list('module', 'action'))
    if role.system_key in ('admin', 'noc_lead'):
        perms = sorted(access.global_permissions_of(role.system_key))
    copy = Role.objects.create(name=_name(name), description=role.description, created_by=actor)
    _set_permissions(copy, perms)
    log(actor, 'role_cloned', target=copy.name, details={'from': role.name, 'permissions': [f'{m}.{a}' for m, a in perms]})
    return copy


@transaction.atomic
def delete_role(actor, role: Role) -> None:
    _editable(role)
    if role.assignments.exists():
        raise AccessError(f'{role.name} is assigned to {role.assignments.values("user").distinct().count()} user(s): remove those '
                          'assignments or deactivate the role instead.')
    log(actor, 'role_deleted', target=role.name, details={'permissions': [f'{m}.{a}' for m, a in role.permissions.values_list('module', 'action')]})
    role.delete()


# --- Assignments -----------------------------------------------------------------------------------

def _assignable(role: Role) -> None:
    if role.system_key in ('admin', 'noc_lead'):
        raise AccessError('Admin and NOC Lead are account roles (every project and circle); set them on the user, not as an assignment.', 'role')
    if not role.is_active:
        raise AccessError(f'{role.name} is inactive.', 'role')


def _not_self(actor, user) -> None:
    if getattr(actor, 'pk', None) == user.pk:
        raise AccessError('You cannot change your own access.')


@transaction.atomic
def assign(actor, user, role: Role, project_key: str, circles: list[str] | None, *, status: str = 'active', valid_until=None) -> list[AccessAssignment]:
    """Assign ``role`` on the entire project (``circles`` None) or on each listed circle. Only active Organization
    associations may be assigned; existing identical assignments are updated, not duplicated."""
    from apps.organization.models import Project, ProjectCircle
    _not_self(actor, user)
    _assignable(role)
    if status not in AccessAssignment.Status.values:
        raise AccessError('Choose Active or Inactive.', 'status')
    project = Project.objects.filter(key=project_key).first()
    if project is None or not project.is_active:
        raise AccessError('Choose an active project of the Organization.', 'project')
    targets: list[ProjectCircle | None]
    if circles is None:
        targets = [None]
    else:
        codes = sorted({str(c).upper() for c in circles})
        if not codes:
            raise AccessError('Choose at least one circle, or the entire project.', 'circles')
        links = {pc.circle.code: pc for pc in ProjectCircle.objects.filter(project=project, is_active=True, circle__is_active=True).select_related('circle')}
        unknown = [c for c in codes if c not in links]
        if unknown:
            raise AccessError(f'Not an active circle of {project.key} in Organization › Project-Circle Mapping: {", ".join(unknown)}.', 'circles')
        targets = [links[c] for c in codes]
    out = []
    for pc in targets:
        a, created = AccessAssignment.objects.update_or_create(user=user, role=role, project=project, project_circle=pc,
                                                               defaults={'status': status, 'valid_until': valid_until, 'granted_by': actor})
        out.append(a)
        log(actor, 'assignment_added' if created else 'assignment_updated', user=user, scope=f'{role.name} · {scope_label(a)}',
            details={'status': status, 'valid_until': valid_until.isoformat() if valid_until else None})
    access.forget(user)
    return out


@transaction.atomic
def update_assignment(actor, a: AccessAssignment, *, role: Role | None = None, status: str | None = None, valid_until=..., ) -> AccessAssignment:
    _not_self(actor, a.user)
    changes = {}
    if role is not None and role.pk != a.role_id:
        _assignable(role)
        if AccessAssignment.objects.filter(user=a.user, role=role, project=a.project, project_circle=a.project_circle).exclude(pk=a.pk).exists():
            raise AccessError(f'{a.user.get_username()} already has {role.name} on this scope.', 'role')
        changes['role'] = {'from': a.role.name, 'to': role.name}
        a.role = role
    if status is not None and status != a.status:
        if status not in AccessAssignment.Status.values:
            raise AccessError('Choose Active or Inactive.', 'status')
        changes['status'] = {'from': a.status, 'to': status}
        a.status = status
    if valid_until is not ... and valid_until != a.valid_until:
        changes['valid_until'] = {'from': a.valid_until.isoformat() if a.valid_until else None, 'to': valid_until.isoformat() if valid_until else None}
        a.valid_until = valid_until
    if changes:
        a.granted_by = actor
        a.save()
        log(actor, 'assignment_updated', user=a.user, scope=f'{a.role.name} · {scope_label(a)}', details=changes)
    access.forget(a.user)
    return a


@transaction.atomic
def revoke(actor, a: AccessAssignment) -> None:
    _not_self(actor, a.user)
    log(actor, 'assignment_revoked', user=a.user, scope=f'{a.role.name} · {scope_label(a)}')
    a.delete()
    access.forget(a.user)
