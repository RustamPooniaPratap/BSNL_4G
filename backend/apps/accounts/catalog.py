"""The permission catalogue: every module and action a role can be granted, each matching endpoints that check it.

Data Panel (Master Data) datasets are modules of their own, generated from the dataset registry
(``apps.masterdata.datasets.DATASETS``): ``data_<dataset key>`` with View, Add, Edit and Export, so a dataset added
there is configurable on Users & Roles without any change here. There is no Delete action anywhere.

Only operations the backend enforces are listed. Pages that stay with the Admin role (Team Performance, CSV Arrival
Tracking, Data Source, RCA Submissions and cause mappings, Organization, Users & Roles, Alert) are not grantable: a
custom role can never reach administrative functions.
"""
from __future__ import annotations

VIEW, CREATE, EDIT, EXPORT, UPLOAD = 'view', 'create', 'edit', 'export', 'upload'
CLOSE, REOPEN, RETRY = 'close', 'reopen', 'retry'
APPROVE, SEND, MANAGE = 'approve', 'send', 'manage'
ACTION_LABELS = {VIEW: 'View', CREATE: 'Add', EDIT: 'Edit', EXPORT: 'Export / Download', UPLOAD: 'Upload',
                 CLOSE: 'Close tickets', REOPEN: 'Reopen tickets', RETRY: 'Retry email',
                 APPROVE: 'Approve', SEND: 'Send email', MANAGE: 'Manage settings'}

# module -> label, description, {action: what it allows}. Data Panel modules are added by ``modules()``.
STATIC_MODULES: dict[str, dict] = {
    'dashboard': {
        'label': 'Dashboard & Uptime',
        'description': 'Overview, 4G Saturation / LWE, Threshold Analysis, Site Portfolio and site details.',
        'actions': {VIEW: 'See KPIs, charts, site tables and site details of the assigned projects and circles.',
                    EXPORT: 'Download the Daily and Consolidated uptime reports (assigned circles only).'},
    },
    'csv_upload': {
        'label': 'CSV Upload',
        'description': 'Uptime Data: raw daily CSV upload (Uptime Data Upload).',
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
    'ticket_management': {
        'label': 'Ticket Management',
        'description': 'OFC outage tickets, Excel imports, status changes and ticket notifications.',
        'actions': {
            VIEW: 'View tickets, details, dashboard metrics and notification history within the assigned project/circle scope.',
            UPLOAD: 'Validate and import the official OFC ticket workbook within the assigned project/circle scope.',
            CLOSE: 'Manually close open tickets with mandatory closure remarks.',
            REOPEN: 'Reopen closed tickets with a mandatory reason and send a notification.',
            RETRY: 'Retry failed ticket email notifications within the assigned project/circle scope.',
        },
    },
    'bsnl_reports': {
        'label': 'BSNL Module · Auto Email Reports',
        'description': 'D-1 and Weekly Circle report emails, their Excel attachments and delivery history.',
        'actions': {VIEW: 'See the reports, email previews and delivery history, and download the emails (.eml) and Excel '
                          'attachments of the assigned projects and circles.',
                    SEND: 'Send a report email now through the portal account (needs every project of the circle; '
                          'All India: every circle).',
                    MANAGE: 'Edit the Distribution Master (report recipients) and switch the daily / weekly schedule on or off.'},
    },
    'bsnl_letters': {
        'label': 'BSNL Module · BSNL Letters',
        'description': 'Letters to BSNL listing Customer (BSNL)-bucket outages per circle, their approval and sending.',
        'actions': {VIEW: 'See the letters, the register and the annexures, and download Word / Excel / PDF files.',
                    EDIT: 'Create Draft letters, edit and regenerate them.',
                    APPROVE: 'Approve letters and record their later status (sent outside the portal, acknowledged, '
                             'exclusion accepted / rejected).',
                    SEND: 'Send approved letters by email through the portal account.',
                    MANAGE: 'Edit BSNL circle contacts, sender details, letter recipients and the RCA bucket mapping.'},
    },
}

ADMIN_ONLY = ['Team Performance', 'CSV Arrival Tracking', 'Data Source', 'RCA Submissions', 'RCA cause mappings',
              'Consolidated RCA upload (all circles; Users & Roles group)', 'Organization', 'Users & Roles', 'Alert']

DATA_PREFIX = 'data_'


def data_module(dataset_key: str) -> str:
    return f'{DATA_PREFIX}{dataset_key}'


def data_modules() -> dict[str, dict]:
    """One module per Data Panel dataset (read from the registry on each call, so new datasets appear)."""
    from apps.masterdata.datasets import DATASETS
    return {data_module(d.key): {
        'label': f'Data Panel · {d.label}', 'description': d.description, 'data_panel': True,
        'actions': {VIEW: 'Browse, search and filter the records of the assigned projects and circles.',
                    CREATE: 'Add new records in the assigned projects and circles (never delete).',
                    EDIT: 'Change values of existing records in the assigned projects and circles (never delete).',
                    EXPORT: 'Download the filtered records (CSV / Excel) of the assigned projects and circles.'}}
        for d in DATASETS.values()}


def modules() -> dict[str, dict]:
    return {**STATIC_MODULES, **data_modules()}


# The built-in CI role: what CI users could do before custom roles, limited to their assigned projects and circles.
# Data Panel: View and Export of the datasets they could open before (``master_data`` view and export), never Add or Edit.
CI_PERMISSIONS = [('dashboard', VIEW), ('dashboard', EXPORT), ('csv_upload', UPLOAD), ('rca_register', VIEW), ('rca_register', CREATE),
                  ('rca_register', EDIT), ('rca_upload', UPLOAD), ('ticket_management', VIEW), ('ticket_management', UPLOAD),
                  ('ticket_management', CLOSE), ('ticket_management', REOPEN), ('ticket_management', RETRY)]


def noc_lead_permissions() -> set[tuple[str, str]]:
    """NOC Lead: every project and circle; the CI permissions and View / Export of every Data Panel dataset (as with the
    former Master Data module), never Add or Edit, and not the RCA summary (Admin and granted roles only). BSNL Module:
    View of both pages and Draft letter editing; approving, sending and settings stay with Admin and granted roles."""
    return (set(CI_PERMISSIONS) | {(m, a) for m in data_modules() for a in (VIEW, EXPORT)}
            | {('bsnl_reports', VIEW), ('bsnl_letters', VIEW), ('bsnl_letters', EDIT)})


def is_known(module: str, action: str) -> bool:
    return action in modules().get(module, {}).get('actions', {})


def as_json() -> dict:
    return {'modules': [{'key': k, 'label': m['label'], 'description': m['description'], 'data_panel': m.get('data_panel', False),
                         'actions': [{'key': a, 'label': ACTION_LABELS[a], 'description': d} for a, d in m['actions'].items()]}
                        for k, m in modules().items()],
            'admin_only': ADMIN_ONLY}
