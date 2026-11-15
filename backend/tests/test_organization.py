"""Organization (Administration > Organization): projects, global circles, associations, circle code mapping, project/circle
user access, change history, and how uploads, imports, exports and RCA use them. Isolated test data only (SQLite).

Sites, daily and monthly records and uploads are the data layer's (apps.sitedata): the project is the site's technology."""
import csv
import io
import tempfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pandas as pd
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import AccountProfile
from apps.accounts.scope import allowed_pairs, forget_profile, may_use, set_circles, set_pairs
from apps.dashboard import report_export
from apps.organization import services
from apps.accounts.models import AccessAssignment
from apps.organization.models import Circle, CircleAlias, OrganizationChange, Project, ProjectCircle
from apps.rca.models import RcaRecord
from apps.sitedata.models import DailySitePerformance, MonthlySitePerformance, Site, SiteIdentifier, UploadBatch
from tests.auth_helpers import portal_user
from tests.sitedata_factory import make_daily, make_site

SEEDED = [('4G Saturation', c) for c in ('MP', 'OD', 'RJ')] + [('LWE', c) for c in ('AP', 'BH', 'CG', 'JH', 'MH', 'MP', 'OD', 'TL', 'UP', 'WB')]


HEADER = ['SrNo', 'BTS IP ID', 'BTS Name', 'Circle', 'SSAID', 'TCS Onair', 'Band category', 'Site Type', 'Nw Avail (2G)',
          'Nw Avail (4G)', 'Nw Avail (4G TCS)', 'Outage Min.', 'Site Category', 'Report Date']


def row(site_id, tcs, *, circle='OR', day='13-10-2026'):
    """A row of a synthetic CNMC daily dump."""
    return ['1', site_id, 'Site', circle, 'SSA', 'Y', 'B', 'SA', '', '', tcs, '0', 'NORMAL', day]


def csv_bytes(rows) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator='\r\n')
    writer.writerow(HEADER)
    writer.writerows(rows)
    return out.getvalue().encode('utf-8')


def site(project, circle, site_id, **extra):
    """A dashboard-scope site of the site master (sitedata.Site) of ``project`` (its technology)."""
    return make_site(site_id, technology=project, circle=circle, **extra)


def monthly(s, month, outage):
    return MonthlySitePerformance.objects.create(site=s, month=month, technology=s.technology,
                                                 calculation_category=MonthlySitePerformance.Category.DAILY_DERIVED,
                                                 total_outage_minutes=outage, availability_pct=100.0, reporting_days=1, calendar_days=31,
                                                 effective_from=month)


class OrgTestCase(TestCase):
    def setUp(self):
        self.admin = portal_user('org-admin', 'admin')
        self.noc = portal_user('org-noc', 'noc_lead')
        self.ci = portal_user('org-ci', 'ci')
        self.client.force_login(self.admin)

    def post(self, name, body, *args, method='post'):
        return getattr(self.client, method)(reverse(name, args=args), body, content_type='application/json')


class MasterDataTests(OrgTestCase):
    def test_existing_projects_circles_and_associations_are_seeded_once(self):
        self.assertEqual(list(Project.objects.values_list('key', 'code')), [('4G Saturation', '4G'), ('LWE', 'LWE')])
        self.assertEqual(Circle.objects.count(), 11)
        self.assertEqual(Circle.objects.filter(code='MP').count(), 1)  # one global MP for both projects
        self.assertEqual(sorted(services.associations()), sorted(SEEDED))
        self.assertEqual(set(Circle.objects.get(code='MP').projects.values_list('project__key', flat=True)), {'4G Saturation', 'LWE'})
        self.assertTrue(OrganizationChange.objects.filter(action='initialised', actor_name='system').exists())

    def test_seeding_creates_no_sites_data_or_access(self):
        self.assertEqual((Site.objects.count(), DailySitePerformance.objects.count(), AccessAssignment.objects.count()), (0, 0, 0))

    def test_project_circle_associations_are_unique(self):
        mp, lwe = Circle.objects.get(code='MP'), Project.objects.get(key='LWE')
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProjectCircle.objects.create(project=lwe, circle=mp)
        response = self.post('org-associations', {'project': 'LWE', 'circle': 'MP'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('already associated', str(response.json()))

    def test_a_new_circle_exists_once_and_appears_for_its_project_only(self):
        response = self.post('org-circles', {'code': 'kl', 'name': 'Kerala', 'reason': 'New circle'})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.post('org-circles', {'code': 'KL', 'name': 'Kerala Two'}).status_code, 400)  # never duplicated
        self.assertEqual(self.post('org-associations', {'project': 'LWE', 'circle': 'KL'}).status_code, 201)
        catalog = self.client.get(reverse('org-catalog')).json()
        self.assertIn({'project': 'LWE', 'circle': 'KL', 'is_active': True}, catalog['associations'])
        options = {p['value']: p for p in self.client.get(reverse('raw-upload-options')).json()['projects']}
        self.assertIn('KL', options['LWE']['circles'])
        self.assertEqual(options['LWE']['site_counts']['KL'], 0)  # no sites invented
        self.assertNotIn('KL', options['4G Saturation']['circles'])
        self.assertEqual((Site.objects.filter(circle='KL').count(), Circle.objects.filter(code='KL').count()), (0, 1))

    def test_deactivation_keeps_history_and_renaming_keeps_the_stored_code(self):
        s = site('4G Saturation', 'RJ', 'UVRJ001')
        make_daily(s, date(2026, 10, 1), 10)
        rj = Circle.objects.get(code='RJ')
        self.assertEqual(self.post('org-circle', {'is_active': False, 'reason': 'Test'}, rj.pk, method='patch').status_code, 200)
        self.assertEqual(self.post('org-circle', {'name': 'Rajasthan Circle'}, rj.pk, method='patch').status_code, 200)
        self.assertEqual(self.post('org-circle', {'code': 'RJX'}, rj.pk, method='patch').status_code, 400)  # the code is fixed
        self.assertEqual((DailySitePerformance.objects.count(), Site.objects.get().circle), (1, 'RJ'))
        self.assertNotIn(('4G Saturation', 'RJ'), services.associations(active_only=True))  # no longer offered
        self.assertIn(('4G Saturation', 'RJ'), services.associations(active_only=False))
        change = OrganizationChange.objects.filter(entity_type='circle', action='deactivated').get()
        self.assertEqual((change.actor_name, change.reason, change.previous['is_active'], change.new['is_active']), ('org-admin', 'Test', True, False))

    def test_projects_are_deactivated_never_deleted_and_their_identifier_is_fixed(self):
        lwe = Project.objects.get(key='LWE')
        self.assertEqual(self.post('org-project', {'key': 'LWE2'}, lwe.pk, method='patch').status_code, 400)
        self.assertEqual(self.post('org-project', {'is_active': False}, lwe.pk, method='patch').status_code, 200)
        self.assertTrue(Project.objects.filter(key='LWE', is_active=False).exists())
        self.assertNotIn('LWE', services.project_keys(active_only=True))
        self.assertEqual(self.post('org-projects', {'key': 'Pilot', 'code': 'PLT', 'name': 'Pilot'}).status_code, 201)
        options = {p['value']: p for p in self.client.get(reverse('raw-upload-options')).json()['projects']}
        self.assertEqual(sorted(options), ['4G Saturation'])  # LWE inactive; Pilot has no raw CSV import on the data layer
        mapping = {m['project']: m for m in self.client.get(reverse('org-aliases')).json()['site_id_mapping']}
        self.assertEqual((mapping['Pilot']['configured'], mapping['4G Saturation']['configured']), (False, True))

    def test_removing_an_association_with_records_keeps_it_inactive_and_leaves_the_other_project(self):
        s = site('4G Saturation', 'MP', 'UVMP001')
        make_daily(s, date(2026, 10, 1), 0)
        mp_4g = ProjectCircle.objects.get(project__key='4G Saturation', circle__code='MP')
        body = self.client.delete(reverse('org-association', args=[mp_4g.pk]), {'reason': 'Test'}, content_type='application/json').json()
        self.assertEqual((body['outcome'], body['dependencies']), ('deactivated', {'sites': 1, 'daily': 1}))
        mp_4g.refresh_from_db()
        self.assertFalse(mp_4g.is_active)
        self.assertTrue(ProjectCircle.objects.get(project__key='LWE', circle__code='MP').is_active)  # LWE untouched
        self.assertEqual((Site.objects.count(), DailySitePerformance.objects.count()), (1, 1))  # nothing cascaded
        self.assertNotIn(('4G Saturation', 'MP'), services.associations(active_only=True))
        again = self.client.delete(reverse('org-association', args=[mp_4g.pk])).json()
        self.assertEqual(again['outcome'], 'kept_inactive')
        self.assertEqual(OrganizationChange.objects.filter(entity_type='association').count(), 1)  # the second call changed nothing

    def test_an_unused_association_is_removed_alone(self):
        ap = ProjectCircle.objects.get(project__key='LWE', circle__code='AP')
        body = self.client.delete(reverse('org-association', args=[ap.pk])).json()
        self.assertEqual(body['outcome'], 'removed')
        self.assertFalse(ProjectCircle.objects.filter(pk=ap.pk).exists())
        self.assertTrue(Circle.objects.filter(code='AP').exists())  # the global circle stays
        self.assertTrue(OrganizationChange.objects.filter(entity_type='association', action='removed').exists())

    def test_an_unused_circle_can_be_deleted_and_a_used_one_cannot(self):
        self.post('org-circles', {'code': 'KL', 'name': 'Kerala'})
        kl = Circle.objects.get(code='KL')
        self.post('org-associations', {'project': 'LWE', 'circle': 'KL'})
        blocked = self.client.delete(reverse('org-circle', args=[kl.pk]))
        self.assertEqual(blocked.status_code, 400)
        self.assertIn('associations 1', str(blocked.json()))
        ProjectCircle.objects.filter(circle=kl).delete()
        self.assertEqual(self.client.delete(reverse('org-circle', args=[kl.pk])).status_code, 200)
        self.assertFalse(Circle.objects.filter(code='KL').exists())
        self.assertTrue(OrganizationChange.objects.filter(entity_type='circle', action='deleted', entity_label='KL').exists())
        mp = Circle.objects.get(code='MP')
        self.assertEqual(self.client.delete(reverse('org-circle', args=[mp.pk])).status_code, 400)

    def test_a_refused_operation_changes_and_records_nothing(self):
        self.post('org-circles', {'code': 'KL', 'name': 'Kerala'})
        kl = Circle.objects.get(code='KL')
        self.post('org-circle', {'is_active': False}, kl.pk, method='patch')
        history = OrganizationChange.objects.count()
        response = self.post('org-associations', {'project': 'LWE', 'circle': 'KL'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('inactive', str(response.json()))
        self.assertFalse(ProjectCircle.objects.filter(circle=kl).exists())
        self.assertEqual(OrganizationChange.objects.count(), history)
        self.client.raise_request_exception = False
        with mock.patch('apps.organization.services.OrganizationChange.objects.create', side_effect=RuntimeError('history unavailable')):
            self.assertEqual(self.post('org-circles', {'code': 'GJ', 'name': 'Gujarat'}).status_code, 500)
        self.assertFalse(Circle.objects.filter(code='GJ').exists())  # rolled back with its history entry

    def test_only_admins_change_the_organization_and_every_portal_user_reads_the_catalog(self):
        for user in (self.noc, self.ci):
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse('org-catalog')).status_code, 200)
            for name in ('org-projects', 'org-circles', 'org-associations', 'org-aliases', 'org-access', 'org-history'):
                self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)
            self.assertEqual(self.post('org-circles', {'code': 'KL', 'name': 'Kerala'}).status_code, 403)
            self.assertEqual(self.post('org-access-user', {'pairs': [{'project': 'LWE', 'circle': 'MP'}]}, self.ci.pk, method='put').status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(reverse('org-catalog')).status_code, 401)
        self.assertFalse(Circle.objects.filter(code='KL').exists())


class DatabaseReadinessTests(OrgTestCase):
    """A new association takes sites, daily, monthly and upload records in the data layer's tables (no new table)."""

    def test_a_new_association_accepts_project_specific_records(self):
        self.post('org-associations', {'project': '4G Saturation', 'circle': 'AP'})
        lwe_ap = site('LWE', 'AP', 'LWEAP01')
        ap_4g = site('4G Saturation', 'AP', 'UVAP001')
        make_daily(ap_4g, date(2026, 10, 13), 30)
        monthly(ap_4g, date(2026, 10, 1), 30)
        with tempfile.TemporaryDirectory() as tmp, override_settings(DATA_DIR=Path(tmp)):
            data = csv_bytes([row('UVAP001', '99', circle='AP', day='14-10-2026')])
            body = self.client.post(reverse('raw-upload-preview'), {'file': SimpleUploadedFile('ap.csv', data), 'project': '4G Saturation',
                                                                     'circle': 'AP', 'reporting_date': '2026-10-14'}).json()
            self.assertEqual(body['summary']['ready_to_import'], 1)
            self.assertEqual(self.client.post(reverse('raw-upload-commit', args=[body['id']]), {'confirm': True},
                                              content_type='application/json').status_code, 200)
        self.assertEqual(sorted(DailySitePerformance.objects.values_list('technology', 'report_date')),
                         [('4G Saturation', date(2026, 10, 13)), ('4G Saturation', date(2026, 10, 14))])
        self.assertFalse(DailySitePerformance.objects.filter(site=lwe_ap).exists())  # the LWE AP site is untouched
        self.assertTrue(UploadBatch.objects.filter(technology='4G Saturation', circle='AP', processing_status='committed').exists())
        usage = services.usage_by_pair()[('4G Saturation', 'AP')]
        current_monthly = MonthlySitePerformance.objects.filter(is_current=True, technology='4G Saturation', site__circle='AP').count()
        self.assertGreaterEqual(current_monthly, 1)  # the commit recalculates the month's results
        self.assertEqual((usage['sites'], usage['on_air_sites'], usage['daily'], usage['monthly'], usage['uploads']), (1, 1, 2, current_monthly, 1))
        self.assertEqual(services.usage_by_pair()[('LWE', 'AP')]['daily'], 0)

    def test_filters_list_configured_circles_without_inventing_data(self):
        options = {'circles': [{'value': 'MP', 'label': 'MP', 'report_types': ['4G Saturation'], 'site_count': 1}],
                   'report_types': [{'value': '4G Saturation', 'label': '4G Saturation', 'site_count': 1}]}  # as built from the data
        merged = services.merge_filter_options(options)
        circles = {c['value']: c for c in merged['circles']}
        self.assertEqual((circles['MP']['has_data'], circles['MP']['report_types'], circles['MP']['site_count']), (True, ['4G Saturation', 'LWE'], 1))
        self.assertEqual((circles['BH']['has_data'], circles['BH']['site_count'], circles['BH']['report_types']), (False, 0, ['LWE']))
        lwe = next(t for t in merged['report_types'] if t['value'] == 'LWE')
        self.assertEqual((lwe['has_data'], lwe['site_count']), (False, 0))
        ProjectCircle.objects.filter(project__key='4G Saturation', circle__code='MP').update(is_active=False)
        again = {c['value']: c for c in services.merge_filter_options(options)['circles']}
        self.assertEqual((again['MP']['report_types'], again['MP']['configured_for']), (['4G Saturation', 'LWE'], ['LWE']))  # history kept


class ProjectSeparationTests(OrgTestCase):
    """A shared circle shares nothing else: sites, daily, monthly and uploads stay per project (technology)."""

    def setUp(self):
        super().setUp()
        self.mp_4g = [site('4G Saturation', 'MP', f'UVMP00{i}') for i in range(1, 5)]
        self.mp_lwe = [site('LWE', 'MP', 'LWEMP01'), site('LWE', 'MP', 'LWEMP02', on_air_date=None)]

    def test_site_counts_and_identities_stay_per_project(self):
        usage = services.usage_by_pair()
        self.assertEqual((usage[('4G Saturation', 'MP')]['sites'], usage[('LWE', 'MP')]['sites']), (4, 2))
        self.assertEqual((usage[('4G Saturation', 'MP')]['on_air_sites'], usage[('LWE', 'MP')]['on_air_sites']), (4, 1))
        with self.assertRaises(IntegrityError), transaction.atomic():
            site('LWE', 'MP', 'UVMP001')  # one site per BSNL Site ID, whatever the technology

    def test_usage_ignores_outside_scope_sites_and_future_on_air_dates(self):
        make_site('STLMP01', circle='MP', outside_scope=True)
        site('4G Saturation', 'MP', 'UVMP009', on_air_date=date(2999, 1, 1))
        usage = services.usage_by_pair()[('4G Saturation', 'MP')]
        self.assertEqual((usage['sites'], usage['on_air_sites']), (5, 4))
        self.assertNotIn(('', 'MP'), services.usage_by_pair())

    def test_escalation_counts_sites_with_matrix_contacts(self):
        site('LWE', 'MP', 'LWEMP03', ci_name='Ravi', ie_name='Amit')
        site('LWE', 'MP', 'LWEMP04', om_manager_name='Manager')
        usage = services.usage_by_pair()
        self.assertEqual((usage[('LWE', 'MP')]['escalation'], usage[('4G Saturation', 'MP')]['escalation']), (2, 0))

    def test_daily_and_monthly_values_are_stored_per_project_site(self):
        day, month = date(2026, 10, 13), date(2026, 10, 1)
        make_daily(self.mp_4g[0], day, 0)
        make_daily(self.mp_lwe[0], day, 720)
        monthly(self.mp_4g[0], month, 5)
        monthly(self.mp_lwe[0], month, 900)
        old = monthly(self.mp_lwe[1], month, 1)
        old.is_current = False
        old.save()
        by_project = dict(DailySitePerformance.objects.filter(report_date=day).values_list('technology', 'outage_minutes'))
        self.assertEqual(by_project, {'4G Saturation': 0, 'LWE': 720})
        current = MonthlySitePerformance.objects.filter(is_current=True)
        self.assertEqual(dict(current.values_list('technology', 'total_outage_minutes')), {'4G Saturation': 5, 'LWE': 900})
        usage = services.usage_by_pair()
        self.assertEqual((usage[('4G Saturation', 'MP')]['daily'], usage[('LWE', 'MP')]['daily']), (1, 1))
        self.assertEqual((usage[('4G Saturation', 'MP')]['monthly'], usage[('LWE', 'MP')]['monthly']), (1, 1))  # current results only
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_daily(self.mp_lwe[0], day, 1)

    def test_site_id_mapping_describes_the_data_layer_rules(self):
        mapping = {m['project']: m for m in self.client.get(reverse('org-aliases')).json()['site_id_mapping']}
        self.assertTrue(mapping['4G Saturation']['configured'])
        self.assertIn('BSNL Site ID', mapping['4G Saturation']['rule'])
        self.assertFalse(mapping['LWE']['configured'])  # no LWE Band ID mapping loaded
        SiteIdentifier.objects.create(site=self.mp_lwe[0], kind=SiteIdentifier.Kind.BAND_2100, value='MPB2100', key='MPB2100',
                                      batch=self.mp_lwe[0].matrix_batch)
        mapping = {m['project']: m for m in self.client.get(reverse('org-aliases')).json()['site_id_mapping']}
        self.assertTrue(mapping['LWE']['configured'])
        self.assertIn('LWE Band ID mapping', mapping['LWE']['rule'])


@override_settings()
class IndependentUploadTests(OrgTestCase):
    """MP 4G and MP LWE files for the same date, imported by the data layer (sitedata.rawcsv): each upload takes only its
    technology's sites (LWE rows here name the LWE site's own BSNL Site ID as BTS IP ID)."""

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        override = override_settings(DATA_DIR=Path(self._tmp.name) / 'data')
        override.enable()
        self.addCleanup(override.disable)
        for project, ids in (('4G Saturation', ('UVMP001', 'UVMP002')), ('LWE', ('LWEMP01', 'LWEMP02'))):
            for i in ids:
                site(project, 'MP', i)

    def upload(self, project, rows, name='mp.csv'):
        data = csv_bytes([row(*r, circle='MP') for r in rows])
        body = self.client.post(reverse('raw-upload-preview'), {'file': SimpleUploadedFile(name, data), 'project': project, 'circle': 'MP',
                                                                'reporting_date': '2026-10-13'})
        self.assertEqual(body.status_code, 201, body.content)
        return body.json()

    def commit(self, batch_id):
        return self.client.post(reverse('raw-upload-commit', args=[batch_id]), {'confirm': True}, content_type='application/json')

    def test_both_projects_import_the_same_circle_and_date_independently(self):
        rows = [('UVMP001', '99'), ('UVMP002', '100'), ('LWEMP01', '50'), ('LWEMP02', '75')]  # one CNMC dump with both technologies
        four_g = self.upload('4G Saturation', rows)
        self.assertEqual(four_g['summary']['ready_to_import'], 2)
        self.assertEqual(self.commit(four_g['id']).status_code, 200)
        lwe = self.upload('LWE', rows)
        self.assertIsNone(lwe['already_imported'])  # the same file is not a duplicate of the 4G upload
        self.assertEqual(lwe['summary']['ready_to_import'], 2)
        self.assertEqual(self.commit(lwe['id']).status_code, 200)
        stored = {(t, i): round(o, 2) for t, i, o in DailySitePerformance.objects.values_list('technology', 'site__bsnl_site_id', 'outage_minutes')}
        self.assertEqual(stored, {('4G Saturation', 'UVMP001'): 14.4, ('4G Saturation', 'UVMP002'): 0.0, ('LWE', 'LWEMP01'): 720.0,
                                  ('LWE', 'LWEMP02'): 360.0})
        batches = UploadBatch.objects.filter(kind__in=('raw_csv_4g', 'raw_csv_lwe'), processing_status='committed')
        self.assertEqual(sorted(batches.values_list('technology', 'circle', 'reporting_date')),
                         [('4G Saturation', 'MP', date(2026, 10, 13)), ('LWE', 'MP', date(2026, 10, 13))])
        usage = services.usage_by_pair()
        self.assertEqual((usage[('4G Saturation', 'MP')]['uploads'], usage[('LWE', 'MP')]['uploads']), (1, 1))  # one upload record per committed preview

    def test_rows_resolve_only_to_the_selected_project(self):
        body = self.upload('LWE', [('UVMP001', '99'), ('LWEMP01', '99'), ('NEW999', '99')])
        codes = {r['raw_id']: r['code'] for r in body['rows']['rows']}
        self.assertEqual(codes, {'UVMP001': 'other_technology', 'LWEMP01': 'ready', 'NEW999': 'outside_programme'})
        body = self.upload('4G Saturation', [('LWEMP01', '99')])
        self.assertEqual(body['rows']['rows'][0]['code'], 'other_technology')
        self.assertEqual(Site.objects.count(), 4)  # never created

    def test_the_same_file_counts_as_already_imported_only_for_its_own_project(self):
        rows = [('UVMP001', '100'), ('LWEMP01', '100')]
        first = self.upload('4G Saturation', rows)
        self.commit(first['id'])
        again = self.upload('4G Saturation', rows)
        self.assertEqual(again['already_imported']['batch'], first['id'])
        self.assertEqual(again['summary']['ready_to_import'], 0)  # identical: skipped, idempotent
        other = self.upload('LWE', rows)
        self.assertIsNone(other['already_imported'])
        self.assertEqual(other['summary']['ready_to_import'], 1)

    def test_a_conflict_in_one_project_leaves_the_other_untouched(self):
        self.commit(self.upload('4G Saturation', [('UVMP001', '100')])['id'])
        self.commit(self.upload('LWE', [('LWEMP01', '50')])['id'])
        conflict = self.upload('4G Saturation', [('UVMP001', '90')])
        self.assertEqual(conflict['rows']['rows'][0]['code'], 'conflict_existing')
        self.assertEqual(DailySitePerformance.objects.get(technology='LWE').outage_minutes, 720)

    def test_a_circle_not_associated_with_the_project_is_refused(self):
        response = self.client.post(reverse('raw-upload-preview'), {'file': SimpleUploadedFile('rj.csv', csv_bytes([row('X', '99', circle='RJ')])),
                                                                     'project': 'LWE', 'circle': 'RJ', 'reporting_date': '2026-10-13'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('not an active circle of LWE', str(response.json()))


class AccessTests(OrgTestCase):
    def test_admin_and_noc_lead_are_not_limited(self):
        self.assertIsNone(allowed_pairs(self.admin))
        self.assertIsNone(allowed_pairs(self.noc))
        self.assertEqual(allowed_pairs(self.ci), set())

    def test_mp_under_4g_does_not_give_mp_under_lwe(self):
        set_pairs(self.ci, [('4G Saturation', 'MP')], actor=self.admin, reason='Assigned to 4G MP')
        self.assertTrue(may_use(self.ci, '4G Saturation', 'MP'))
        self.assertFalse(may_use(self.ci, 'LWE', 'MP'))
        self.client.force_login(self.ci)
        options = {p['value']: p['circles'] for p in self.client.get(reverse('raw-upload-options')).json()['projects']}
        self.assertEqual(options, {'4G Saturation': ['MP'], 'LWE': []})
        response = self.client.post(reverse('raw-upload-preview'), {'file': SimpleUploadedFile('a.csv', b'x'), 'project': 'LWE', 'circle': 'MP',
                                                                     'reporting_date': '2026-10-13'})
        self.assertEqual(response.status_code, 403)
        change = OrganizationChange.objects.get(entity_type='user_access')
        self.assertEqual((change.actor_name, change.new['pairs'], change.reason), ('org-admin', [['4G Saturation', 'MP']], 'Assigned to 4G MP'))

    def test_a_new_association_does_not_grant_access(self):
        set_circles(self.ci, ['RJ'])  # RJ belongs to 4G Saturation only today
        self.post('org-associations', {'project': 'LWE', 'circle': 'RJ'})
        self.assertEqual(allowed_pairs(self.ci), {('4G Saturation', 'RJ')})

    def test_grants_must_be_associations(self):
        response = self.post('org-access-user', {'pairs': [{'project': '4G Saturation', 'circle': 'BH'}]}, self.ci.pk, method='put')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(AccessAssignment.objects.count(), 0)

    def test_legacy_circle_assignments_grant_nothing_until_reviewed(self):
        AccountProfile.objects.update_or_create(user=self.ci, defaults={'circles': ['MP']})
        forget_profile(self.ci)
        # A circle without a project cannot be mapped safely: it stays restricted (no access) and is listed for review.
        self.assertEqual(allowed_pairs(self.ci), set())
        self.assertFalse(may_use(self.ci, 'LWE', 'MP'))
        access = {u['username']: u for u in self.client.get(reverse('org-access')).json()['users']}
        self.assertEqual((access['org-ci']['legacy_circles'], access['org-ci']['needs_review']), (['MP'], True))
        # Reviewing it replaces the legacy assignment with explicit project grants.
        self.post('org-access-user', {'pairs': [{'project': 'LWE', 'circle': 'MP'}], 'reason': 'Reviewed'}, self.ci.pk, method='put')
        forget_profile(self.ci)  # the change was made through the API, on another copy of the user
        self.assertEqual(allowed_pairs(self.ci), {('LWE', 'MP')})
        self.assertEqual(AccountProfile.objects.get(user=self.ci).circles, [])

    def test_exports_filter_by_project_and_circle_together(self):
        sites = pd.DataFrame({'report_type': ['4G Saturation', 'LWE', 'LWE'], 'circle': ['MP', 'MP', 'OD']})
        ds = SimpleNamespace(sites=sites)
        mine = {('4G Saturation', 'MP')}
        self.assertEqual(list(report_export.resolve_scope(ds, None, 'MP', mine).rows), [0])  # MP LWE is not included
        with self.assertRaisesMessage(report_export.ExportError, 'not assigned to circle MP under LWE'):
            report_export.resolve_scope(ds, 'LWE', 'MP', mine)
        self.assertEqual(list(report_export.resolve_scope(ds, None, None, None).rows), [0, 1, 2])


class CodeMappingTests(OrgTestCase):
    def test_aliases_resolve_within_their_source_and_project(self):
        raw = services.AliasResolver('raw_daily_csv')
        self.assertEqual((raw.resolve('OR'), raw.resolve(' od '), raw.resolve('UE'), raw.resolve('Odisha')), ('OD', 'OD', None, None))
        self.assertEqual(services.AliasResolver('master_workbook').resolve('Madhya Pradesh'), 'MP')
        self.assertIsNone(services.AliasResolver('master_workbook').resolve('OR'))  # another source's code is not shared
        response = self.post('org-aliases', {'source': 'raw_daily_csv', 'project': 'LWE', 'raw_code': 'MPX', 'circle': 'MP', 'reason': 'Verified'})
        self.assertEqual(response.status_code, 201)
        raw = services.AliasResolver('raw_daily_csv')
        self.assertEqual((raw.resolve('MPX', 'LWE'), raw.resolve('MPX', '4G Saturation'), raw.resolve('MPX')), ('MP', None, None))

    def test_an_alias_cannot_take_another_circle_s_code_and_unknown_codes_create_nothing(self):
        response = self.post('org-aliases', {'source': 'raw_daily_csv', 'project': None, 'raw_code': 'RJ', 'circle': 'MP'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.post('org-circles', {'code': 'OR', 'name': 'Orissa'}).status_code, 400)  # OR is OD's alias
        circles = Circle.objects.count()
        self.assertIsNone(services.AliasResolver('raw_daily_csv').resolve('ZZ'))
        self.assertEqual(Circle.objects.count(), circles)

    def test_deactivating_an_alias_stops_its_use_and_is_recorded(self):
        alias = CircleAlias.objects.get(source='raw_daily_csv', raw_key='or')
        self.post('org-alias', {'is_active': False, 'reason': 'Check'}, alias.pk, method='patch')
        self.assertIsNone(services.AliasResolver('raw_daily_csv').resolve('OR'))
        self.assertTrue(OrganizationChange.objects.filter(entity_type='circle_alias', action='deactivated').exists())

    def test_shadowed_global_aliases_are_flagged(self):
        self.post('org-aliases', {'source': 'raw_daily_csv', 'project': 'LWE', 'raw_code': 'OR', 'circle': 'MP'})
        rows = {(a['project'], a['raw_code']): a for a in self.client.get(reverse('org-aliases')).json()['aliases'] if a['source'] == 'raw_daily_csv'}
        self.assertIn('For LWE the project alias maps "OR" to MP instead.', rows[(None, 'OR')]['problems'])


class ImportAndRcaTests(OrgTestCase):
    def test_pairs_outside_the_organization_are_reported_and_block(self):
        check = services.check_pairs([('4G Saturation', 'MP'), ('4G Saturation', 'BH'), ('LWE', 'KL'), ('Pilot', 'MP')])
        self.assertEqual((check['proposed_associations'], check['unknown_circles'], check['unknown_projects']),
                         ([{'project': '4G Saturation', 'circle': 'BH'}], [{'project': 'LWE', 'circle': 'KL'}], ['Pilot']))
        self.assertTrue(check['blocking'])
        self.assertIn('Set up the Organization first', services.blocking_message(check))
        self.assertFalse(services.check_pairs([('LWE', 'MP')])['blocking'])
        self.assertEqual(Site.objects.count(), 0)  # nothing created

    def test_rca_records_and_expected_units_use_active_associations(self):
        response = self.post('rca-records', {'reporting_date': '2026-10-13', 'project': '4G Saturation', 'circle': 'BH', 'site_id': 'UVBH001',
                                             'final_bucket': 'BSNL OFC', 'bucket_2': 'x', 'rca_text': 'y'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('not an active circle of 4G Saturation', str(response.json()))
        self.assertEqual(RcaRecord.objects.count(), 0)
        from apps.rca.cycles import expected_units
        self.assertIn(('LWE', 'BH'), expected_units())
        self.assertNotIn(('4G Saturation', 'BH'), expected_units())  # not associated: never expected
