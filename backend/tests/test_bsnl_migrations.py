import importlib
import unittest
from unittest.mock import patch


seed_migration = importlib.import_module('apps.bsnl.migrations.0002_seed_bucket_mapping')


class MappingManager:
    def __init__(self):
        self.rows = {}

    def get_or_create(self, *, final_bucket, defaults):
        if final_bucket in self.rows:
            return self.rows[final_bucket], False
        row = {'final_bucket': final_bucket, **defaults}
        self.rows[final_bucket] = row
        return row, True


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
