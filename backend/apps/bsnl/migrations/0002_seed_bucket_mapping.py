"""Seeds the RCA bucket mapping decided on 17 Nov 2026: BSNL OFC and BSNL Media are the Customer (BSNL) bucket; every
other approved Final Bucket is Own. Admins change it on the BSNL Letters page (rows are never overwritten here)."""
from django.db import migrations

CUSTOMER = ('BSNL OFC', 'BSNL Media')


def forwards(apps, schema_editor):
    from apps.rca.taxonomy import APPROVED
    Mapping = apps.get_model('bsnl', 'RcaBucketMapping')
    for final in APPROVED:
        Mapping.objects.get_or_create(final_bucket=final, defaults={'bucket': 'Customer' if final in CUSTOMER else 'Own'})


class Migration(migrations.Migration):

    dependencies = [('bsnl', '0001_initial')]

    # Preserve seeded rows on reverse because admins may have since edited or added mappings.
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
