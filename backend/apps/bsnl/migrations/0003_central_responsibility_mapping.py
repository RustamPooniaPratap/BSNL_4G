from django.db import migrations, models
from django.db.migrations.recorder import MigrationRecorder


THIRD_PARTY_DEFAULTS = ('Others', 'TCS', 'DMW', 'HFCL')


def update_untouched_defaults(apps, schema_editor):
    seed_applied = MigrationRecorder(schema_editor.connection).migration_qs.filter(
        app='bsnl', name='0002_seed_bucket_mapping',
    ).values_list('applied', flat=True).first()
    if seed_applied is None:
        return
    Mapping = apps.get_model('bsnl', 'RcaBucketMapping')
    # A deleted editor becomes NULL via SET_NULL, so also distinguish seeded rows by their update timestamp.
    Mapping.objects.filter(final_bucket__in=THIRD_PARTY_DEFAULTS, bucket='Own', updated_by__isnull=True,
                          updated_at__lte=seed_applied) \
        .update(bucket='Third party')


class Migration(migrations.Migration):

    dependencies = [('bsnl', '0002_seed_bucket_mapping')]

    operations = [
        migrations.AlterField(
            model_name='rcabucketmapping',
            name='bucket',
            field=models.CharField(
                choices=[
                    ('Own', 'Own'),
                    ('Customer', 'Customer (BSNL)'),
                    ('Third party', 'Third party'),
                    ('Pending', 'Pending'),
                    ('Unclassified', 'Unclassified'),
                ],
                max_length=12,
            ),
        ),
        migrations.RunPython(update_untouched_defaults, migrations.RunPython.noop),
    ]
