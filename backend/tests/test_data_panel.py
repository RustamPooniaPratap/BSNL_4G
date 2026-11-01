"""Data Panel editing: per-dataset View / Add / Edit / Export permissions, one-transaction saves with validation and
rollback, project/circle scope, provenance and no delete. Synthetic records in the test database only."""
import importlib
from datetime import date
from unittest import mock

from django.apps import apps as django_apps
from django.test import TestCase
from django.urls import reverse

from apps.accounts import catalog
from apps.accounts.models import Role, RolePermission
from apps.masterdata import datasets
from apps.rca.models import RcaEvent, RcaRecord
from apps.uptimedb.models import DataImportBatch, EscalationImportBatch, EscalationSite, SiteDailyPerformance, UptimeSite
from tests.auth_helpers import portal_user

G4 = '4G Saturation'


class DataPanelCase(TestCase):
    def setUp(self):
        self.admin = portal_user('dp-admin', 'admin')
        batch = DataImportBatch.objects.create(original_filename='master.xlsx', checksum_sha256='x', sheet_name='Up-Time Report', stored_path='-',
                                               status=DataImportBatch.Status.COMMITTED)
        self.mp = UptimeSite.objects.create(project=G4, circle='MP', site_id='UVMP1', site_key='UVMP1', site_name='Alpha', on_air=True,
                                            on_air_raw='Yes', batch=batch, source_row=2)
        self.rj = UptimeSite.objects.create(project=G4, circle='RJ', site_id='UVRJ1', site_key='UVRJ1', site_name='Delta', batch=batch, source_row=3)
        self.day = SiteDailyPerformance.objects.create(site=self.mp, date=date(2026, 10, 1), outage_minutes=10, batch=batch)
        self.import_batch = batch

    def save(self, key, user=None, changes=(), additions=()):
        self.client.force_login(user or self.admin)
        return self.client.post(reverse('master-save', args=[key]), {'changes': list(changes), 'additions': list(additions)},
                                content_type='application/json')

    def role(self, name, *actions, dataset='uptime_sites'):
        role = Role.objects.create(name=name)
        for action in actions:
            RolePermission.objects.create(role=role, module=catalog.data_module(dataset), action=action)
        return role

    def member(self, username, role, project=G4, circle='MP'):
        from apps.accounts import services
        user = portal_user(username, 'member')
        services.assign(self.admin, user, role, project, [circle])
        return user


class AdminEditingTests(DataPanelCase):
    def test_several_edits_save_together_with_provenance_and_persist(self):
        response = self.save('uptime_sites', changes=[{'id': self.mp.pk, 'values': {'site_name': 'Alpha North', 'on_air': 'No'}},
                                                       {'id': self.rj.pk, 'values': {'oa': 'JAIPUR'}}])
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['updated'], 2)
        self.mp.refresh_from_db()
        self.assertEqual((self.mp.site_name, self.mp.on_air, self.mp.on_air_raw), ('Alpha North', False, 'No'))
        self.assertEqual(self.mp.batch.kind, DataImportBatch.Kind.DATA_PANEL)  # traceable to this save
        self.assertEqual(self.mp.batch.imported_by, self.admin)
        rows = self.client.get(reverse('master-records', args=['uptime_sites']), {'q': 'UVMP1'}).json()['rows']
        self.assertEqual(rows[0]['site_name'], 'Alpha North')  # as stored

    def test_any_admin_may_edit_and_add(self):
        second = portal_user('dp-admin-2', 'admin')
        added = self.save('uptime_daily', second, additions=[{'values': {'project': G4, 'circle': 'MP', 'site_id': 'uvmp1', 'date': '2026-10-02',
                                                                          'outage_minutes': '0'}}])
        self.assertEqual(added.status_code, 200, added.content)
        self.assertTrue(SiteDailyPerformance.objects.filter(site=self.mp, date=date(2026, 10, 2), outage_minutes=0).exists())

    def test_one_invalid_cell_rolls_everything_back(self):
        response = self.save('uptime_daily', changes=[{'id': self.day.pk, 'values': {'outage_minutes': '20'}}],
                             additions=[{'values': {'project': G4, 'circle': 'MP', 'site_id': 'UVMP1', 'date': '2026-10-03', 'outage_minutes': 'abc'}}])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['details']['additions'], {'0': {'outage_minutes': 'Enter a number.'}})
        self.day.refresh_from_db()
        self.assertEqual(self.day.outage_minutes, 10)  # the valid change was not saved either
        self.assertFalse(DataImportBatch.objects.filter(kind=DataImportBatch.Kind.DATA_PANEL).exists())

    def test_rules_unique_identity_associations_and_ranges(self):
        duplicate = self.save('uptime_sites', additions=[{'values': {'project': G4, 'circle': 'mp', 'site_id': ' uvmp1 '}}])
        self.assertEqual(duplicate.json()['details']['additions']['0'], {'site_id': 'A record with the same identity already exists (each must be unique).'})
        outside = self.save('uptime_sites', additions=[{'values': {'project': G4, 'circle': 'BH', 'site_id': 'UVBH1'}}])
        self.assertIn('not a circle of', outside.json()['details']['additions']['0']['circle'])
        unknown_site = self.save('uptime_daily', additions=[{'values': {'project': G4, 'circle': 'MP', 'site_id': 'NOPE', 'date': '2026-10-02'}}])
        self.assertIn('not a Site Master site', unknown_site.json()['details']['additions']['0']['site_id'])
        too_much = self.save('uptime_daily', changes=[{'id': self.day.pk, 'values': {'outage_minutes': '2000'}}])
        self.assertIn('1,440', too_much.json()['details']['changes'][str(self.day.pk)]['outage_minutes'])
        missing = self.save('uptime_sites', additions=[{'values': {'project': G4, 'circle': 'MP'}}])
        self.assertEqual(missing.json()['details']['additions']['0'], {'site_id': 'Required.'})
        frozen = self.save('uptime_daily', changes=[{'id': self.day.pk, 'values': {'date': '2026-10-09'}}])  # identity of a daily value
        self.assertEqual(frozen.json()['details']['changes'][str(self.day.pk)], {'date': 'This column cannot be changed here.'})
        self.assertEqual(UptimeSite.objects.count(), 2)

    def test_blank_numbers_are_not_reported_never_zero(self):
        self.save('uptime_daily', changes=[{'id': self.day.pk, 'values': {'outage_minutes': ''}}])
        self.day.refresh_from_db()
        self.assertIsNone(self.day.outage_minutes)

    def test_rca_edits_follow_the_register_rules_and_are_recorded(self):
        rec = RcaRecord.objects.create(reporting_date=date(2026, 10, 1), project=G4, project_raw='4G Satu', circle='MP', circle_raw='Madhya Pradesh',
                                       site_id='UVMP1', site_key='UVMP1', final_bucket='TCS', final_bucket_key='tcs', rca_text='', rca_key='')
        ok = self.save('rca', changes=[{'id': rec.pk, 'values': {'final_bucket': 'BSNL  OFC'}}])  # an old blank RCA text is not this edit's fault
        self.assertEqual(ok.status_code, 200, ok.content)
        rec.refresh_from_db()
        self.assertEqual((rec.final_bucket, rec.final_bucket_key, rec.project_raw), ('BSNL  OFC', 'bsnl ofc', '4G Satu'))
        self.assertEqual(RcaEvent.objects.get(record=rec).changes['final_bucket'], {'from': 'TCS', 'to': 'BSNL  OFC'})
        refused = self.save('rca', changes=[{'id': rec.pk, 'values': {'rca_text': ''}}])
        self.assertEqual(refused.status_code, 400)
        added = self.save('rca', additions=[{'values': {'reporting_date': '2026-10-02', 'project': G4, 'circle': 'MP', 'site_id': 'UVMP1', 'rca_text': 'Fiber cut'}}])
        self.assertEqual(added.status_code, 200, added.content)
        self.assertEqual(RcaRecord.objects.get(rca_text='Fiber cut').source, RcaRecord.Source.MANUAL)

    def test_escalation_edits_keep_raw_dates_and_links_in_step(self):
        batch = EscalationImportBatch.objects.create(original_filename='m.xlsx', checksum_sha256='x', sheet_name='Raw Data', stored_path='-')
        row = EscalationSite.objects.create(project=G4, circle='MP', site_id='UVMPX', site_key='UVMPX', batch=batch, source_row=2)
        response = self.save('escalation', changes=[{'id': row.pk, 'values': {'site_id': 'UVMP1', 'om_start_date': '2026-10-05'}}])
        self.assertEqual(response.status_code, 200, response.content)
        row.refresh_from_db()
        self.assertEqual((row.site_key, row.om_start_raw, row.uptime_site_id, row.match_status), ('UVMP1', '2026-10-05', self.mp.pk, 'matched'))
        self.assertEqual(row.batch.initiated_via, 'data_panel')


class PermissionTests(DataPanelCase):
    def test_view_only_cannot_save_or_export(self):
        user = self.member('viewer', self.role('Viewer', 'view'))
        self.client.force_login(user)
        listed = {d['key']: d['permissions'] for d in self.client.get(reverse('master-datasets')).json()['datasets']}
        self.assertEqual(list(listed), ['uptime_sites'])  # only the datasets granted
        self.assertEqual((listed['uptime_sites']['edit'], listed['uptime_sites']['add'], listed['uptime_sites']['export']), (False, False, False))
        self.assertEqual(self.save('uptime_sites', user, changes=[{'id': self.mp.pk, 'values': {'site_name': 'x'}}]).status_code, 403)
        self.assertEqual(self.save('uptime_sites', user, additions=[{'values': {'project': G4, 'circle': 'MP', 'site_id': 'N1'}}]).status_code, 403)
        self.assertEqual(self.client.get(reverse('master-export', args=['uptime_sites'])).status_code, 403)
        self.assertEqual(self.client.get(reverse('master-records', args=['uptime_daily'])).status_code, 403)  # another dataset

    def test_edit_only_and_add_only_are_independent(self):
        editor = self.member('editor', self.role('Editor', 'view', 'edit'))
        self.assertEqual(self.save('uptime_sites', editor, changes=[{'id': self.mp.pk, 'values': {'site_name': 'Edited'}}]).status_code, 200)
        self.assertEqual(self.save('uptime_sites', editor, additions=[{'values': {'project': G4, 'circle': 'MP', 'site_id': 'N1'}}]).status_code, 403)
        adder = self.member('adder', self.role('Adder', 'view', 'create'))
        self.assertEqual(self.save('uptime_sites', adder, additions=[{'values': {'project': G4, 'circle': 'MP', 'site_id': 'N1'}}]).status_code, 200)
        self.assertEqual(self.save('uptime_sites', adder, changes=[{'id': self.mp.pk, 'values': {'site_name': 'x'}}]).status_code, 403)
        self.client.force_login(editor)
        self.assertEqual(self.client.get(reverse('master-export', args=['uptime_sites'])).status_code, 403)  # Edit gives no Export
        exporter = self.member('exporter', self.role('Exporter', 'view', 'export'))
        self.client.force_login(exporter)
        self.assertEqual(self.client.get(reverse('master-export', args=['uptime_sites'])).status_code, 200)

    def test_project_circle_scope_applies_to_edits_and_additions(self):
        user = self.member('mp-editor', self.role('MP Editor', 'view', 'edit', 'create'))  # 4G MP only
        other = self.save('uptime_sites', user, changes=[{'id': self.rj.pk, 'values': {'site_name': 'x'}}])
        self.assertIn('outside the projects and circles', other.json()['details']['changes'][str(self.rj.pk)]['_row'])
        moved = self.save('uptime_sites', user, changes=[{'id': self.mp.pk, 'values': {'circle': 'RJ'}}])
        self.assertIn('Outside the projects and circles', moved.json()['details']['changes'][str(self.mp.pk)]['circle'])
        added = self.save('uptime_sites', user, additions=[{'values': {'project': G4, 'circle': 'RJ', 'site_id': 'N2'}}])
        self.assertEqual(added.status_code, 400)
        self.rj.refresh_from_db()
        self.assertEqual((self.rj.site_name, UptimeSite.objects.count()), ('Delta', 2))

    def test_granting_and_revoking_applies_at_once(self):
        from apps.accounts import services
        role = self.role('Granted', 'view', 'edit')
        user = self.member('dyn', role)
        self.assertEqual(self.save('uptime_sites', user, changes=[{'id': self.mp.pk, 'values': {'site_name': 'A'}}]).status_code, 200)
        services.update_role(self.admin, role, permissions=[{'module': 'data_uptime_sites', 'action': 'view'}])
        self.assertEqual(self.save('uptime_sites', user, changes=[{'id': self.mp.pk, 'values': {'site_name': 'B'}}]).status_code, 403)

    def test_there_is_no_delete_anywhere(self):
        self.client.force_login(self.admin)
        for name in ('master-save', 'master-records', 'master-export', 'master-options'):
            self.assertEqual(self.client.delete(reverse(name, args=['uptime_sites'])).status_code, 405, name)
        self.assertNotIn('delete', {a for m in catalog.modules().values() for a in m['actions']})
        self.save('uptime_sites', changes=[{'id': self.mp.pk, 'values': {'site_name': 'only this'}}])
        self.assertEqual(UptimeSite.objects.count(), 2)  # rows not in the payload are untouched


class FrameworkTests(TestCase):
    def test_a_new_dataset_gets_its_permissions_without_code_changes(self):
        extra = datasets.Dataset('future_table', 'Future table', 'A dataset added later.', lambda: UptimeSite.objects.all(), (), 'project', 'circle')
        with mock.patch.dict(datasets.DATASETS, {'future_table': extra}):
            module = catalog.modules()['data_future_table']
            self.assertEqual(list(module['actions']), ['view', 'create', 'edit', 'export'])
            self.assertTrue(catalog.is_known('data_future_table', 'export'))

    def test_existing_master_data_grants_convert_without_broadening(self):
        role = Role.objects.create(name='Old viewer')
        RolePermission.objects.create(role=role, module='master_data', action='view')
        importlib.import_module('apps.accounts.migrations.0007_data_panel_permissions').forwards(django_apps, None)
        grants = set(RolePermission.objects.filter(role=role).values_list('module', 'action'))
        self.assertEqual(grants, {(f'data_{k}', 'view') for k in ('uptime_sites', 'uptime_daily', 'uptime_monthly', 'escalation', 'rca')})
