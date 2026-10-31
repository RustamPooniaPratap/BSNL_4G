"""The permission catalogue: every module and action a role can be granted, each matching endpoints that check it.

Only operations the backend enforces are listed. Pages that stay with the Admin role (Team Performance, CSV Arrival
Tracking, Data Source, RCA Submissions and cause mappings, Organization, Users & Roles, Alert) are not grantable: a
custom role can never reach administrative functions.
"""
from __future__ import annotations

VIEW, CREATE, EDIT, EXPORT, UPLOAD = 'view', 'create', 'edit', 'export', 'upload'
ACTION_LABELS = {VIEW: 'View', CREATE: 'Create', EDIT: 'Edit', EXPORT: 'Export / Download', UPLOAD: 'Upload'}

# module -> label, description, {action: what it allows}
MODULES: dict[str, dict] = {
    'dashboard': {
        'label': 'Dashboard & Uptime',
        'description': 'Overview, 4G Saturation / LWE, Threshold Analysis, Site Portfolio and site details.',
        'actions': {VIEW: 'See KPIs, charts, site tables and site details of the assigned projects and circles.',
                    EXPORT: 'Download the Daily and Consolidated uptime reports (assigned circles only).'},
    },
    'master_data': {
        'label': 'Master Data',
        'description': 'Uptime master, escalation matrix and RCA data explorer.',
        'actions': {VIEW: 'Browse and search the records of the assigned projects and circles.',
                    EXPORT: 'Export the filtered records (assigned circles only).'},
    },
    'csv_upload': {
        'label': 'CSV Upload',
        'description': 'Data Entry: raw daily CSV upload, Add Row and Add Site.',
        'actions': {UPLOAD: 'Validate, preview and import raw daily CSV files for the assigned circles, and see their own uploads.'},
    },
    'rca_register': {
        'label': 'RCA Register',
        'description': 'The RCA records and their follow-up.',
        'actions': {VIEW: 'Browse RCA records of the assigned circles (historical records).',
                    CREATE: 'Record a new RCA manually (assigned circles only).',
                    EDIT: 'Edit their own manual records, update follow-up up to Action Completed and comment.'},
    },
    'rca_upload': {
        'label': 'RCA Upload',
        'description': 'Upload Circle RCA.',
        'actions': {UPLOAD: 'Validate, preview and import circle RCA files for the assigned circles, and see their own '
                            'uploads. Gives no access to the RCA register or summary.'},
    },
    'rca_summary': {
        'label': 'RCA Summary',
        'description': 'RCA overview, circle-wise breakdown, root causes and trends.',
        'actions': {VIEW: 'See the RCA summary pages, limited to the assigned projects and circles.'},
    },
}

ADMIN_ONLY = ['Team Performance', 'CSV Arrival Tracking', 'Data Source', 'RCA Submissions', 'RCA cause mappings',
              'Consolidated RCA upload (all circles; Users & Roles group)', 'Organization', 'Users & Roles', 'Alert']

# The built-in CI role: what CI users could do before custom roles, now limited to their assigned projects and circles.
CI_PERMISSIONS = [('dashboard', VIEW), ('dashboard', EXPORT), ('master_data', VIEW), ('master_data', EXPORT),
                  ('csv_upload', UPLOAD), ('rca_register', VIEW), ('rca_register', CREATE), ('rca_register', EDIT),
                  ('rca_upload', UPLOAD)]
# NOC Lead: every project and circle, everything above except the RCA summary (Admin and granted roles only).
NOC_LEAD_PERMISSIONS = CI_PERMISSIONS


def is_known(module: str, action: str) -> bool:
    return action in MODULES.get(module, {}).get('actions', {})


def as_json() -> dict:
    return {'modules': [{'key': k, 'label': m['label'], 'description': m['description'],
                         'actions': [{'key': a, 'label': ACTION_LABELS[a], 'description': d} for a, d in m['actions'].items()]}
                        for k, m in MODULES.items()],
            'admin_only': ADMIN_ONLY}
