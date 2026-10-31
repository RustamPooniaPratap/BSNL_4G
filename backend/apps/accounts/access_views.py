"""Users & Roles › Roles & Permissions, Access Assignments, Access Preview and Access History (Admins only).

Every list comes from the database; nothing is invented. Writes go through ``services`` (validation, self-protection,
access history).
"""
from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from . import access, catalog, services
from .audit import audit
from .models import AccessAssignment, AccessEvent, Role
from .permissions import IsAdminRole

User = get_user_model()


def _fail(exc: services.AccessError):
    raise ValidationError({exc.field: str(exc)})


def role_json(role: Role) -> dict:
    if role.system_key in ('admin', 'noc_lead'):
        perms = sorted(access.global_permissions_of(role.system_key))
        users = [u for u in User.objects.filter(is_active=True).prefetch_related('groups') if access.role_of(u) == role.system_key]
        names = sorted(u.get_username() for u in users)
    else:
        perms = sorted(role.permissions.values_list('module', 'action'))
        names = sorted(set(role.assignments.values_list('user__username', flat=True)))
    return {'id': role.pk, 'name': role.name, 'description': role.description, 'system': role.is_system, 'system_key': role.system_key or None,
            'is_active': role.is_active, 'editable': not role.is_system, 'assignable': role.system_key not in ('admin', 'noc_lead'),
            'global': role.system_key in ('admin', 'noc_lead'),
            'permissions': [{'module': m, 'action': a} for m, a in perms], 'users': names,
            'created_at': role.created_at.isoformat(timespec='seconds'), 'updated_at': role.updated_at.isoformat(timespec='seconds')}


def assignment_json(a: AccessAssignment) -> dict:
    problem = access.assignment_problem(a)
    return {'id': a.pk, 'user_id': a.user_id, 'username': a.user.get_username(), 'role_id': a.role_id, 'role': a.role.name,
            'project': a.project.key, 'circle': a.project_circle.circle.code if a.project_circle_id else None,
            'scope': 'project' if a.project_circle_id is None else 'circle', 'status': a.status,
            'valid_until': a.valid_until.isoformat() if a.valid_until else None, 'applies': not problem, 'problem': problem or None,
            'granted_by': a.granted_by.get_username() if a.granted_by else None, 'updated_at': a.updated_at.isoformat(timespec='seconds')}


def assignments_of(user) -> list[dict]:
    qs = AccessAssignment.objects.filter(user=user).select_related('user', 'role', 'project', 'project_circle__circle', 'granted_by')
    return [assignment_json(a) for a in qs]


def _role(pk) -> Role:
    role = Role.objects.filter(pk=pk).first()
    if role is None:
        raise NotFound('No such role.')
    return role


def _user(pk) -> User:
    user = User.objects.filter(pk=pk).first() if str(pk or '').isdigit() else None
    if user is None:
        raise NotFound('No such user.')
    return user


def _date(value):
    if value in (None, ''):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValidationError({'valid_until': 'Give the date as YYYY-MM-DD.'}) from exc


# --- Catalogue and roles ---------------------------------------------------------------------------

@api_view(['GET'])
@permission_classes([IsAdminRole])
def access_catalog(request):
    return Response(catalog.as_json())


@api_view(['GET', 'POST'])
@permission_classes([IsAdminRole])
def roles(request):
    if request.method == 'POST':
        d = request.data
        try:
            role = services.create_role(request.user, d.get('name'), d.get('description') or '', d.get('permissions') or [])
        except services.AccessError as exc:
            _fail(exc)
        audit('role_created', request, role=role.name)
        return Response({'role': role_json(role)}, status=status.HTTP_201_CREATED)
    return Response({'roles': [role_json(r) for r in Role.objects.prefetch_related('permissions')]})


@api_view(['PATCH', 'DELETE'])
@permission_classes([IsAdminRole])
def role_detail(request, pk: int):
    role = _role(pk)
    try:
        if request.method == 'DELETE':
            services.delete_role(request.user, role)
            audit('role_deleted', request, role=role.name)
            return Response(status=status.HTTP_204_NO_CONTENT)
        d = request.data
        role = services.update_role(request.user, role, name=d.get('name'), description=d.get('description'),
                                    permissions=d.get('permissions'), is_active=d.get('is_active'))
    except services.AccessError as exc:
        _fail(exc)
    audit('role_updated', request, role=role.name)
    return Response({'role': role_json(role)})


@api_view(['POST'])
@permission_classes([IsAdminRole])
def role_clone(request, pk: int):
    try:
        role = services.clone_role(request.user, _role(pk), request.data.get('name'))
    except services.AccessError as exc:
        _fail(exc)
    audit('role_cloned', request, role=role.name)
    return Response({'role': role_json(role)}, status=status.HTTP_201_CREATED)


# --- Assignments -----------------------------------------------------------------------------------

@api_view(['GET', 'POST'])
@permission_classes([IsAdminRole])
def assignments(request):
    if request.method == 'GET':
        qs = AccessAssignment.objects.select_related('user', 'role', 'project', 'project_circle__circle', 'granted_by')
        if request.query_params.get('user'):
            qs = qs.filter(user=_user(request.query_params['user']))
        return Response({'assignments': [assignment_json(a) for a in qs]})
    d = request.data
    user, role = _user(d.get('user')), _role(d.get('role'))
    scope = d.get('scope')
    if scope not in ('project', 'circles'):
        raise ValidationError({'scope': 'Choose Entire project or Selected circles.'})
    circles = d.get('circles') if scope == 'circles' else None
    if circles is not None and not isinstance(circles, list):
        raise ValidationError({'circles': 'Give a list of circle codes.'})
    try:
        made = services.assign(request.user, user, role, str(d.get('project') or ''), circles, status=d.get('status') or 'active',
                               valid_until=_date(d.get('valid_until')))
    except services.AccessError as exc:
        _fail(exc)
    audit('access_assigned', request, user_id=user.pk, role=role.name, project=d.get('project'), circles=','.join(circles or ['*']))
    return Response({'assignments': [assignment_json(a) for a in made]}, status=status.HTTP_201_CREATED)


@api_view(['PATCH', 'DELETE'])
@permission_classes([IsAdminRole])
def assignment_detail(request, pk: int):
    a = AccessAssignment.objects.select_related('user', 'role', 'project', 'project_circle__circle').filter(pk=pk).first()
    if a is None:
        raise NotFound('No such assignment.')
    try:
        if request.method == 'DELETE':
            services.revoke(request.user, a)
            audit('access_revoked', request, user_id=a.user_id, assignment=pk)
            return Response(status=status.HTTP_204_NO_CONTENT)
        d = request.data
        a = services.update_assignment(request.user, a, role=_role(d['role']) if d.get('role') else None, status=d.get('status'),
                                       valid_until=_date(d.get('valid_until')) if 'valid_until' in d else ...)
    except services.AccessError as exc:
        _fail(exc)
    audit('access_changed', request, user_id=a.user_id, assignment=pk)
    return Response({'assignment': assignment_json(a)})


# --- Preview, effective permissions and history ----------------------------------------------------

@api_view(['GET'])
@permission_classes([IsAdminRole])
def preview(request):
    """What the user may do in one module on one project/circle. Read only: no impersonation, nothing changes."""
    p = request.query_params
    user = _user(p.get('user'))
    module = p.get('module')
    if module not in catalog.MODULES:
        raise ValidationError({'module': 'Choose a module.'})
    if not p.get('project') or not p.get('circle'):
        raise ValidationError({'circle': 'Choose the project and circle.'})
    return Response(access.explain(user, p['project'], p['circle'], module))


@api_view(['GET'])
@permission_classes([IsAdminRole])
def effective(request, user_id: int):
    user = _user(user_id)
    return Response({'user': user.get_username(), 'role': access.role_of(user), 'is_active': user.is_active,
                     'permissions': access.permissions(user), 'scopes': access.scopes(user), 'assignments': assignments_of(user)})


@api_view(['GET'])
@permission_classes([IsAdminRole])
def history(request):
    qs = AccessEvent.objects.all()
    p = request.query_params
    if p.get('user'):
        qs = qs.filter(target_user_id=p['user'])
    if p.get('action'):
        qs = qs.filter(action=p['action'])
    return Response({'events': [{'id': e.pk, 'at': e.created_at.isoformat(timespec='seconds'), 'actor': e.actor_name or '-', 'action': e.action,
                                 'user': e.target_name, 'scope': e.scope, 'details': e.details} for e in qs[:500]],
                     'actions': sorted(set(AccessEvent.objects.order_by().values_list('action', flat=True).distinct()))})
