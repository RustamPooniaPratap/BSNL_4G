"""Create the two portal role groups (Admin, CI). Adds rows to auth_group only."""
from django.db import migrations

ROLE_GROUPS = ('Admin', 'CI')


def create_groups(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    for name in ROLE_GROUPS:
        Group.objects.get_or_create(name=name)


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0001_initial'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]
    # Reversing leaves the groups in place: deleting them would drop users' role assignments.
    operations = [migrations.RunPython(create_groups, migrations.RunPython.noop)]
