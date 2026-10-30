"""The group of users allowed to upload consolidated RCA workbooks (besides Admins). Created empty: nobody is added
automatically; Admins add users on Users & Roles."""
from django.db import migrations

GROUP = 'RCA Consolidated Uploaders'


def create(apps, schema_editor):
    apps.get_model('auth', 'Group').objects.get_or_create(name=GROUP)


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0004_account_circles'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [migrations.RunPython(create, migrations.RunPython.noop)]
