from django.db import migrations


PERMISSIONS = (
    ('ticket_management', 'view'),
    ('ticket_management', 'upload'),
    ('ticket_management', 'close'),
    ('ticket_management', 'reopen'),
    ('ticket_management', 'retry'),
)


def forwards(apps, schema_editor):
    Role = apps.get_model('accounts', 'Role')
    RolePermission = apps.get_model('accounts', 'RolePermission')
    role = Role.objects.filter(system_key='ci').first()
    if role is not None:
        for module, action in PERMISSIONS:
            RolePermission.objects.get_or_create(role_id=role.pk, module=module, action=action)


def backwards(apps, schema_editor):
    RolePermission = apps.get_model('accounts', 'RolePermission')
    RolePermission.objects.filter(role__system_key='ci', module='ticket_management',
                                  action__in=[action for _, action in PERMISSIONS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0007_data_panel_permissions'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
