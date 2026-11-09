"""Up-Time Report sites missing from the Consolidation Matrix: kept pending, reported, resolved by an Admin (matrix
update or approved alternate identifier), then processed safely (apps.sitedata.unmatched). Test database only.

Factory workbook sites (1-3 Oct): UVMP001, UVMP002, UVMP003, UVRJ001, LWEMP01, LWEOD01, LWEBH01; the test matrix has all
but UVMP003 (4G) and LWEBH01 (LWE), which are therefore unmatched.
"""
from datetime import date, datetime

from django.urls import reverse

from apps.sitedata import daily, portfolio, unmatched
from apps.sitedata.models import DailyPerformanceEvent, DailySitePerformance, IdentifierConflict, Site, SiteIdentifier, UploadBatch
from tests.auth_helpers import SignedInTestCase, portal_user
from tests.test_sitedata import MATRIX, SiteDataTestCase

EXTRA = ['4G Saturation', 'Madhya Pradesh', 'UVMP009', 'India', 'B', 'O', 'D', datetime(2025, 1, 1), 'Yes', datetime(2025, 1, 1), 'IE One', 'CI East', '', '']
UVMP003 = ['4G Saturation', 'Madhya Pradesh', 'UVMP003', 'Charlie', 'B', 'O', 'D', datetime(2025, 1, 1), 'Yes', datetime(2025, 1, 1), 'IE One', 'CI West', '', '']


class UnmatchedCase(SignedInTestCase, SiteDataTestCase):
    def setUp(self):
        super().setUp()
        portfolio.clear_cache()
        self.addCleanup(portfolio.clear_cache)
        self.load_matrix([*MATRIX, EXTRA])  # UVMP009: a master site the Up-Time Report does not list
        self.upload = self.load_uptime()

    def site_days(self, key):
        return DailySitePerformance.objects.filter(site__site_key=key).count()

    def status(self, site_id):
        return next(s for s in unmatched.report()['sites'] if s['site_id'] == site_id)


class PendingTests(UnmatchedCase):
    def test_matched_sites_import_and_unmatched_ones_stay_pending_and_visible(self):
        self.assertEqual(self.site_days('UVMP001'), 3)  # in both the matrix and the Up-Time Report
        self.assertFalse(Site.objects.filter(site_key__in=['UVMP003', 'LWEBH01']).exists())  # never created from a report
        self.assertFalse(DailySitePerformance.objects.filter(source_identifier__in=['UVMP003', 'LWEBH01']).exists())  # not in any KPI
        mp = self.status('UVMP003')
        self.assertEqual({k: mp[k] for k in ('project', 'circle', 'first_date', 'last_date', 'pending_site_days', 'reason', 'status', 'uploads')},
                         {'project': '4G Saturation', 'circle': 'MP', 'first_date': '2026-10-01', 'last_date': '2026-10-03', 'pending_site_days': 3,
                          'reason': 'Not in the Consolidation Matrix site master', 'status': 'pending', 'uploads': [self.upload.pk]})
        self.assertEqual(self.status('LWEBH01')['project'], 'LWE')
        self.assertEqual(unmatched.report()['pending_sites'], 2)

    def test_after_the_matrix_lists_the_site_its_pending_records_are_processed_once(self):
        self.load_matrix([*MATRIX, EXTRA, UVMP003], name='matrix2.xlsx')
        self.assertEqual(self.status('UVMP003')['status'], 'ready')
        self.assertEqual(self.site_days('UVMP003'), 0)  # nothing is processed without an Admin
        result = unmatched.process_pending(user=self.admin)
        self.assertEqual(result['counts']['accepted'], 3)
        record = DailySitePerformance.objects.filter(site__site_key='UVMP003').order_by('report_date').first()
        self.assertEqual((record.batch_id, record.source_identifier, record.report_date, record.outage_minutes),
                         (self.upload.pk, 'UVMP003', date(2026, 10, 1), 1440.0))  # original upload, ID and date kept
        self.assertEqual(self.status('UVMP003')['status'], 'processed')
        self.assertEqual(self.status('LWEBH01')['status'], 'pending')  # still unresolved
        again = unmatched.process_pending(user=self.admin)
        self.assertEqual((again['uploads'], self.site_days('UVMP003')), ([], 3))  # processed once

    def test_a_duplicate_upload_adds_nothing_and_finds_the_resolved_site(self):
        self.load_matrix([*MATRIX, EXTRA, UVMP003], name='matrix2.xlsx')
        unmatched.process_pending(user=self.admin)
        stored = DailySitePerformance.objects.count()
        again = self.load_uptime(name='again.xlsx')
        self.assertEqual((again.records_accepted, DailySitePerformance.objects.count()), (0, stored))
        self.assertNotIn('UVMP003', again.report['sites_not_in_site_master'])


class AlternateIdentifierTests(UnmatchedCase):
    def test_an_approved_alternate_identifier_resolves_the_site(self):
        unmatched.map_alternate('UVMP003', Site.objects.get(site_key='UVMP009'), user=self.admin, reason='Same tower, renumbered (circle letter 5 Nov)')
        self.assertEqual(self.status('UVMP003')['resolved_to'], 'UVMP009')
        self.assertEqual(self.status('UVMP003')['resolved_by'], 'alternate_identifier')
        unmatched.process_pending(user=self.admin)
        self.assertEqual(self.site_days('UVMP009'), 3)
        self.assertEqual(set(DailySitePerformance.objects.filter(site__site_key='UVMP009').values_list('source_identifier', flat=True)), {'UVMP003'})
        batch = SiteIdentifier.objects.get(kind='alternate_site_id', key='UVMP003').batch
        self.assertEqual((batch.kind, batch.remarks, batch.uploaded_by), (UploadBatch.Kind.CORRECTION, 'Same tower, renumbered (circle letter 5 Nov)', self.admin))

    def test_one_identifier_can_never_name_two_sites(self):
        target = Site.objects.get(site_key='UVMP009')
        unmatched.map_alternate('UVMP003', target, user=self.admin, reason='evidence')
        with self.assertRaisesRegex(unmatched.ResolutionRejected, 'already an identifier of UVMP009'):
            unmatched.map_alternate('UVMP003', Site.objects.get(site_key='UVRJ001'), user=self.admin, reason='evidence')
        with self.assertRaisesRegex(unmatched.ResolutionRejected, 'itself a master site ID'):
            unmatched.map_alternate('UVMP001', target, user=self.admin, reason='evidence')
        IdentifierConflict.objects.create(kind='band_2100', key='T4MP99X', value='T4MP99X', claims=[], active=True, batch=self.upload)
        with self.assertRaisesRegex(unmatched.ResolutionRejected, 'blocked'):
            unmatched.map_alternate('T4MP99X', target, user=self.admin, reason='evidence')
        with self.assertRaisesRegex(unmatched.ResolutionRejected, 'needs a reason'):
            unmatched.map_alternate('LWEBH01', target, user=self.admin, reason=' ')
        with self.assertRaisesRegex(unmatched.ResolutionRejected, 'Only an Admin'):
            unmatched.map_alternate('LWEBH01', target, user=portal_user('map-ci', 'ci'), reason='evidence')
        self.assertEqual(SiteIdentifier.objects.filter(kind='alternate_site_id').count(), 1)

    def test_4g_and_lwe_identities_stay_separate(self):
        unmatched.map_alternate('LWEBH01', Site.objects.get(site_key='UVMP009'), user=self.admin, reason='wrong mapping on purpose')
        result = unmatched.process_pending(user=self.admin)
        self.assertEqual(self.site_days('UVMP009'), 0)  # an LWE row never fills a 4G site
        self.assertEqual(result['uploads'][0]['rejected_rows'], 1)
        rejected = UploadBatch.objects.get(pk=self.upload.pk).report['pending_processed'][0]['rejected_rows']
        self.assertEqual(rejected[0]['code'], 'technology_mismatch')

    def test_an_authorized_correction_is_never_overwritten(self):
        unmatched.map_alternate('UVMP003', Site.objects.get(site_key='UVMP009'), user=self.admin, reason='evidence')
        unmatched.process_pending(user=self.admin)
        record = DailySitePerformance.objects.get(site__site_key='UVMP009', report_date=date(2026, 10, 2))
        daily.correct(record, 99.0, user=self.admin, reason='Verified with the circle')
        again = self.load_uptime(name='again.xlsx')  # the same file again: a lower-precedence value for a corrected record
        self.assertEqual(again.records_conflict, 1)
        record.refresh_from_db()
        self.assertEqual((record.availability_pct, record.batch.kind), (99.0, UploadBatch.Kind.CORRECTION))
        self.assertTrue(DailyPerformanceEvent.objects.filter(site=record.site, report_date=record.report_date, action='conflict').exists())


class OlderUploadTests(UnmatchedCase):
    def test_uploads_without_the_detail_are_flagged_and_can_be_refreshed(self):
        self.upload.report = {k: v for k, v in self.upload.report.items() if k != 'unmatched_sites'}  # as uploads before 7 Nov 2026
        self.upload.save(update_fields=['report'])
        self.assertEqual(unmatched.report()['uploads_without_detail'], [self.upload.pk])
        self.assertIsNone(self.status('UVMP003')['pending_site_days'])
        self.assertEqual(unmatched.refresh_details(user=self.admin), 1)
        self.assertEqual((unmatched.report()['uploads_without_detail'], self.status('UVMP003')['pending_site_days']), ([], 3))


class ApiTests(UnmatchedCase):
    def test_report_map_and_process_through_the_api(self):
        self.client.force_login(self.admin)
        sites = {s['site_id']: s for s in self.client.get(reverse('sitedata-unmatched')).json()['sites']}
        self.assertEqual(sites['UVMP003']['status'], 'pending')
        refused = self.client.post(reverse('sitedata-unmatched-map'), {'identifier': 'UVMP003', 'site_id': 'UVMP001', 'reason': ''}, content_type='application/json')
        self.assertEqual(refused.status_code, 400)
        mapped = self.client.post(reverse('sitedata-unmatched-map'), {'identifier': 'UVMP003', 'site_id': 'UVMP009', 'reason': 'evidence'}, content_type='application/json')
        self.assertEqual(mapped.status_code, 201, mapped.content[:300])
        self.assertEqual(self.client.post(reverse('sitedata-unmatched-process'), {}, content_type='application/json').status_code, 400)  # confirm
        done = self.client.post(reverse('sitedata-unmatched-process'), {'confirm': True}, content_type='application/json').json()
        self.assertEqual(done['counts']['accepted'], 3)
        self.assertEqual({s['site_id']: s['status'] for s in done['sites']}['UVMP003'], 'processed')

    def test_only_admins(self):
        self.client.force_login(portal_user('unmatched-ci', 'ci'))
        self.assertEqual(self.client.get(reverse('sitedata-unmatched')).status_code, 403)
        self.assertEqual(self.client.post(reverse('sitedata-unmatched-process'), {'confirm': True}, content_type='application/json').status_code, 403)
