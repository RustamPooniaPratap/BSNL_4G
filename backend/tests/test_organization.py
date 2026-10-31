"""Organization (Administration > Organization): projects, global circles, associations, circle code mapping, project/circle
user access, change history, and how uploads, imports, exports and RCA use them. Isolated test data only (SQLite)."""
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
from apps.uptimedb.models import DataImportBatch, SiteDailyPerformance, SiteMonthlyPerformance, UptimeSite
from apps.uptimedb.raw.resolvers import RESOLVERS, FourGResolver
from tests.auth_helpers import portal_user
from tests.test_raw_upload import csv_bytes, row

SEEDED = [('4G Saturation', c) for c in ('MP', 'OD', 'RJ')] + [('LWE', c) for c in ('AP', 'BH', 'CG', 'JH', 'MH', 'MP', 'OD', 'TL', 'UP', 'WB')]


def site(project, circle, site_id, batch, **extra):
    return UptimeSite.objects.create(project=project, circle=circle, site_id=site_id, site_key=site_id.upper(), batch=batch, source_row=1,
                                     on_air=True, **extra)


class OrgTestCase(TestCase):
    def setUp(self):
        self.master = DataImportBatch.objects.create(original_filename='master.xlsx', checksum_sha256='m', sheet_name='Up-Time Report',
                                                     stored_path='-', status=DataImportBatch.Status.COMMITTED)
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
        self.assertEqual((UptimeSite.objects.count(), SiteDailyPerformance.objects.count(), AccessAssignment.objects.count()), (0, 0, 0))

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
        self.assertEqual((UptimeSite.objects.filter(circle='KL').count(), Circle.objects.filter(code='KL').count()), (0, 1))

    def test_deactivation_keeps_history_and_renaming_keeps_the_stored_code(self):
        s = site('4G Saturation', 'RJ', 'UVRJ001', self.master)
        SiteDailyPerformance.objects.create(site=s, date=date(2026, 10, 1), outage_minutes=10, batch=self.master)
        rj = Circle.objects.get(code='RJ')
        self.assertEqual(self.post('org-circle', {'is_active': False, 'reason': 'Test'}, rj.pk, method='patch').status_code, 200)
        self.assertEqual(self.post('org-circle', {'name': 'Rajasthan Circle'}, rj.pk, method='patch').status_code, 200)
        self.assertEqual(self.post('org-circle', {'code': 'RJX'}, rj.pk, method='patch').status_code, 400)  # the code is fixed
        self.assertEqual((SiteDailyPerformance.objects.count(), UptimeSite.objects.get().circle), (1, 'RJ'))
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
        self.assertEqual((sorted(options), options['Pilot']['configured']), (['4G Saturation', 'Pilot'], False))  # no upload rule: not configured

    def test_removing_an_association_with_records_keeps_it_inactive_and_leaves_the_other_project(self):
        s = site('4G Saturation', 'MP', 'UVMP001', self.master)
        SiteDailyPerformance.objects.create(site=s, date=date(2026, 10, 1), outage_minutes=0, batch=self.master)
        mp_4g = ProjectCircle.objects.get(project__key='4G Saturation', circle__code='MP')
        body = self.client.delete(reverse('org-association', args=[mp_4g.pk]), {'reason': 'Test'}, content_type='application/json').json()
        self.assertEqual((body['outcome'], body['dependencies']), ('deactivated', {'sites': 1, 'daily': 1}))
        mp_4g.refresh_from_db()
        self.assertFalse(mp_4g.is_active)
        self.assertTrue(ProjectCircle.objects.get(project__key='LWE', circle__code='MP').is_active)  # LWE untouched
        self.assertEqual((UptimeSite.objects.count(), SiteDailyPerformance.objects.count()), (1, 1))  # nothing cascaded
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
    """A new association takes sites, daily, monthly and upload records in the existing tables (no new table or migration)."""

    def test_a_new_association_accepts_project_specific_records(self):
        self.post('org-associations', {'project': '4G Saturation', 'circle': 'AP'})
        lwe_ap = site('LWE', 'AP', 'LWEAP01', self.master)
        ap_4g = site('4G Saturation', 'AP', 'UVAP001', self.master)
        SiteDailyPerformance.objects.create(site=ap_4g, date=date(2026, 10, 13), outage_minutes=30, batch=self.master)
        SiteMonthlyPerformance.objects.create(site=ap_4g, month=date(2026, 10, 1), outage_minutes=30, batch=self.master)
        with tempfile.TemporaryDirectory() as tmp, override_settings(DATA_DIR=Path(tmp)):
            data = csv_bytes([row('UVAP001', '99', circle='AP', day='14-10-2026')])
            body = self.client.post(reverse('raw-upload-preview'), {'file': SimpleUploadedFile('ap.csv', data), 'project': '4G Saturation',
                                                                     'circle': 'AP', 'reporting_date': '2026-10-14'}).json()
            self.assertEqual(body['summary']['ready_to_import'], 1)
            self.assertEqual(self.client.post(reverse('raw-upload-commit', args=[body['id']]), {'confirm': True},
                                              content_type='application/json').status_code, 200)
        self.assertEqual(sorted(SiteDailyPerformance.objects.values_list('site__project', 'date')),
                         [('4G Saturation', date(2026, 10, 13)), ('4G Saturation', date(2026, 10, 14))])
        self.assertFalse(SiteDailyPerformance.objects.filter(site=lwe_ap).exists())  # the LWE AP site is untouched
        self.assertTrue(DataImportBatch.objects.filter(project='4G Saturation', circle='AP', status='committed').exists())

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
    """A shared circle shares nothing else: sites, daily, monthly and uploads stay per project."""

    def setUp(self):
        super().setUp()
        self.mp_4g = [site('4G Saturation', 'MP', f'UVMP00{i}', self.master) for i in range(1, 4)]
        self.mp_lwe = [site('LWE', 'MP', 'LWEMP01', self.master)]
        self.shared_id_4g = site('4G Saturation', 'MP', 'SAME01', self.master)
        self.shared_id_lwe = site('LWE', 'MP', 'SAME01', self.master)  # the same text, another project: no collision

    def test_site_counts_and_identities_stay_per_project(self):
        usage = services.usage_by_pair()
        self.assertEqual((usage[('4G Saturation', 'MP')]['sites'], usage[('LWE', 'MP')]['sites']), (4, 2))
        self.assertNotEqual(self.shared_id_4g.pk, self.shared_id_lwe.pk)
        with self.assertRaises(IntegrityError), transaction.atomic():
            site('LWE', 'MP', 'SAME01', self.master)  # unique per project, circle and site ID

    def test_daily_and_monthly_values_are_stored_per_project_site(self):
        day, month = date(2026, 10, 13), date(2026, 10, 1)
        SiteDailyPerformance.objects.create(site=self.shared_id_4g, date=day, outage_minutes=0, batch=self.master)
        SiteDailyPerformance.objects.create(site=self.shared_id_lwe, date=day, outage_minutes=720, batch=self.master)
        SiteMonthlyPerformance.objects.create(site=self.shared_id_4g, month=month, outage_minutes=5, batch=self.master)
        SiteMonthlyPerformance.objects.create(site=self.shared_id_lwe, month=month, outage_minutes=900, batch=self.master)
        by_project = dict(SiteDailyPerformance.objects.filter(date=day).values_list('site__project', 'outage_minutes'))
        self.assertEqual(by_project, {'4G Saturation': 0, 'LWE': 720})
        self.assertEqual(dict(SiteMonthlyPerformance.objects.values_list('site__project', 'outage_minutes')), {'4G Saturation': 5, 'LWE': 900})
        with self.assertRaises(IntegrityError), transaction.atomic():
            SiteDailyPerformance.objects.create(site=self.shared_id_lwe, date=day, outage_minutes=1, batch=self.master)

    def test_raw_ids_resolve_only_to_the_selected_project(self):
        lwe = FourGResolver('LWE', 'MP')
        self.assertEqual(lwe.resolve('UVMP001').code, 'other_project')  # a 4G site never resolves for LWE
        self.assertEqual(FourGResolver('4G Saturation', 'MP').resolve('LWEMP01').code, 'other_project')
        self.assertEqual(lwe.resolve('SAME01').site, self.shared_id_lwe)
        self.assertEqual(FourGResolver('4G Saturation', 'MP').resolve('SAME01').site, self.shared_id_4g)
        self.assertEqual(lwe.resolve('NEW999').code, 'unknown_site')
        self.assertEqual(UptimeSite.objects.count(), 6)  # never created


@override_settings()
class IndependentUploadTests(OrgTestCase):
    """MP 4G and MP LWE files for the same date. LWE uses the 4G resolver here only to exercise the shared pipeline:
    the real LWE identifier mapping is not configured (resolvers.LweResolver)."""

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        override = override_settings(DATA_DIR=Path(self._tmp.name) / 'data')
        override.enable()
        self.addCleanup(override.disable)
        for project, ids in (('4G Saturation', ('UVMP001', 'SAME01')), ('LWE', ('LWEMP01', 'SAME01'))):
            for i in ids:
                site(project, 'MP', i, self.master)
        patch = mock.patch.dict(RESOLVERS, {'LWE': FourGResolver})
        patch.start()
        self.addCleanup(patch.stop)

    def upload(self, project, rows, name='mp.csv'):
        data = csv_bytes([row(*r, circle='MP') for r in rows])
        body = self.client.post(reverse('raw-upload-preview'), {'file': SimpleUploadedFile(name, data), 'project': project, 'circle': 'MP',
                                                                'reporting_date': '2026-10-13'})
        self.assertEqual(body.status_code, 201, body.content)
        return body.json()

    def commit(self, batch_id):
        return self.client.post(reverse('raw-upload-commit', args=[batch_id]), {'confirm': True}, content_type='application/json')

    def test_both_projects_import_the_same_circle_and_date_independently(self):
        four_g = self.upload('4G Saturation', [('UVMP001', '99'), ('SAME01', '100')])
        self.assertEqual(self.commit(four_g['id']).status_code, 200)
        lwe = self.upload('LWE', [('LWEMP01', '50'), ('SAME01', '75')])
        self.assertIsNone(lwe['already_imported'])
        self.assertEqual(lwe['summary']['ready_to_import'], 2)  # not a duplicate of the 4G upload
        self.assertEqual(self.commit(lwe['id']).status_code, 200)
        stored = {(p, i): round(o, 2) for p, i, o in SiteDailyPerformance.objects.values_list('site__project', 'site__site_id', 'outage_minutes')}
        self.assertEqual(stored, {('4G Saturation', 'UVMP001'): 14.4, ('4G Saturation', 'SAME01'): 0.0, ('LWE', 'LWEMP01'): 720.0, ('LWE', 'SAME01'): 360.0})
        batches = DataImportBatch.objects.filter(kind='raw_daily_csv', status='committed')
        self.assertEqual(sorted(batches.values_list('project', 'circle', 'reporting_date')),
                         [('4G Saturation', 'MP', date(2026, 10, 13)), ('LWE', 'MP', date(2026, 10, 13))])

    def test_the_same_file_counts_as_already_imported_only_for_its_own_project(self):
        rows = [('SAME01', '100')]
        first = self.upload('4G Saturation', rows)
        self.commit(first['id'])
        again = self.upload('4G Saturation', rows)
        self.assertEqual(again['already_imported']['batch'], first['id'])
        self.assertEqual(again['summary']['ready_to_import'], 0)  # identical: skipped, idempotent
        other = self.upload('LWE', rows)
        self.assertIsNone(other['already_imported'])
        self.assertEqual(other['summary']['ready_to_import'], 1)

    def test_a_conflict_in_one_project_leaves_the_other_untouched(self):
        self.commit(self.upload('4G Saturation', [('SAME01', '100')])['id'])
        self.commit(self.upload('LWE', [('SAME01', '50')])['id'])
        conflict = self.upload('4G Saturation', [('SAME01', '90')])
        self.assertEqual(conflict['rows']['rows'][0]['code'], 'conflict_existing')
        self.assertEqual(SiteDailyPerformance.objects.get(site__project='LWE').outage_minutes, 720)

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
    def test_master_workbook_pairs_outside_the_organization_block_a_full_import(self):
        from apps.uptimedb import importer
        from tests.workbook_factory import write_workbook
        with tempfile.TemporaryDirectory() as tmp, override_settings(DATA_DIR=Path(tmp)):
            path = write_workbook(Path(tmp) / 'm.xlsx', sites=[('4G Satu.', 'MP', 'UVMP001', 'A', 'Yes', 'Yes', [0, 0, 0]),
                                                              ('4G Satu.', 'BH', 'UVBH001', 'B', 'Yes', 'Yes', [0, 0, 0]),
                                                              ('LWE', 'KL', 'LWEKL01', 'C', 'Yes', 'Yes', [0, 0, 0])])
            batch = importer.preview(path, 'm.xlsx')
            check = batch.report['organization']
            self.assertEqual((check['proposed_associations'], check['unknown_circles']),
                             ([{'project': '4G Saturation', 'circle': 'BH'}], [{'project': 'LWE', 'circle': 'KL'}]))
            with self.assertRaisesMessage(importer.ImportRejected, 'Set up the Organization first'):
                importer.commit(batch)
            self.assertEqual(UptimeSite.objects.count(), 0)  # no master site created for an unknown circle

    def test_rca_records_and_expected_units_use_active_associations(self):
        response = self.post('rca-records', {'reporting_date': '2026-10-13', 'project': '4G Saturation', 'circle': 'BH', 'site_id': 'UVBH001',
                                             'final_bucket': 'BSNL OFC', 'bucket_2': 'x', 'rca_text': 'y'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('not an active circle of 4G Saturation', str(response.json()))
        self.assertEqual(RcaRecord.objects.count(), 0)
        from apps.rca.cycles import CycleError, validate_units
        self.assertEqual(validate_units([['LWE', 'bh']]), [('LWE', 'BH')])
        with self.assertRaises(CycleError):
            validate_units([['4G Saturation', 'BH']])
