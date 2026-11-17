import importlib
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch


seed_migration = importlib.import_module('apps.bsnl.migrations.0002_seed_bucket_mapping')
classification_migration = importlib.import_module('apps.bsnl.migrations.0003_central_responsibility_mapping')


class MappingManager:
    def __init__(self):
        self.rows = {}

    def get_or_create(self, *, final_bucket, defaults):
        if final_bucket in self.rows:
            return self.rows[final_bucket], False
        row = {'final_bucket': final_bucket, **defaults}
        self.rows[final_bucket] = row
        return row, True

    def filter(self, **criteria):
        manager = self

        class Query:
            def update(self, **values):
                matched = 0
                for row in manager.rows.values():
                    def matches(key, value):
                        if key == 'updated_by__isnull' and value:
                            return row.get('updated_by_id') is None
                        if key.endswith('__in'):
                            return row.get(key[:-4]) in value
                        if key.endswith('__lte'):
                            return row.get(key[:-5]) <= value
                        return row.get(key) == value

                    if all(matches(key, value) for key, value in criteria.items()):
                        row.update(values)
                        matched += 1
                return matched

        return Query()


class MappingModel:
    objects = MappingManager()


class MigrationApps:
    @staticmethod
    def get_model(app_label, model_name):
        if (app_label, model_name) != ('bsnl', 'RcaBucketMapping'):
            raise AssertionError(f'Unexpected model lookup: {app_label}.{model_name}')
        return MappingModel


class SeedBucketMappingMigrationTests(unittest.TestCase):
    def setUp(self):
        MappingModel.objects = MappingManager()

    def test_forward_seed_is_idempotent_and_preserves_existing_values(self):
        approved = {'BSNL OFC': (), 'BSNL Media': (), 'IaasP Power': ()}
        with patch('apps.rca.taxonomy.APPROVED', approved):
            seed_migration.forwards(MigrationApps, None)
            MappingModel.objects.rows['BSNL OFC']['bucket'] = 'Pending'
            seed_migration.forwards(MigrationApps, None)

        self.assertEqual(len(MappingModel.objects.rows), len(approved))
        self.assertEqual(MappingModel.objects.rows['BSNL OFC']['bucket'], 'Pending')
        self.assertEqual(MappingModel.objects.rows['BSNL Media']['bucket'], 'Customer')
        self.assertEqual(MappingModel.objects.rows['IaasP Power']['bucket'], 'Own')

    def test_reverse_is_noop_and_preserves_existing_mappings(self):
        MappingModel.objects.rows = {
            'BSNL OFC': {'final_bucket': 'BSNL OFC', 'bucket': 'Pending'},
            'Admin-added mapping': {'final_bucket': 'Admin-added mapping', 'bucket': 'Third party'},
        }
        before = {key: row.copy() for key, row in MappingModel.objects.rows.items()}
        operation = seed_migration.Migration.operations[0]

        self.assertIs(operation.reverse_code, seed_migration.migrations.RunPython.noop)
        operation.reverse_code(MigrationApps, None)

        self.assertEqual(MappingModel.objects.rows, before)


class CentralMappingMigrationTests(unittest.TestCase):
    def setUp(self):
        MappingModel.objects = MappingManager()

    def test_only_untouched_seeded_own_rows_move_to_third_party(self):
        seed_applied = datetime(2026, 1, 1, tzinfo=timezone.utc)
        MappingModel.objects.rows = {
            'Others': {'final_bucket': 'Others', 'bucket': 'Own', 'updated_by_id': None,
                       'updated_at': datetime(2025, 12, 31, tzinfo=timezone.utc)},
            'TCS': {'final_bucket': 'TCS', 'bucket': 'Own', 'updated_by_id': None,
                    'updated_at': datetime(2025, 12, 31, tzinfo=timezone.utc)},
            'DMW': {'final_bucket': 'DMW', 'bucket': 'Own', 'updated_by_id': 7,
                    'updated_at': datetime(2026, 1, 2, tzinfo=timezone.utc)},
            'HFCL': {'final_bucket': 'HFCL', 'bucket': 'Own', 'updated_by_id': None,
                     'updated_at': datetime(2026, 1, 2, tzinfo=timezone.utc)},
            'IaasP Power': {'final_bucket': 'IaasP Power', 'bucket': 'Own'},
            'BSNL OFC': {'final_bucket': 'BSNL OFC', 'bucket': 'Customer'},
        }

        with patch.object(classification_migration, 'MigrationRecorder') as migration_recorder:
            migration_recorder.return_value.migration_qs.filter.return_value.values_list.return_value.first.return_value = seed_applied
            classification_migration.update_untouched_defaults(MigrationApps, SimpleNamespace(connection=object()))

        self.assertEqual(MappingModel.objects.rows['Others']['bucket'], 'Third party')
        self.assertEqual(MappingModel.objects.rows['TCS']['bucket'], 'Third party')
        self.assertEqual(MappingModel.objects.rows['DMW']['bucket'], 'Own')
        self.assertEqual(MappingModel.objects.rows['HFCL']['bucket'], 'Own')
        self.assertEqual(MappingModel.objects.rows['IaasP Power']['bucket'], 'Own')
        self.assertEqual(MappingModel.objects.rows['BSNL OFC']['bucket'], 'Customer')
        operation = classification_migration.Migration.operations[1]
        self.assertIs(operation.reverse_code, classification_migration.migrations.RunPython.noop)
