"""Initial organization, from what the application already used (verified on 30 Oct 2026, read only):

- Projects: "4G Saturation" and "LWE", the two report types of the site master and the Master workbook.
- Circles: the 11 circle codes of the site master (accounts.scope.KNOWN_CIRCLES), once each, named as the application's
  existing circle-name aliases name them.
- Associations: the 13 project/circle pairs of both the active Master workbook (4G_LWE_Consolidated_Oct'26-Last_Changes,
  sha256 60c1f6f857) and PostgreSQL's site master (identical: 4G Saturation MP, OD, RJ; LWE AP, BH, CG, JH, MH, MP, OD,
  TL, UP, WB), plus any other pair the site master holds when the migration runs. Nothing else is created: no sites, data,
  obligations or access.
- Circle code aliases: exactly the mappings the code applied before (raw CSV "OR" -> OD; the Master workbook's
  "Madhya Pradesh" and "Odisha"; the state names of the escalation matrix, day-wise and RCA files).
- Legacy circle-only CI assignments become project-specific grants only when the circle belongs to exactly one
  project (the same access as before); the others stay as they are, flagged for review.

Idempotent: existing rows are kept, nothing is overwritten or deleted.
"""
from django.db import migrations

PROJECTS = [('4G Saturation', '4G', '4G Saturation', 10), ('LWE', 'LWE', 'LWE', 20)]
CIRCLES = {
    'AP': 'Andhra Pradesh', 'BH': 'Bihar', 'CG': 'Chhattisgarh', 'JH': 'Jharkhand', 'MH': 'Maharashtra', 'MP': 'Madhya Pradesh',
    'OD': 'Odisha', 'RJ': 'Rajasthan', 'TL': 'Telangana', 'UP': 'Uttar Pradesh', 'WB': 'West Bengal',
}
ASSOCIATIONS = [('4G Saturation', c) for c in ('MP', 'OD', 'RJ')] + [('LWE', c) for c in ('AP', 'BH', 'CG', 'JH', 'MH', 'MP', 'OD', 'TL', 'UP', 'WB')]

# State names (and spellings) used by the escalation matrix, as in apps.dashboard.activity.CIRCLES.
STATE_NAMES = {
    'odisha': 'OD', 'orissa': 'OD', 'rajasthan': 'RJ', 'madhya pradesh': 'MP', 'jharkhand': 'JH', 'bihar': 'BH',
    'chhattisgarh': 'CG', 'uttar pradesh': 'UP', 'west bengal': 'WB', 'andhra pradesh': 'AP', 'telangana': 'TL', 'maharashtra': 'MH',
    'chattishgarh': 'CG', 'chhattishgarh': 'CG', 'maharastra': 'MH', 'telangna': 'TL', 'west bangal': 'WB',
}
# As in apps.rca.parser.CIRCLES.
RCA_NAMES = {
    'odisha': 'OD', 'orissa': 'OD', 'rajasthan': 'RJ', 'madhya pradesh': 'MP', 'jharkhand': 'JH', 'bihar': 'BH',
    'chhattisgarh': 'CG', 'chhatisgarh': 'CG', 'chattisgarh': 'CG', 'chattishgarh': 'CG', 'chhattishgarh': 'CG', 'uttar pradesh': 'UP',
    'west bengal': 'WB', 'andhra pradesh': 'AP', 'telangana': 'TL', 'maharashtra': 'MH',
}
WORKBOOK_NAMES = {'Madhya Pradesh': 'MP', 'Odisha': 'OD'}  # apps.dashboard.workbook.CIRCLE_ALIASES (LWE rows)
ALIASES = (
    [('raw_daily_csv', 'OR', 'OD', 'Verified: the Odisha daily dump writes OR for the master\'s OD (same UVOR... sites).')]
    + [('master_workbook', raw, code, 'Up-Time Report LWE rows write the state name.') for raw, code in WORKBOOK_NAMES.items()]
    + [('daywise_report', raw, code, 'Established day-wise report alias.') for raw, code in {**WORKBOOK_NAMES, **STATE_NAMES}.items()]
    + [('escalation_matrix', raw, code, 'Established escalation matrix spelling.') for raw, code in STATE_NAMES.items()]
    + [('rca_workbook', raw, code, 'Established RCA workbook spelling.') for raw, code in RCA_NAMES.items()]
)


def _key(raw):
    return ' '.join(str(raw).split()).casefold()


def forwards(apps, schema_editor):
    Project = apps.get_model('organization', 'Project')
    Circle = apps.get_model('organization', 'Circle')
    ProjectCircle = apps.get_model('organization', 'ProjectCircle')
    CircleAlias = apps.get_model('organization', 'CircleAlias')
    UserCircleAccess = apps.get_model('organization', 'UserCircleAccess')
    Change = apps.get_model('organization', 'OrganizationChange')
    UptimeSite = apps.get_model('uptimedb', 'UptimeSite')
    AccountProfile = apps.get_model('accounts', 'AccountProfile')

    created = {'projects': 0, 'circles': 0, 'associations': 0, 'aliases': 0}
    projects = {}
    for key, code, name, order in PROJECTS:
        projects[key], new = Project.objects.get_or_create(key=key, defaults={'code': code, 'name': name, 'sort_order': order})
        created['projects'] += new
    stored = sorted(set(UptimeSite.objects.values_list('project', 'circle').distinct()))
    for project, _ in stored:  # a project in the site master that is not one of the two (none on 30 Oct 2026)
        if project not in projects:
            projects[project], new = Project.objects.get_or_create(key=project, defaults={'code': project[:12], 'name': project, 'sort_order': 100})
            created['projects'] += new
    circles = {}
    for code, name in CIRCLES.items():
        circles[code], new = Circle.objects.get_or_create(code=code, defaults={'name': name})
        created['circles'] += new
    for _, code in stored:
        if code not in circles:  # named by its code until an Admin names it (none on 30 Oct 2026)
            circles[code], new = Circle.objects.get_or_create(code=code, defaults={'name': code, 'description': 'From the site master; name to be confirmed.'})
            created['circles'] += new
    for project, code in sorted(set(ASSOCIATIONS) | set(stored)):
        _, new = ProjectCircle.objects.get_or_create(project=projects[project], circle=circles[code])
        created['associations'] += new
    for source, raw, code, notes in ALIASES:
        _, new = CircleAlias.objects.get_or_create(source=source, project=None, raw_key=_key(raw),
                                                   defaults={'raw_code': raw, 'circle': circles[code], 'notes': notes})
        created['aliases'] += new
    if any(created.values()):
        Change.objects.create(entity_type='organization', entity_id='-', entity_label='Organization', action='initialised',
                              new=created, actor_name='system',
                              reason='Seeded from the site master, the active Master workbook and the aliases the application already used.')

    # Legacy circle-only CI assignments.
    by_circle = {}
    for pc in ProjectCircle.objects.select_related('project', 'circle'):
        by_circle.setdefault(pc.circle.code, []).append(pc)
    for profile in AccountProfile.objects.select_related('user'):
        legacy = sorted({str(c).upper() for c in (profile.circles or [])})
        if not legacy:
            continue
        keep, converted = [], []
        for code in legacy:
            links = by_circle.get(code, [])
            if len(links) == 1:
                UserCircleAccess.objects.get_or_create(user=profile.user, project_circle=links[0])
                converted.append([links[0].project.key, code])
            else:
                keep.append(code)  # several projects (or none): kept as it was, for an Admin to review
        if converted:
            profile.circles = keep
            profile.save(update_fields=['circles'])
            Change.objects.create(entity_type='user_access', entity_id=str(profile.user_id), entity_label=profile.user.username[:120],
                                  action='legacy_migrated', previous={'legacy_circles': legacy},
                                  new={'pairs': converted, 'legacy_circles': keep}, actor_name='system',
                                  reason='Circle-only assignment converted where the circle belongs to one project only.')


class Migration(migrations.Migration):

    dependencies = [
        ('organization', '0001_initial'),
        ('uptimedb', '0004_raw_daily_uploads'),
        ('accounts', '0004_account_circles'),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
