"""Drop the legacy site_overview view (uptimedb_uptimesite + uptimedb_escalationsite + rca_rcarecord) before the legacy
tables are removed (0007). No application code reads it; the data layer (apps.sitedata) replaces it.

Runs after the RCA migrations that last recreated the view (rca 0004/0005) and after organization 0002, whose data
step reads uptimedb.UptimeSite on a fresh database. Reversible: the reverse recreates the view as rca 0004 left it.
"""
from importlib import import_module

from django.db import migrations

VIEW = import_module('apps.rca.migrations.0004_incident_occurrence').VIEW


class Migration(migrations.Migration):

    dependencies = [
        ('uptimedb', '0005_data_panel_batch_kind'),
        ('rca', '0005_upload_types'),
        ('organization', '0003_access_moved_to_assignments'),
    ]

    operations = [
        migrations.RunSQL('DROP VIEW IF EXISTS site_overview', reverse_sql=VIEW),
    ]
