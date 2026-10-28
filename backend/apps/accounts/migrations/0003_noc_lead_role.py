"""Create the NOC Lead role group. Adds one row to auth_group only."""
from django.db import migrations


def create_group(apps, schema_editor):
    apps.get_model('auth', 'Group').objects.get_or_create(name='NOC Lead')


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0002_portal_roles'),
    ]
    # Reversing leaves the group in place: deleting it would drop users' role assignments.
    operations = [migrations.RunPython(create_group, migrations.RunPython.noop)]
