"""Data Panel permissions per dataset.

The former ``master_data`` module (View, Export) covered every Master Data dataset. Each grant becomes the same action
on each dataset that existed then, so no role gains or loses anything; Add and Edit are new and granted to nobody
(Admins have them through the Admin role). Reversible: the per-dataset View / Export grants of a role fold back into
``master_data`` (Add and Edit grants are dropped on rollback, as the old catalogue had no such actions).
"""
from django.db import migrations

# Frozen: the datasets registered when this migration was written (apps.masterdata.datasets.DATASETS).
DATASETS = ['uptime_sites', 'uptime_daily', 'uptime_monthly', 'escalation', 'rca']


def forwards(apps, schema_editor):
    RolePermission = apps.get_model('accounts', 'RolePermission')
    AccessEvent = apps.get_model('accounts', 'AccessEvent')
    converted = []
    for old in RolePermission.objects.filter(module='master_data'):
        for key in DATASETS:
            RolePermission.objects.get_or_create(role_id=old.role_id, module=f'data_{key}', action=old.action)
        converted.append(f'{old.role_id}:{old.action}')
        old.delete()
    AccessEvent.objects.create(actor_name='system', action='data_panel_permissions_migrated',
                               details={'datasets': DATASETS, 'grants_converted': converted, 'add_edit_granted': []})


def backwards(apps, schema_editor):
    RolePermission = apps.get_model('accounts', 'RolePermission')
    rows = RolePermission.objects.filter(module__in=[f'data_{k}' for k in DATASETS])
    for role_id, action in set(rows.filter(action__in=['view', 'export']).values_list('role_id', 'action')):
        RolePermission.objects.get_or_create(role_id=role_id, module='master_data', action=action)
    rows.delete()


class Migration(migrations.Migration):
    dependencies = [('accounts', '0006_access_control')]
    operations = [migrations.RunPython(forwards, backwards)]
