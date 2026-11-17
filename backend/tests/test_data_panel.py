"""Data Panel editing on the data layer (apps.sitedata): per-dataset View / Add / Edit / Export permissions, read-only
derived datasets, Daily Performance changes as authorized corrections (with a reason) in one transaction, project/circle
scope and no delete. Synthetic records in the test database only."""
import importlib
from datetime import date
from unittest import mock

from django.apps import apps as django_apps
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts import catalog
from apps.accounts.models import Role, RolePermission
from apps.masterdata import datasets
from apps.rca.models import RcaEvent, RcaRecord
from apps.sitedata import daily, portfolio
from apps.sitedata.models import DailyPerformanceEvent, DailySitePerformance, MonthlySitePerformance, Site, SiteManualOverride, UploadBatch
from tests.auth_helpers import portal_user
from tests.sitedata_factory import make_daily, make_site

G4 = '4G Saturation'
REASON = 'CNMC ticket 4711: outage window confirmed'


class DataPanelCase(TestCase):
    def setUp(self):
        self.admin = portal_user('dp-admin', 'admin')
        self.mp = make_site('UVMP1', circle='MP', site_name='Alpha', ci_contact='9999900000')
        self.rj = make_site('UVRJ1', circle='RJ', site_name='Delta')
        self.day = make_daily(self.mp, date(2026, 10, 1), outage=10)
        self.rj_day = make_daily(self.rj, date(2026, 10, 1), outage=0)
        portfolio.clear_cache()
        self.addCleanup(portfolio.clear_cache)

    def save(self, key, user=None, changes=(), additions=(), reason=REASON):
        self.client.force_login(user or self.admin)
        body = {'changes': list(changes), 'additions': list(additions)}
        if reason is not None:
            body['reason'] = reason
        return self.client.post(reverse('master-save', args=[key]), body, content_type='application/json')

    def role(self, name, *actions, dataset='uptime_daily'):
        role = Role.objects.create(name=name)
        for action in actions:
            RolePermission.objects.create(role=role, module=catalog.data_module(dataset), action=action)
        return role

    def member(self, username, role, project=G4, circle='MP'):
        from apps.accounts import services
        user = portal_user(username, 'member')
        services.assign(self.admin, user, role, project, [circle])
        return user

    def corrections(self):
        return UploadBatch.objects.filter(kind=UploadBatch.Kind.CORRECTION)


class ReadOnlyDatasetTests(DataPanelCase):
    def test_monthly_is_read_only_and_escalation_has_a_scoped_editor(self):
        self.client.force_login(self.admin)
        listed = {d['key']: d['permissions'] for d in self.client.get(reverse('master-datasets')).json()['datasets']}
        self.assertEqual((listed['uptime_monthly']['edit'], listed['uptime_monthly']['add'],
                          listed['uptime_monthly']['editable'], listed['uptime_monthly']['addable']), (False, False, [], []))
        response = self.save('uptime_monthly', changes=[{'id': self.mp.pk, 'values': {'site_name': 'Changed'}}],
                             additions=[{'values': {'site_id': 'NEW1'}}])
        self.assertEqual(response.status_code, 400)
        self.assertIn('read-only', response.json()['error'])
        self.assertTrue(listed['escalation']['edit'])
        self.assertIn('ci_name', listed['escalation']['editable'])
        self.assertNotIn('bsnl_site_id', listed['escalation']['editable'])
        self.assertNotIn('circle', listed['escalation']['editable'])
        self.mp.refresh_from_db()
        self.assertEqual((self.mp.site_name, Site.objects.count()), ('Alpha', 2))
        self.assertTrue(listed['uptime_sites']['edit'])
        self.assertFalse(listed['uptime_sites']['add'])
        self.assertNotIn('site_id', listed['uptime_sites']['editable'])
        self.assertEqual((listed['uptime_daily']['edit'], listed['uptime_daily']['add'], listed['uptime_daily']['reason_required']), (True, True, True))
        self.assertEqual(listed['uptime_daily']['editable'], ['availability_pct', 'outage_minutes'])


class SiteEditingTests(DataPanelCase):
    def test_site_fields_are_validated_saved_and_record_the_matrix_baseline(self):
        response = self.save('uptime_sites', changes=[{'id': self.mp.pk, 'values': {'site_name': 'Manual Alpha'}}])
        self.assertEqual(response.status_code, 200, response.content)
        self.mp.refresh_from_db()
        override = SiteManualOverride.objects.get(site=self.mp, field='site_name')
        self.assertEqual((self.mp.site_name, override.matrix_value, override.updated_by), ('Manual Alpha', 'Alpha', self.admin))

        invalid = self.save('uptime_sites', changes=[{'id': self.mp.pk, 'values': {'site_name': 'x' * 201}}])
        self.assertEqual(invalid.status_code, 400)
        self.assertIn('site_name', invalid.json()['details']['changes'][str(self.mp.pk)])
        forbidden = self.save('uptime_sites', changes=[{'id': self.mp.pk, 'values': {'site_id': 'NEW-ID', 'circle': 'RJ'}}])
        self.assertEqual(forbidden.status_code, 400)
        self.assertEqual(forbidden.json()['details']['changes'][str(self.mp.pk)],
                         {'site_id': 'This column cannot be changed here.', 'circle': 'This column cannot be changed here.'})
        self.mp.refresh_from_db()
        self.assertEqual((self.mp.site_name, self.mp.circle), ('Manual Alpha', 'MP'))

    def test_numeric_boolean_and_effective_date_edits_preserve_derived_data_rules(self):
        response = self.save('uptime_sites', changes=[{'id': self.mp.pk, 'values': {
            'latitude': '24.5', 'on_air': 'No', 'om_start_date': '2026-10-01',
        }}])
        self.assertEqual(response.status_code, 200, response.content)
        self.mp.refresh_from_db()
        self.assertEqual((self.mp.latitude, self.mp.on_air, self.mp.on_air_status, self.mp.om_start_date),
                         (24.5, False, 'No', date(2026, 10, 1)))
        self.assertEqual(set(SiteManualOverride.objects.filter(site=self.mp).values_list('field', flat=True)),
                         {'latitude', 'on_air_status', 'om_start_date', 'om_start_raw'})
        self.assertTrue(MonthlySitePerformance.objects.filter(
            site=self.mp, month=date(2026, 10, 1), is_current=True, effective_from=date(2026, 10, 1),
        ).exists())

        invalid = self.save('uptime_sites', changes=[{'id': self.mp.pk, 'values': {'latitude': 'NaN'}}])
        self.assertEqual(invalid.status_code, 400)
        self.assertIn('Enter a number', invalid.json()['details']['changes'][str(self.mp.pk)]['latitude'])

    def test_stale_site_update_is_refused(self):
        version = self.mp.updated_at.isoformat()
        Site.objects.filter(pk=self.mp.pk).update(site_name='Changed elsewhere', updated_at=timezone.now())
        response = self.save('uptime_sites', changes=[{'id': self.mp.pk, 'updated_at': version, 'values': {'site_name': 'Stale edit'}}])
        self.assertEqual(response.status_code, 400)
        self.assertIn('changed after it was loaded', response.json()['details']['changes'][str(self.mp.pk)]['_row'])
        self.mp.refresh_from_db()
        self.assertEqual(self.mp.site_name, 'Changed elsewhere')


class EscalationEditingTests(DataPanelCase):
    def test_escalation_fields_are_saved_as_matrix_overrides(self):
        response = self.save('escalation', changes=[{'id': self.mp.pk, 'values': {'ci_name': 'Manual CI', 'il_name': 'Manual IL'}}])
        self.assertEqual(response.status_code, 200, response.content)
        self.mp.refresh_from_db()
        self.assertEqual((self.mp.ci_name, self.mp.il_name), ('Manual CI', 'Manual IL'))
        self.assertEqual(
            dict(SiteManualOverride.objects.filter(site=self.mp).values_list('field', 'matrix_value')),
            {'ci_name': '', 'il_name': ''},
        )

        invalid = self.save('escalation', changes=[{'id': self.mp.pk, 'values': {'ci_name': 'x' * 121}}])
        self.assertEqual(invalid.status_code, 400)
        self.assertIn('ci_name', invalid.json()['details']['changes'][str(self.mp.pk)])
        forbidden = self.save('escalation', changes=[{'id': self.mp.pk, 'values': {'site_id': 'NEW-ID', 'reporting_scope': 'outside_scope'}}])
        self.assertEqual(forbidden.status_code, 400)
        self.assertEqual(Site.objects.get(pk=self.mp.pk).ci_name, 'Manual CI')

    def test_escalation_permissions_and_project_circle_scope_are_independent(self):
        viewer = self.member('escalation-viewer', self.role('Escalation viewer', 'view', dataset='escalation'))
        self.assertEqual(self.save('escalation', viewer, changes=[{'id': self.mp.pk, 'values': {'ci_name': 'No grant'}}]).status_code, 403)
        editor = self.member('escalation-editor', self.role('Escalation editor', 'view', 'edit', dataset='escalation'))
        self.assertEqual(self.save('escalation', editor, changes=[{'id': self.mp.pk, 'values': {'ci_name': 'Scoped CI'}}]).status_code, 200)
        contact = self.save('escalation', editor, changes=[{'id': self.mp.pk, 'values': {'ci_contact': '9000000000'}}])
        self.assertEqual(contact.status_code, 400)
        self.assertEqual(contact.json()['details']['changes'][str(self.mp.pk)]['ci_contact'], 'This column cannot be changed here.')
        denied = self.save('escalation', editor, changes=[{'id': self.rj.pk, 'values': {'ci_name': 'Outside scope'}}])
        self.assertEqual(denied.status_code, 400)
        self.assertIn('outside the projects and circles', denied.json()['details']['changes'][str(self.rj.pk)]['_row'])


class DailyCorrectionTests(DataPanelCase):
    def test_an_edit_is_an_authorized_correction_with_its_reason(self):
        response = self.save('uptime_daily', changes=[{'id': self.day.pk, 'values': {'availability_pct': '99.5'}}])
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual((response.json()['updated'], response.json()['added']), (1, 0))
        self.day.refresh_from_db()
        self.assertAlmostEqual(self.day.availability_pct, 99.5)
        self.assertAlmostEqual(self.day.outage_minutes, 7.2)
        self.assertEqual((self.day.revision, self.day.batch.kind, daily.rank(self.day.batch.kind)), (2, UploadBatch.Kind.CORRECTION, 3))
        self.assertEqual((self.day.batch.uploaded_by, self.day.batch.remarks), (self.admin, REASON))
        event = DailyPerformanceEvent.objects.get(site=self.mp, report_date=date(2026, 10, 1))
        self.assertEqual((event.action, event.reason, event.user), (DailyPerformanceEvent.Action.CORRECTION, REASON, self.admin))
        self.assertAlmostEqual(event.stored_outage_minutes, 10)
        rows = self.client.get(reverse('master-records', args=['uptime_daily']), {'period': 'overall', 'site_id': 'UVMP1'}).json()['rows']
        self.assertEqual((rows[0]['source'], rows[0]['revision']), ('correction', 2))

    def test_outage_minutes_may_be_entered_instead(self):
        self.assertEqual(self.save('uptime_daily', changes=[{'id': self.day.pk, 'values': {'outage_minutes': '0'}}]).status_code, 200)
        self.day.refresh_from_db()
        self.assertEqual((self.day.availability_pct, self.day.outage_minutes), (100, 0))

    def test_the_same_value_is_no_correction(self):
        response = self.save('uptime_daily', changes=[{'id': self.day.pk, 'values': {'outage_minutes': '10'}}])
        self.assertEqual((response.status_code, response.json()['updated']), (200, 0))
        self.assertFalse(self.corrections().exists())

    def test_a_missing_site_day_is_added(self):
        response = self.save('uptime_daily', additions=[{'values': {'project': G4, 'circle': 'mp', 'site_id': ' uvmp1 ', 'date': '2026-10-02',
                                                                     'outage_minutes': '0'}}])
        self.assertEqual(response.status_code, 200, response.content)
        record = DailySitePerformance.objects.get(site=self.mp, report_date=date(2026, 10, 2))
        self.assertEqual((record.availability_pct, record.batch.kind, record.batch.remarks, record.technology, record.circle),
                         (100, UploadBatch.Kind.CORRECTION, REASON, G4, 'MP'))
        again = self.save('uptime_daily', additions=[{'values': {'site_id': 'UVMP1', 'date': '2026-10-02', 'availability_pct': '50'}}])
        self.assertEqual(again.status_code, 400)
        self.assertIn('already has a value', again.json()['details']['additions']['0']['_row'])

    def test_a_reason_is_required(self):
        for reason in (None, '', '   '):
            response = self.save('uptime_daily', changes=[{'id': self.day.pk, 'values': {'availability_pct': '50'}}], reason=reason)
            self.assertEqual(response.status_code, 400, reason)
            self.assertEqual(response.json()['details'], {'reason': 'Required.'})
        self.day.refresh_from_db()
        self.assertEqual((self.day.outage_minutes, self.corrections().count()), (10, 0))

    def test_a_finalized_month_is_refused(self):
        MonthlySitePerformance.objects.create(
            site=self.mp, month=date(2026, 10, 1), technology=G4, calculation_category=MonthlySitePerformance.Category.DAILY_DERIVED,
            total_outage_minutes=10, availability_pct=99.3, reporting_days=1, calendar_days=31, effective_from=date(2026, 10, 1),
            finalized_at=timezone.now())
        response = self.save('uptime_daily', changes=[{'id': self.day.pk, 'values': {'availability_pct': '50'}}])
        self.assertEqual(response.status_code, 400)
        self.assertIn('finalized', response.json()['details']['changes'][str(self.day.pk)]['_row'])
        added = self.save('uptime_daily', additions=[{'values': {'site_id': 'UVMP1', 'date': '2026-10-05', 'availability_pct': '50'}}])
        self.assertIn('finalized', added.json()['details']['additions']['0']['_row'])
        self.day.refresh_from_db()
        self.assertEqual((self.day.outage_minutes, self.corrections().count()), (10, 0))

    def test_one_invalid_cell_rolls_everything_back(self):
        response = self.save('uptime_daily', changes=[{'id': self.day.pk, 'values': {'outage_minutes': '20'}}],
                             additions=[{'values': {'site_id': 'UVMP1', 'date': '2026-10-03', 'outage_minutes': 'abc'}}])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['details']['additions'], {'0': {'outage_minutes': 'Enter a number.'}})
        self.day.refresh_from_db()
        self.assertEqual((self.day.outage_minutes, self.day.revision), (10, 1))  # the valid change was not saved either
        self.assertFalse(self.corrections().exists())
        self.assertFalse(DailyPerformanceEvent.objects.exists())

    def test_values_sites_and_columns_are_validated(self):
        def errors(response, kind='changes', key=None):
            self.assertEqual(response.status_code, 400, response.content)
            return response.json()['details'][kind][key or (str(self.day.pk) if kind == 'changes' else '0')]
        change = lambda values: self.save('uptime_daily', changes=[{'id': self.day.pk, 'values': values}])  # noqa: E731
        add = lambda values: self.save('uptime_daily', additions=[{'values': values}])  # noqa: E731
        self.assertIn('between 0 and 100', errors(change({'availability_pct': '101'}))['availability_pct'])
        self.assertIn('1,440', errors(change({'outage_minutes': '2000'}))['outage_minutes'])
        self.assertIn('cannot be removed', errors(change({'availability_pct': ''}))['availability_pct'])
        self.assertIn('disagree', errors(change({'availability_pct': '50', 'outage_minutes': '0'}))['outage_minutes'])
        self.assertEqual(errors(change({'date': '2026-10-09'})), {'date': 'This column cannot be changed here.'})  # identity of a value
        self.assertIn('not a Site Master site', errors(add({'site_id': 'NOPE', 'date': '2026-10-02', 'availability_pct': '1'}), 'additions')['site_id'])
        self.assertEqual(errors(add({'availability_pct': '1'}), 'additions'), {'site_id': 'Required.', 'date': 'Required.'})
        self.assertIn('circle MP', errors(add({'site_id': 'UVMP1', 'circle': 'RJ', 'date': '2026-10-02', 'availability_pct': '1'}), 'additions')['circle'])
        self.assertIn('4G Saturation site', errors(add({'site_id': 'UVMP1', 'project': 'LWE', 'date': '2026-10-02', 'availability_pct': '1'}), 'additions')['project'])
        self.assertIn('future', errors(add({'site_id': 'UVMP1', 'date': '2999-01-01', 'availability_pct': '1'}), 'additions')['date'])
        make_site('STMP1', circle='MP', outside_scope=True)
        self.assertIn('outside the dashboard', errors(add({'site_id': 'STMP1', 'date': '2026-10-02', 'availability_pct': '1'}), 'additions')['site_id'])
        self.assertFalse(self.corrections().exists())

    def test_a_correction_changes_what_the_dashboard_shows(self):
        def outage():
            portfolio.clear_cache()
            ds = portfolio.portfolio_dataset()
            return ds.outage[list(ds.sites['site_id']).index('UVMP1'), ds.position(date(2026, 10, 1))]
        self.assertAlmostEqual(outage(), 10)
        self.assertEqual(self.save('uptime_daily', changes=[{'id': self.day.pk, 'values': {'outage_minutes': '720'}}]).status_code, 200)
        self.assertAlmostEqual(outage(), 720)
        monthly = MonthlySitePerformance.objects.get(site=self.mp, month=date(2026, 10, 1), is_current=True,
                                                     calculation_category=MonthlySitePerformance.Category.DAILY_DERIVED)
        self.assertAlmostEqual(monthly.total_outage_minutes, 720)  # the monthly results were recalculated after the save

    def test_rca_edits_follow_the_register_rules_and_are_recorded(self):
        rec = RcaRecord.objects.create(reporting_date=date(2026, 10, 1), project=G4, project_raw='4G Satu', circle='MP', circle_raw='Madhya Pradesh',
                                       site_id='UVMP1', site_key='UVMP1', final_bucket='TCS', final_bucket_key='tcs', rca_text='', rca_key='')
        ok = self.save('rca', changes=[{'id': rec.pk, 'values': {'final_bucket': 'bsnl ofc '}}])  # an old blank RCA text is not this edit's fault
        self.assertEqual(ok.status_code, 200, ok.content)
        rec.refresh_from_db()
        # The approved BSNL OFC (case and surrounding spaces ignored), kept as entered (trimmed), never renamed.
        self.assertEqual((rec.final_bucket, rec.final_bucket_key, rec.project_raw), ('bsnl ofc', 'bsnl ofc', '4G Satu'))
        self.assertEqual(RcaEvent.objects.get(record=rec).changes['final_bucket'], {'from': 'TCS', 'to': 'bsnl ofc'})
        refused = self.save('rca', changes=[{'id': rec.pk, 'values': {'rca_text': ''}}])
        self.assertEqual(refused.status_code, 400)
        for values in ({'final_bucket': 'BSNL  OFC'}, {'final_bucket': 'TCS', 'bucket_2': 'SSA OFC'}):
            self.assertEqual(self.save('rca', changes=[{'id': rec.pk, 'values': values}]).status_code, 400, values)
        base = {'reporting_date': '2026-10-02', 'project': G4, 'circle': 'MP', 'site_id': 'UVMP1', 'rca_text': 'Fiber cut'}
        self.assertEqual(self.save('rca', additions=[{'values': base}]).status_code, 400)  # no Final Bucket
        added = self.save('rca', additions=[{'values': {**base, 'final_bucket': 'BSNL OFC'}}], reason=None)  # RCA needs no reason
        self.assertEqual(added.status_code, 200, added.content)
        self.assertEqual(RcaRecord.objects.get(rca_text='Fiber cut').source, RcaRecord.Source.MANUAL)


class PermissionTests(DataPanelCase):
    def test_view_only_cannot_save_or_export(self):
        user = self.member('viewer', self.role('Viewer', 'view'))
        self.client.force_login(user)
        listed = {d['key']: d['permissions'] for d in self.client.get(reverse('master-datasets')).json()['datasets']}
        self.assertEqual(list(listed), ['uptime_daily'])  # only the datasets granted
        self.assertEqual((listed['uptime_daily']['edit'], listed['uptime_daily']['add'], listed['uptime_daily']['export']), (False, False, False))
        self.assertEqual(self.save('uptime_daily', user, changes=[{'id': self.day.pk, 'values': {'outage_minutes': '1'}}]).status_code, 403)
        self.assertEqual(self.save('uptime_daily', user, additions=[{'values': {'site_id': 'UVMP1', 'date': '2026-10-02', 'outage_minutes': '1'}}]).status_code, 403)
        self.assertEqual(self.client.get(reverse('master-export', args=['uptime_daily'])).status_code, 403)
        self.assertEqual(self.client.get(reverse('master-records', args=['uptime_sites'])).status_code, 403)  # another dataset

    def test_edit_on_a_read_only_dataset_grants_nothing(self):
        user = self.member('monthly-editor', self.role('Monthly editor', 'view', 'edit', 'create', dataset='uptime_monthly'))
        self.client.force_login(user)
        caps = self.client.get(reverse('master-datasets')).json()['datasets'][0]['permissions']
        self.assertEqual((caps['edit'], caps['add']), (False, False))
        self.assertEqual(self.save('uptime_monthly', user, changes=[{'id': self.mp.pk, 'values': {'site_name': 'x'}}]).status_code, 400)

    def test_site_editor_is_limited_to_its_authorized_circle(self):
        user = self.member('site-editor', self.role('Site editor', 'view', 'edit', dataset='uptime_sites'))
        self.assertEqual(self.save('uptime_sites', user, changes=[{'id': self.mp.pk, 'values': {'site_name': 'Edited'}}]).status_code, 200)
        denied = self.save('uptime_sites', user, changes=[{'id': self.rj.pk, 'values': {'site_name': 'Out of scope'}}])
        self.assertEqual(denied.status_code, 400)
        self.assertIn('outside the projects and circles', denied.json()['details']['changes'][str(self.rj.pk)]['_row'])
        self.rj.refresh_from_db()
        self.assertEqual(self.rj.site_name, 'Delta')

    def test_edit_only_and_add_only_are_independent(self):
        editor = self.member('editor', self.role('Editor', 'view', 'edit'))
        self.assertEqual(self.save('uptime_daily', editor, changes=[{'id': self.day.pk, 'values': {'outage_minutes': '1'}}]).status_code, 200)
        self.assertEqual(self.save('uptime_daily', editor, additions=[{'values': {'site_id': 'UVMP1', 'date': '2026-10-02', 'outage_minutes': '1'}}]).status_code, 403)
        adder = self.member('adder', self.role('Adder', 'view', 'create'))
        self.assertEqual(self.save('uptime_daily', adder, additions=[{'values': {'site_id': 'UVMP1', 'date': '2026-10-02', 'outage_minutes': '1'}}]).status_code, 200)
        self.assertEqual(self.save('uptime_daily', adder, changes=[{'id': self.day.pk, 'values': {'outage_minutes': '2'}}]).status_code, 403)
        self.client.force_login(editor)
        self.assertEqual(self.client.get(reverse('master-export', args=['uptime_daily'])).status_code, 403)  # Edit gives no Export
        exporter = self.member('exporter', self.role('Exporter', 'view', 'export'))
        self.client.force_login(exporter)
        self.assertEqual(self.client.get(reverse('master-export', args=['uptime_daily'])).status_code, 200)

    def test_project_circle_scope_applies_to_corrections_and_additions(self):
        user = self.member('mp-editor', self.role('MP Editor', 'view', 'edit', 'create'))  # 4G MP only
        self.client.force_login(user)
        rows = self.client.get(reverse('master-records', args=['uptime_daily']), {'period': 'overall'}).json()['rows']
        self.assertEqual([r['site_id'] for r in rows], ['UVMP1'])
        other = self.save('uptime_daily', user, changes=[{'id': self.rj_day.pk, 'values': {'outage_minutes': '5'}}])
        self.assertIn('outside the projects and circles', other.json()['details']['changes'][str(self.rj_day.pk)]['_row'])
        added = self.save('uptime_daily', user, additions=[{'values': {'site_id': 'UVRJ1', 'date': '2026-10-02', 'outage_minutes': '5'}}])
        self.assertIn('Outside the projects and circles', added.json()['details']['additions']['0']['circle'])
        self.rj_day.refresh_from_db()
        self.assertEqual((self.rj_day.outage_minutes, self.corrections().count()), (0, 0))
        ok = self.save('uptime_daily', user, changes=[{'id': self.day.pk, 'values': {'outage_minutes': '5'}}])
        self.assertEqual(ok.status_code, 200, ok.content)  # an authorized (non-Admin) correction inside the scope
        self.assertEqual(DailyPerformanceEvent.objects.get().user, user)

    def test_granting_and_revoking_applies_at_once(self):
        from apps.accounts import services
        role = self.role('Granted', 'view', 'edit')
        user = self.member('dyn', role)
        self.assertEqual(self.save('uptime_daily', user, changes=[{'id': self.day.pk, 'values': {'outage_minutes': '1'}}]).status_code, 200)
        services.update_role(self.admin, role, permissions=[{'module': 'data_uptime_daily', 'action': 'view'}])
        self.assertEqual(self.save('uptime_daily', user, changes=[{'id': self.day.pk, 'values': {'outage_minutes': '2'}}]).status_code, 403)

    def test_there_is_no_delete_anywhere(self):
        self.client.force_login(self.admin)
        for name in ('master-save', 'master-records', 'master-export', 'master-options'):
            self.assertEqual(self.client.delete(reverse(name, args=['uptime_daily'])).status_code, 405, name)
        self.assertNotIn('delete', {a for m in catalog.modules().values() for a in m['actions']})
        self.save('uptime_daily', changes=[{'id': self.day.pk, 'values': {'outage_minutes': '3'}}])
        self.assertEqual(DailySitePerformance.objects.count(), 2)  # rows not in the payload are untouched


class FrameworkTests(TestCase):
    def test_a_new_dataset_gets_its_permissions_without_code_changes(self):
        extra = datasets.Dataset('future_table', 'Future table', 'A dataset added later.', lambda: Site.objects.all(), (), 'technology', 'circle')
        with mock.patch.dict(datasets.DATASETS, {'future_table': extra}):
            module = catalog.modules()['data_future_table']
            self.assertEqual(list(module['actions']), ['view', 'create', 'edit', 'export'])
            self.assertTrue(catalog.is_known('data_future_table', 'export'))

    def test_dataset_keys_and_permission_modules_are_unchanged(self):
        self.assertEqual(list(datasets.DATASETS), ['uptime_sites', 'uptime_daily', 'uptime_monthly', 'escalation', 'rca'])
        self.assertTrue(all(catalog.is_known(f'data_{k}', 'view') for k in datasets.DATASETS))

    def test_existing_master_data_grants_convert_without_broadening(self):
        role = Role.objects.create(name='Old viewer')
        RolePermission.objects.create(role=role, module='master_data', action='view')
        importlib.import_module('apps.accounts.migrations.0007_data_panel_permissions').forwards(django_apps, None)
        grants = set(RolePermission.objects.filter(role=role).values_list('module', 'action'))
        self.assertEqual(grants, {(f'data_{k}', 'view') for k in ('uptime_sites', 'uptime_daily', 'uptime_monthly', 'escalation', 'rca')})
