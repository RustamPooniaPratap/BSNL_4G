"""Endpoint discovery for the API Registry: every (URL name, HTTP method) of the portal's URL configuration.

Read from Django's URL resolver and the DRF view classes only (no view is called). ``sync()`` records new endpoints as
Pending, refreshes the metadata of known ones, marks vanished ones as not present, and never changes a review decision
except that an endpoint which has become blocked can no longer stay Approved.
"""
from __future__ import annotations

import inspect
import re
from dataclasses import dataclass, field

from django.db import transaction
from django.urls import URLPattern, URLResolver, get_resolver
from django.utils import timezone

from .models import ApiEndpoint

METHODS = ('GET', 'POST', 'PUT', 'PATCH', 'DELETE')

# Route prefix -> portal area shown in the registry (first match wins).
MODULES = (
    ('/api/auth/', 'Authentication & Users'),
    ('/api/dashboard/', 'Dashboard'),
    ('/api/all-kpis/', "All KPI's"),
    ('/api/site-portfolio/', 'Site Portfolio'),
    ('/api/rca/', 'RCA'),
    ('/api/organization/', 'Organization'),
    ('/api/master-data/', 'Data Panel'),
    ('/api/alerts/', 'Alerts'),
    ('/api/tickets/', 'Ticket Management'),
    ('/api/bsnl/', 'BSNL Module'),
    ('/api/email/', 'Email'),
    ('/api/api-master/', 'API Master'),
    ('/api/raw-uploads/', 'Uptime Data Upload'),
    ('/api/arrival-tracker/', 'Uptime Data Upload'),
    ('/api/upload/', 'Master Workbook'),
    ('/api/raw-files/', 'Master Workbook'),
    ('/api/sitedata/', 'Data Imports & Corrections'),
    ('/api/health/', 'System'),
)

# Areas that are never exposed to external applications, whatever the endpoint.
BLOCKED_MODULES = {
    'Authentication & Users': 'Authentication and user management',
    'Organization': 'Organization administration',
    'Data Panel': 'Data Panel record editing and exports',
    'Alerts': 'Alert and email administration',
    'Ticket Management': 'Ticket records and notifications are internal only',
    'BSNL Module': 'Report emails, recipients and BSNL letters are internal only',
    'Email': 'Email sending',
    'API Master': 'API Master administration',
    'Uptime Data Upload': 'Data upload and processing',
    'Master Workbook': 'Master workbook administration',
    'Data Imports & Corrections': 'Data imports, corrections and finalisation',
    'System': 'Internal system endpoint',
}
OPEN_PERMISSIONS = {'AllowAny', 'IsSignedIn'}
ADMIN_PERMISSIONS = {'IsAdminRole', 'AdminForWrites'}
UPLOAD_PERMISSIONS = {'CanUploadRca'}
FILE_WORDS = re.compile(r'(upload|import|preview|commit|discard|correction|export|download|report|\.csv|\.xlsx)', re.I)
# Internal endpoints that describe the data source rather than business data.
INTERNAL_NAMES = {'dashboard-workbook': 'Internal data-source status', 'dashboard-source': 'Internal data-source status'}
# Response fields that must be reviewed before an approval (staff names, site-level records).
FIELD_REVIEW = {
    'dashboard-records': 'Site-level records (site details, team names)',
    'dashboard-record-detail': 'Site-level record detail',
    'rca-records': 'Individual RCA records (site, remarks, follow-up)',
    'rca-record': 'Individual RCA record, comments and history',
    'dashboard-om-heads': 'Names of O&M Head users',
    'dashboard-alerts': 'Operational alert details',
    'allkpis-hierarchy': 'CI / IE names per row',
    'allkpis-sites': 'Site-level records',
    'allkpis-rca': 'RCA records',
    'site-portfolio-breakdowns': 'Names of O&M Head users per circle (om_heads)',
}
PARAM = re.compile(r'<(?:(?P<type>\w+):)?(?P<name>\w+)>')


@dataclass
class Found:
    key: str
    url_name: str
    path: str
    method: str
    module: str
    name: str
    description: str
    view: str
    permission_classes: list[str]
    authentication_classes: list[str]
    path_params: list[dict] = field(default_factory=list)
    blocked: bool = False
    block_reason: str = ''
    field_review: str = ''


def _walk(patterns, prefix=''):
    for p in patterns:
        if isinstance(p, URLResolver):
            yield from _walk(p.url_patterns, prefix + str(p.pattern))
        elif isinstance(p, URLPattern):
            yield prefix + str(p.pattern), p


def _view_class(callback):
    return getattr(callback, 'cls', None) or getattr(callback, 'view_class', None)


def _methods(callback, cls) -> list[str]:
    actions = getattr(callback, 'actions', None)
    if actions:
        return sorted(m.upper() for m in actions if m.upper() in METHODS)
    if cls is None:
        return []
    return [m for m in METHODS if hasattr(cls, m.lower())]


def _docstring(callback, cls, method: str) -> str:
    """The first paragraph of the handler's docstring (the function for @api_view views, else the class or method)."""
    candidates = [getattr(cls, method.lower(), None), callback.__dict__.get('__wrapped__'), cls, callback]
    if getattr(cls, '__name__', '') == 'WrappedAPIView':  # @api_view: the docstring is on the decorated function
        candidates.insert(0, getattr(cls, method.lower(), None))
    for obj in candidates:
        doc = inspect.getdoc(obj) if obj is not None else None
        if doc and not doc.startswith(('Function that', 'APIView', 'Intentionally simple parent class')):
            return doc.split('\n\n', 1)[0].replace('\n', ' ').strip()
    return ''


def _module(path: str) -> str:
    return next((label for prefix, label in MODULES if path.startswith(prefix)), 'Other')


def _title(url_name: str, method: str) -> str:
    words = url_name.replace('_', '-').split('-')
    return f'{method} ' + ' '.join(w if w.isupper() else w.capitalize() for w in words if w)


def classify(item: Found) -> Found:
    """Blocked reason (first rule that applies) and the field-review note. Order matters: the most specific reason first."""
    perms = set(item.permission_classes)
    reason = ''
    if item.module in BLOCKED_MODULES:
        reason = BLOCKED_MODULES[item.module]
    elif perms & OPEN_PERMISSIONS or not item.authentication_classes:
        reason = 'Authentication flow or open endpoint'
    elif perms & ADMIN_PERMISSIONS:
        reason = 'Admin-only endpoint'
    elif item.method != 'GET':
        reason = 'Write operation: not exposed externally'
    elif perms & UPLOAD_PERMISSIONS or any(p.startswith(('Can_csv_upload', 'Can_rca_upload')) for p in perms):
        reason = 'Upload endpoint'
    elif FILE_WORDS.search(item.path) or any(p.endswith('_export') for p in perms):
        reason = 'Upload, import, export or file download'
    elif item.url_name in INTERNAL_NAMES:
        reason = INTERNAL_NAMES[item.url_name]
    item.blocked, item.block_reason = bool(reason), reason
    item.field_review = '' if reason else FIELD_REVIEW.get(item.url_name, '')
    return item


def discover() -> list[Found]:
    found = []
    for route, pattern in _walk(get_resolver().url_patterns):
        callback = pattern.callback
        cls = _view_class(callback)
        if not pattern.name:
            continue
        path = '/' + route.replace('^', '').replace('$', '')
        params = [{'name': m['name'], 'type': m['type'] or 'str'} for m in PARAM.finditer(path)]
        perms = [c.__name__ for c in getattr(cls, 'permission_classes', [])] if cls else []
        auth = [c.__name__ for c in getattr(cls, 'authentication_classes', [])] if cls else []
        for method in _methods(callback, cls):
            found.append(classify(Found(
                key=f'{pattern.name}:{method}', url_name=pattern.name, path=path, method=method, module=_module(path),
                name=_title(pattern.name, method), description=_docstring(callback, cls, method),
                view=f'{callback.__module__}.{getattr(callback, "__name__", cls.__name__ if cls else "?")}',
                permission_classes=perms, authentication_classes=auth, path_params=params)))
    return found


def sync() -> dict:
    """Bring the registry in line with the URL configuration. Returns counts of what changed."""
    now = timezone.now()
    found = {f.key: f for f in discover()}
    created = updated = vanished = revoked = 0
    with transaction.atomic():
        existing = {e.key: e for e in ApiEndpoint.objects.select_for_update()}
        for key, f in found.items():
            values = {k: getattr(f, k) for k in ('url_name', 'path', 'method', 'module', 'name', 'description', 'view',
                                                  'permission_classes', 'authentication_classes', 'path_params', 'blocked',
                                                  'block_reason', 'field_review')}
            row = existing.get(key)
            if row is None:
                ApiEndpoint.objects.create(key=key, last_seen=now, present=True, **values)
                created += 1
                continue
            changed = any(getattr(row, k) != v for k, v in values.items()) or not row.present
            for k, v in values.items():
                setattr(row, k, v)
            row.present, row.last_seen = True, now
            if row.blocked and row.status == ApiEndpoint.Status.APPROVED:  # newly blocked: it can no longer be approved
                row.status = ApiEndpoint.Status.PENDING
                row.review_note = f'Returned to Pending by discovery: {row.block_reason}.'
                revoked += 1
            row.save()
            updated += int(changed)
        for key, row in existing.items():
            if key not in found and row.present:
                row.present = False
                row.save(update_fields=['present', 'updated_at'])
                vanished += 1
    return {'discovered': len(found), 'created': created, 'updated': updated, 'no_longer_present': vanished,
            'approvals_withdrawn': revoked, 'total': ApiEndpoint.objects.count()}
