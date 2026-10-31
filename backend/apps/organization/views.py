"""Organization API (Administration > Organization). Admins manage everything; any portal user may read the catalog.

Every write runs in one transaction with its change-history entry, so a refused or failed operation changes nothing and
records nothing. Projects are deactivated, never deleted. A circle can be deleted only while nothing refers to it
(associations, aliases, records of any project, grants); otherwise it is deactivated. Removing an association removes
only that project's association, and only while nothing refers to it (sites, daily or monthly values, uploads, RCA
records or expected units, escalation sites, user grants); otherwise the association is kept, inactive.
"""
from __future__ import annotations

import re

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from apps.accounts.audit import audit
from apps.accounts.permissions import IsAdminRole, IsPortalUser
from apps.accounts.roles import ADMIN, CI, NOC_LEAD, ROLES, role_of
from apps.accounts.scope import granted_pairs, legacy_circles, set_pairs

from . import services
from .models import Circle, CircleAlias, OrganizationChange, Project, ProjectCircle

User = get_user_model()
CODE = re.compile(r'^[A-Z][A-Z0-9-]{1,19}$')
EMPTY_USAGE = services.EMPTY_USAGE


def _reason(request) -> str:
    return str(request.data.get('reason') or '').strip()[:500]


def _get(model, pk):
    obj = model.objects.filter(pk=pk).first()
    if obj is None:
        raise NotFound('Not found.')
    return obj


def _save(obj, fields=None):
    try:
        with transaction.atomic():
            obj.save() if fields is None else obj.save(update_fields=[*fields, 'updated_at'])
    except IntegrityError as exc:
        raise ValidationError({'form': 'Another record already uses this value.'}) from exc


@api_view(['GET'])
@permission_classes([IsPortalUser])
def catalog(request):
    return Response(services.catalog())


# --- Projects --------------------------------------------------------------------------------------

def _project_json(p: Project, usage: dict) -> dict:
    links = [pc for pc in p.circles.all()]
    totals = dict(EMPTY_USAGE)
    for pc in links:
        for k, v in usage.get((p.key, pc.circle.code), {}).items():
            totals[k] += v
    return {'id': p.id, 'key': p.key, 'code': p.code, 'name': p.name, 'description': p.description, 'is_active': p.is_active,
            'circles': [{'code': pc.circle.code, 'is_active': pc.is_active} for pc in links], 'usage': totals,
            'created_at': p.created_at.isoformat(timespec='seconds'), 'updated_at': p.updated_at.isoformat(timespec='seconds')}


def _project_state(p: Project) -> dict:
    return {'key': p.key, 'code': p.code, 'name': p.name, 'description': p.description, 'is_active': p.is_active}


class ProjectSerializer(serializers.Serializer):
    key = serializers.RegexField(r'^[A-Za-z0-9][A-Za-z0-9 .&-]{0,19}$', required=False,
                                 error_messages={'invalid': 'Use up to 20 letters, digits, spaces and . & -'})
    code = serializers.RegexField(r'^[A-Za-z0-9][A-Za-z0-9 -]{0,11}$', required=False,
                                  error_messages={'invalid': 'Use up to 12 letters, digits, spaces and -'})
    name = serializers.CharField(max_length=80, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    is_active = serializers.BooleanField(required=False)


@api_view(['GET', 'POST'])
@permission_classes([IsAdminRole])
@transaction.atomic
def projects(request):
    if request.method == 'POST':
        data = ProjectSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        missing = {f: 'Required.' for f in ('key', 'code', 'name') if not str(v.get(f) or '').strip()}
        if missing:
            raise ValidationError(missing)
        p = Project(key=v['key'].strip(), code=v['code'].strip(), name=v['name'].strip(), description=v.get('description', ''),
                    is_active=v.get('is_active', True), sort_order=(Project.objects.count() + 1) * 10)
        _save(p)
        services.record('project', p, 'created', new=_project_state(p), actor=request.user, reason=_reason(request), label=p.name)
        audit('org_project_created', request, project=p.key)
    usage = services.usage_by_pair()
    qs = Project.objects.prefetch_related('circles__circle')
    return Response({'projects': [_project_json(p, usage) for p in qs]}, status=201 if request.method == 'POST' else 200)


@api_view(['PATCH'])
@permission_classes([IsAdminRole])
@transaction.atomic
def project_detail(request, pk: int):
    p = _get(Project, pk)
    if 'key' in request.data and request.data['key'] != p.key:
        raise ValidationError({'key': 'The project identifier is stored on its records and cannot change; edit the name instead.'})
    data = ProjectSerializer(data=request.data, partial=True)
    data.is_valid(raise_exception=True)
    before = _project_state(p)
    for field in ('code', 'name', 'description', 'is_active'):
        if field in data.validated_data:
            value = data.validated_data[field]
            setattr(p, field, value.strip() if isinstance(value, str) else value)
    if _project_state(p) != before:
        _save(p)
        action = 'updated' if before['is_active'] == p.is_active else ('activated' if p.is_active else 'deactivated')
        services.record('project', p, action, previous=before, new=_project_state(p), actor=request.user, reason=_reason(request), label=p.name)
        audit('org_project_' + action, request, project=p.key)
    return Response({'project': _project_json(Project.objects.prefetch_related('circles__circle').get(pk=p.pk), services.usage_by_pair())})


# --- Circles ---------------------------------------------------------------------------------------

def _circle_json(c: Circle, usage: dict, links: list[ProjectCircle]) -> dict:
    mine = [pc for pc in links if pc.circle_id == c.id]
    return {'id': c.id, 'code': c.code, 'name': c.name, 'description': c.description, 'is_active': c.is_active,
            'projects': [{'project': pc.project.key, 'project_code': pc.project.code, 'is_active': pc.is_active,
                          'usage': usage.get((pc.project.key, c.code), dict(EMPTY_USAGE))} for pc in mine],
            # Data of the circle under projects it is not associated with (shown so nothing is hidden).
            'unassociated_data': [{'project': p, 'usage': u} for (p, code), u in sorted(usage.items())
                                  if code == c.code and p not in {pc.project.key for pc in mine}],
            'aliases': c.aliases.count(), 'deletable': not circle_dependencies(c, usage),
            'created_at': c.created_at.isoformat(timespec='seconds'), 'updated_at': c.updated_at.isoformat(timespec='seconds')}


def _circle_state(c: Circle) -> dict:
    return {'code': c.code, 'name': c.name, 'description': c.description, 'is_active': c.is_active}


class CircleSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=20, required=False)
    name = serializers.CharField(max_length=80, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    is_active = serializers.BooleanField(required=False)

    def validate_code(self, value):
        code = value.strip().upper()
        if not CODE.match(code):
            raise serializers.ValidationError('Use 2 to 20 capital letters, digits or -, starting with a letter (e.g. MP).')
        return code


def _all_circles():
    usage = services.usage_by_pair()
    links = list(ProjectCircle.objects.select_related('project', 'circle'))
    return [_circle_json(c, usage, links) for c in Circle.objects.all()]


@api_view(['GET', 'POST'])
@permission_classes([IsAdminRole])
@transaction.atomic
def circles(request):
    if request.method == 'POST':
        data = CircleSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        missing = {f: 'Required.' for f in ('code', 'name') if not str(v.get(f) or '').strip()}
        if missing:
            raise ValidationError(missing)
        if Circle.objects.filter(name__iexact=v['name'].strip()).exists() or Circle.objects.filter(code=v['code']).exists():
            raise ValidationError({'form': 'A circle with this code or name already exists; associate it with the project instead.'})
        taken = CircleAlias.objects.filter(raw_key=services.alias_key(v['code']), is_active=True).select_related('circle').first()
        if taken:
            raise ValidationError({'code': f'"{v["code"]}" is an alias of circle {taken.circle.code} ({taken.get_source_display()}).'})
        c = Circle(code=v['code'], name=v['name'].strip(), description=v.get('description', ''), is_active=v.get('is_active', True))
        _save(c)
        services.record('circle', c, 'created', new=_circle_state(c), actor=request.user, reason=_reason(request), label=c.code)
        audit('org_circle_created', request, circle=c.code)
    return Response({'circles': _all_circles()}, status=201 if request.method == 'POST' else 200)


def circle_dependencies(c: Circle, usage: dict | None = None) -> dict:
    """Everything that refers to the circle; it can be deleted only when this is empty."""
    from apps.accounts.models import AccountProfile
    deps = {'associations': c.projects.count(), 'aliases': c.aliases.count(),
            'legacy_assignments': sum(1 for circles in AccountProfile.objects.values_list('circles', flat=True)
                                      if c.code in [str(x).upper() for x in circles or []])}
    for (_, code), counts in (usage if usage is not None else services.usage_by_pair()).items():
        if code == c.code:
            for k, v in counts.items():
                if k != 'on_air_sites':
                    deps[k] = deps.get(k, 0) + v
    return {k: v for k, v in deps.items() if v}


@api_view(['PATCH', 'DELETE'])
@permission_classes([IsAdminRole])
@transaction.atomic
def circle_detail(request, pk: int):
    c = _get(Circle, pk)
    if request.method == 'DELETE':
        deps = circle_dependencies(c)
        if deps:
            raise ValidationError({'form': f'{c.code} cannot be deleted: ' + ', '.join(f'{k.replace("_", " ")} {v:,}' for k, v in deps.items())
                                   + '. Deactivate it instead.'})
        services.record('circle', c, 'deleted', previous=_circle_state(c), actor=request.user, reason=_reason(request), label=c.code)
        audit('org_circle_deleted', request, circle=c.code)
        c.delete()
        return Response({'circles': _all_circles()})
    if 'code' in request.data and str(request.data['code']).strip().upper() != c.code:
        raise ValidationError({'code': 'The circle code is stored on its records and cannot change; edit the name instead.'})
    data = CircleSerializer(data={k: v for k, v in request.data.items() if k != 'code'}, partial=True)
    data.is_valid(raise_exception=True)
    before = _circle_state(c)
    for field in ('name', 'description', 'is_active'):
        if field in data.validated_data:
            value = data.validated_data[field]
            setattr(c, field, value.strip() if isinstance(value, str) else value)
    if Circle.objects.exclude(pk=c.pk).filter(name__iexact=c.name).exists():
        raise ValidationError({'name': 'Another circle has this name.'})
    if _circle_state(c) != before:
        _save(c)
        action = 'updated' if before['is_active'] == c.is_active else ('activated' if c.is_active else 'deactivated')
        services.record('circle', c, action, previous=before, new=_circle_state(c), actor=request.user, reason=_reason(request), label=c.code)
        audit('org_circle_' + action, request, circle=c.code)
    return Response({'circles': _all_circles()})


# --- Project-circle associations -------------------------------------------------------------------

def _all_associations():
    usage = services.usage_by_pair()
    return [{'id': pc.id, 'project': pc.project.key, 'project_code': pc.project.code, 'project_active': pc.project.is_active,
             'circle': pc.circle.code, 'circle_name': pc.circle.name, 'circle_active': pc.circle.is_active, 'is_active': pc.is_active,
             'usage': usage.get((pc.project.key, pc.circle.code), dict(EMPTY_USAGE)),
             'created_at': pc.created_at.isoformat(timespec='seconds')}
            for pc in ProjectCircle.objects.select_related('project', 'circle')]


@api_view(['GET', 'POST'])
@permission_classes([IsAdminRole])
@transaction.atomic
def associations(request):
    if request.method == 'POST':
        project = Project.objects.filter(key=request.data.get('project')).first()
        circle = Circle.objects.filter(code=str(request.data.get('circle') or '').upper()).first()
        if project is None or circle is None:
            raise ValidationError({'form': 'Choose an existing project and an existing circle.'})
        if not (project.is_active and circle.is_active):
            inactive = circle.code if project.is_active else project.key
            raise ValidationError({'form': f'{inactive} is inactive; activate it before associating.'})
        if ProjectCircle.objects.filter(project=project, circle=circle).exists():
            raise ValidationError({'form': f'{circle.code} is already associated with {project.key}.'})
        pc = ProjectCircle(project=project, circle=circle)
        _save(pc)
        services.record('association', pc, 'created', new={'project': project.key, 'circle': circle.code, 'is_active': True},
                        actor=request.user, reason=_reason(request))
        audit('org_association_created', request, project=project.key, circle=circle.code)
    return Response({'associations': _all_associations()}, status=201 if request.method == 'POST' else 200)


@api_view(['PATCH', 'DELETE'])
@permission_classes([IsAdminRole])
@transaction.atomic
def association_detail(request, pk: int):
    pc = _get(ProjectCircle, pk)
    state = {'project': pc.project.key, 'circle': pc.circle.code, 'is_active': pc.is_active}
    if request.method == 'DELETE':
        usage = services.usage_by_pair().get((pc.project.key, pc.circle.code), EMPTY_USAGE)
        used = {k: v for k, v in usage.items() if v and k != 'on_air_sites'}
        if used:
            # Records of this project and circle refer to it: kept (inactive, out of operational scope), never cascaded.
            outcome = 'deactivated' if pc.is_active else 'kept_inactive'
            if pc.is_active:
                pc.is_active = False
                _save(pc, ['is_active'])
                services.record('association', pc, 'deactivated', previous=state, new={**state, 'is_active': False}, actor=request.user,
                                reason=_reason(request) or 'Removal requested; kept inactive because records refer to it.', label=str(pc))
                audit('org_association_deactivated', request, project=pc.project.key, circle=pc.circle.code)
            return Response({'associations': _all_associations(), 'outcome': outcome, 'dependencies': used})
        services.record('association', pc, 'removed', previous=state, actor=request.user, reason=_reason(request), label=str(pc))
        audit('org_association_removed', request, project=pc.project.key, circle=pc.circle.code)
        pc.delete()
        return Response({'associations': _all_associations(), 'outcome': 'removed', 'dependencies': {}})
    if 'is_active' not in request.data or not isinstance(request.data['is_active'], bool):
        raise ValidationError({'is_active': 'Give true or false.'})
    if pc.is_active != request.data['is_active']:
        pc.is_active = request.data['is_active']
        _save(pc, ['is_active'])
        action = 'activated' if pc.is_active else 'deactivated'
        services.record('association', pc, action, previous=state, new={**state, 'is_active': pc.is_active}, actor=request.user,
                        reason=_reason(request), label=str(pc))
        audit('org_association_' + action, request, project=pc.project.key, circle=pc.circle.code)
    return Response({'associations': _all_associations()})


# --- Circle code mapping ---------------------------------------------------------------------------

def _alias_state(a: CircleAlias) -> dict:
    return {'source': a.source, 'project': a.project.key if a.project else None, 'raw_code': a.raw_code, 'circle': a.circle.code,
            'is_active': a.is_active, 'notes': a.notes}


def _all_aliases():
    rows = list(CircleAlias.objects.select_related('project', 'circle', 'created_by'))
    problems = services.alias_problems(rows)
    return {'aliases': [{'id': a.id, **_alias_state(a), 'circle_name': a.circle.name, 'source_label': a.get_source_display(),
                         'problems': problems.get(a.id, []), 'created_by': a.created_by.get_username() if a.created_by else 'system',
                         'updated_at': a.updated_at.isoformat(timespec='seconds')} for a in rows],
            'sources': [{'value': v, 'label': l} for v, l in CircleAlias.Source.choices],
            'site_id_mapping': _site_id_mapping()}


def _site_id_mapping() -> list[dict]:
    """How raw site identifiers resolve per project (raw/resolvers.py); separate from circle code aliases."""
    from apps.uptimedb.raw.resolvers import RESOLVERS
    rules = {'4G Saturation': 'The raw BTS IP ID is the master site ID, matched within the project and circle only.',
             'LWE': 'Not configured: the authoritative mapping from raw IDs (e.g. JHDTJN001) to master LWE IDs (e.g. LWEJH0001) and the '
                    '2100 / 700 MHz selection rule have not been supplied, so LWE rows are not imported.'}
    return [{'project': p, 'configured': bool(RESOLVERS.get(p) and RESOLVERS[p].configured),
             'rule': rules.get(p, 'No resolver: raw daily uploads are not configured for this project.')} for p in services.project_keys()]


def _alias_fields(request, alias: CircleAlias | None) -> dict:
    data, errors, out = request.data, {}, {}
    if alias is None or 'source' in data:
        if data.get('source') not in CircleAlias.Source.values:
            errors['source'] = 'Choose the source.'
        out['source'] = data.get('source')
    if alias is None or 'project' in data:
        key = data.get('project') or None
        project = Project.objects.filter(key=key).first() if key else None
        if key and project is None:
            errors['project'] = 'Unknown project.'
        out['project'] = project
    if alias is None or 'raw_code' in data:
        raw = ' '.join(str(data.get('raw_code') or '').split())
        if not raw or len(raw) > 60:
            errors['raw_code'] = 'Enter the code as the source writes it (up to 60 characters).'
        out['raw_code'], out['raw_key'] = raw, services.alias_key(raw)
    if alias is None or 'circle' in data:
        circle = Circle.objects.filter(code=str(data.get('circle') or '').upper()).first()
        if circle is None:
            errors['circle'] = 'Choose the canonical circle.'
        out['circle'] = circle
    if 'is_active' in data:
        out['is_active'] = bool(data['is_active'])
    if 'notes' in data:
        out['notes'] = str(data.get('notes') or '').strip()[:300]
    if errors:
        raise ValidationError(errors)
    circle = out.get('circle') or (alias.circle if alias else None)
    raw_key = out.get('raw_key', alias.raw_key if alias else '')
    other = Circle.objects.filter(code__iexact=raw_key).exclude(pk=circle.pk if circle else None).first()
    if other:
        raise ValidationError({'raw_code': f'"{raw_key.upper()}" is the code of circle {other.code}; it cannot mean another circle.'})
    return out


@api_view(['GET', 'POST'])
@permission_classes([IsAdminRole])
@transaction.atomic
def aliases(request):
    if request.method == 'POST':
        a = CircleAlias(**_alias_fields(request, None), created_by=request.user)
        _save(a)
        services.record('circle_alias', a, 'created', new=_alias_state(a), actor=request.user, reason=_reason(request),
                        label=f'{a.raw_code} → {a.circle.code}')
        audit('org_alias_created', request, source=a.source, raw=a.raw_code, circle=a.circle.code)
    return Response(_all_aliases(), status=201 if request.method == 'POST' else 200)


@api_view(['PATCH'])
@permission_classes([IsAdminRole])
@transaction.atomic
def alias_detail(request, pk: int):
    a = _get(CircleAlias, pk)
    before = _alias_state(a)
    for field, value in _alias_fields(request, a).items():
        setattr(a, field, value)
    if _alias_state(a) != before:
        _save(a)
        action = 'updated' if before['is_active'] == a.is_active else ('activated' if a.is_active else 'deactivated')
        services.record('circle_alias', a, action, previous=before, new=_alias_state(a), actor=request.user, reason=_reason(request),
                        label=f'{a.raw_code} → {a.circle.code}')
        audit('org_alias_' + action, request, source=a.source, raw=a.raw_code, circle=a.circle.code)
    return Response(_all_aliases())


# --- User access -----------------------------------------------------------------------------------

def _access_json(user) -> dict:
    role = role_of(user)
    legacy = legacy_circles(user)
    return {'id': user.pk, 'username': user.get_username(), 'name': user.get_full_name(), 'role': role,
            'role_label': ROLES.get(role or '', 'No role'), 'is_active': user.is_active,
            'limited': role not in (ADMIN, NOC_LEAD), 'pairs': [{'project': p, 'circle': c} for p, c in granted_pairs(user)],
            'legacy_circles': legacy, 'needs_review': bool(legacy)}


@api_view(['GET'])
@permission_classes([IsAdminRole])
def access(request):
    users = User.objects.prefetch_related('groups').select_related('portal_profile').order_by('username')
    return Response({'users': [_access_json(u) for u in users]})


@api_view(['PUT'])
@permission_classes([IsAdminRole])
@transaction.atomic
def access_detail(request, user_id: int):
    user = User.objects.filter(pk=user_id).first()
    if user is None:
        raise NotFound('No such user.')
    raw = request.data.get('pairs')
    if not isinstance(raw, list) or not all(isinstance(i, dict) for i in raw):
        raise ValidationError({'pairs': 'Give a list of {project, circle}.'})
    pairs = [(str(i.get('project') or ''), str(i.get('circle') or '').upper()) for i in raw]
    try:
        added, removed = set_pairs(user, pairs, actor=request.user, reason=_reason(request))
    except ValueError as exc:
        raise ValidationError({'pairs': str(exc)}) from exc
    audit('org_access_changed', request, user_id=user.pk, login_id=user.username,
          added=','.join(f'{p}/{c}' for p, c in added) or '-', removed=','.join(f'{p}/{c}' for p, c in removed) or '-')
    return Response({'user': _access_json(user)})


# --- History ---------------------------------------------------------------------------------------

@api_view(['GET'])
@permission_classes([IsAdminRole])
def history(request):
    qs = OrganizationChange.objects.all()
    kind = request.query_params.get('entity_type')
    if kind:
        qs = qs.filter(entity_type=kind)
    return Response({'changes': [{'id': h.id, 'entity_type': h.entity_type, 'entity_id': h.entity_id, 'entity_label': h.entity_label,
                                  'action': h.action, 'previous': h.previous, 'new': h.new, 'actor': h.actor_name or '-',
                                  'reason': h.reason, 'created_at': h.created_at.isoformat(timespec='seconds')} for h in qs[:500]]})
