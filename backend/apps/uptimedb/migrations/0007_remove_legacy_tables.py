"""Permanent removal of the legacy operational tables. The data layer (apps.sitedata) is the only operational data
layer; no application code reads or writes these tables any more, and their data is not migrated (approved decision).

The tables are dropped with explicit DROP TABLE statements WITHOUT CASCADE, children before parents, so the drop fails
(and the migration rolls back) if any database object still depended on them: daily and monthly performance and the
escalation sites first, then the site master, the import batches and the settings table (replaced by common.Setting).
Each DROP TABLE removes only that table's own constraints and indexes. The Django model state is removed separately
(SeparateDatabaseAndState), because Django's own DeleteModel would emit DROP TABLE ... CASCADE on PostgreSQL.

The apps.uptimedb package remains only as this migration history (other apps' historical migrations depend on it); it
has no models, views or code. The reverse recreates the empty tables from the historical schema; data comes back only
from a backup.
"""
from django.db import migrations

# Drop order: tables that reference others first. (model name, table)
TABLES = (
    ('SiteDailyPerformance', 'uptimedb_sitedailyperformance'),
    ('SiteMonthlyPerformance', 'uptimedb_sitemonthlyperformance'),
    ('EscalationSite', 'uptimedb_escalationsite'),
    ('UptimeSite', 'uptimedb_uptimesite'),
    ('DataImportBatch', 'uptimedb_dataimportbatch'),
    ('EscalationImportBatch', 'uptimedb_escalationimportbatch'),
    ('AppSetting', 'uptimedb_appsetting'),
)


def drop_tables(apps, schema_editor):
    for _model, table in TABLES:
        schema_editor.execute(f'DROP TABLE {schema_editor.quote_name(table)}')  # no CASCADE: dependents make it fail


def recreate_tables(apps, schema_editor):
    """Empty tables as migration 0006 left them (parents first)."""
    from django.db.migrations.loader import MigrationLoader
    state = MigrationLoader(schema_editor.connection).project_state(('uptimedb', '0006_drop_site_overview'))
    for model, _table in reversed(TABLES):
        schema_editor.create_model(state.apps.get_model('uptimedb', model))


class Migration(migrations.Migration):

    dependencies = [
        ('uptimedb', '0006_drop_site_overview'),
        ('common', '0001_setting'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(drop_tables, recreate_tables)],
            state_operations=[migrations.DeleteModel(name=model) for model, _table in TABLES],
        ),
    ]
