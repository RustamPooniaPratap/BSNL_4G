"""Raw daily CNMC CSV upload API (/api/raw-uploads/) on the data layer: preview, commit into the central daily table at
precedence 1, pending (unmatched) rows, permissions per project/circle, double commits, and the validation report.
Synthetic files in the test database only."""
from datetime import date

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.accounts.scope import set_circles
from apps.sitedata import portfolio
from apps.sitedata.models import DailySitePerformance, MonthlySitePerformance, Site, UploadBatch
from tests.auth_helpers import portal_user
from tests.test_sitedata import MATRIX, CSV_HEADER, SiteDataTestCase

G4, LWE = '4G Saturation', 'LWE'


def csv_bytes(rows) -> bytes:
    lines = [','.join(CSV_HEADER)]
    for i, (site, b2100, b700, tcs, circle, day) in enumerate(rows, start=1):
        lines.append(','.join(map(str, [i, site, 'Site', circle, b2100, b700, '', tcs, day])))
    return ('\r\n'.join(lines) + '\r\n').encode()


class RawUploadTestCase(SiteDataTestCase):
    def setUp(self):
        super().setUp()
        self.load_matrix(MATRIX)
        self.client.force_login(self.admin)
        portfolio.clear_cache()
        self.addCleanup(portfolio.clear_cache)

    def preview(self, rows, *, project=G4, circle='MP', day='2026-10-01', expected=201, name='day.csv', content=None):
        upload = SimpleUploadedFile(name, content if content is not None else csv_bytes(rows), content_type='text/csv')
        r = self.client.post(reverse('raw-upload-preview'), {'file': upload, 'project': project, 'circle': circle, 'reporting_date': day})
        self.assertEqual(r.status_code, expected, r.content[:500])
        return r.json()

    def commit(self, batch_id, expected=200):
        r = self.client.post(reverse('raw-upload-commit', args=[batch_id]), {'confirm': True}, content_type='application/json')
        self.assertEqual(r.status_code, expected, r.content[:500])
        return r.json()


class PreviewAndCommitTests(RawUploadTestCase):
    def test_preview_writes_nothing_and_commit_writes_the_daily_table(self):
        rows = [('UVMP001', '', '', '99', 'MP', '01-10-2026'), ('UVMP002', '', '', '', 'MP', '01-10-2026'),
                ('UNKNOWN9', '', '', '50', 'MP', '01-10-2026')]
        batch = self.preview(rows)
        self.assertEqual(batch['status'], 'previewed')
        self.assertEqual(batch['summary']['ready_to_import'], 1)
        self.assertEqual(batch['summary']['by_status']['out_of_scope'], 1)  # no identifier known anywhere: outside the programme
        self.assertEqual(batch['summary']['by_status']['availability'], 1)  # blank: not reported
        self.assertEqual(batch['summary']['classification'], {'matched': 2, 'unmatched_programme': 0, 'outside_programme': 1, 'invalid': 0})
        self.assertEqual(batch['pending_sites'], [])  # only programme identifiers are pending
        self.assertEqual({r['code'] for r in batch['rows']['rows']}, {'ready', 'not_reported', 'outside_programme'})
        self.assertFalse(DailySitePerformance.objects.exists())

        done = self.commit(batch['id'])
        self.assertEqual(done['status'], 'committed')
        self.assertEqual((done['daily']['inserted'], done['daily']['pending']), (1, 0))
        rec = DailySitePerformance.objects.get()
        self.assertEqual((rec.site.site_key, rec.report_date, rec.availability_pct, rec.batch.kind), ('UVMP001', date(2026, 10, 1), 99.0, UploadBatch.Kind.RAW_CSV_4G))
        self.assertAlmostEqual(rec.outage_minutes, 1440 * 0.01)
        self.assertFalse(Site.objects.filter(site_key='UNKNOWN9').exists())  # never created from a CSV row
        self.assertFalse(DailySitePerformance.objects.filter(site__site_key='UVMP002').exists())  # blank is not 0
        # The month is recalculated and the dashboard reads the new record.
        self.assertTrue(MonthlySitePerformance.objects.filter(site__site_key='UVMP001', month=date(2026, 10, 1), is_current=True).exists())

    def test_a_second_commit_of_the_same_upload_is_refused(self):
        batch = self.preview([('UVMP001', '', '', '99', 'MP', '01-10-2026')])
        self.commit(batch['id'])
        self.assertIn('committed', self.commit(batch['id'], expected=409)['error'])
        self.assertEqual(DailySitePerformance.objects.count(), 1)

    def test_the_same_file_again_adds_nothing(self):
        rows = [('UVMP001', '', '', '99', 'MP', '01-10-2026')]
        self.commit(self.preview(rows)['id'])
        again = self.preview(rows)
        self.assertEqual(again['summary']['identical_skipped'], 1)
        self.assertEqual(again['already_imported']['batch'], UploadBatch.objects.filter(processing_status='committed', kind='raw_csv_4g').get().pk)
        self.commit(again['id'])
        self.assertEqual(DailySitePerformance.objects.count(), 1)

    def test_lwe_rows_resolve_through_the_band_mapping(self):
        self.client.force_login(self.admin)
        from tests.test_sitedata import BAND
        from apps.sitedata import bandmap
        batch = self.load_bands(BAND)
        bandmap.commit(batch, user=self.admin)
        preview = self.preview([('MPBLG001', 'T4MP01BLG001lw', 'T4MP28BLG001lw', '97.5', 'MP', '01-10-2026')], project=LWE)
        self.assertEqual(preview['summary']['ready_to_import'], 1)
        self.commit(preview['id'])
        self.assertEqual(DailySitePerformance.objects.get().site.site_key, 'LWEMP01')

    def test_an_unreadable_file_is_refused_with_the_reason(self):
        r = self.preview(None, content=b'\x00\x01 not a csv', expected=400)
        self.assertTrue(r['error'])

    def test_wrong_date_and_circle_rows_are_rejected(self):
        batch = self.preview([('UVMP001', '', '', '99', 'MP', '02-10-2026'), ('UVRJ001', '', '', '99', 'RJ', '01-10-2026')])
        self.assertEqual(batch['summary']['date_mismatches'], 1)
        self.assertEqual(batch['summary']['project_or_circle_mismatches'], 1)
        self.assertEqual(batch['summary']['ready_to_import'], 0)

    def test_validation_report_lists_every_row_not_imported(self):
        batch = self.preview([('UVMP001', '', '', '99', 'MP', '01-10-2026'), ('UNKNOWN9', '', '', '50', 'MP', '01-10-2026')])
        r = self.client.get(reverse('raw-upload-issues', args=[batch['id']]))
        text = r.content.decode('utf-8-sig')
        self.assertIn('UNKNOWN9', text)
        self.assertNotIn(',ready,', text)

    def test_discard_closes_a_preview(self):
        batch = self.preview([('UVMP001', '', '', '99', 'MP', '01-10-2026')])
        r = self.client.post(reverse('raw-upload-discard', args=[batch['id']]))
        self.assertEqual(r.json()['status'], 'discarded')
        self.commit(batch['id'], expected=409)


class PermissionTests(RawUploadTestCase):
    def setUp(self):
        super().setUp()
        self.ci = portal_user('raw-ci-mp', 'ci')
        set_circles(self.ci, ['MP'])

    def test_ci_users_upload_only_their_circles_and_see_only_their_uploads(self):
        admin_batch = self.preview([('UVMP001', '', '', '99', 'MP', '01-10-2026')])
        self.client.force_login(self.ci)
        options = self.client.get(reverse('raw-upload-options')).json()
        self.assertEqual(options['assigned_circles'], ['MP'])
        self.preview([('UVRJ001', '', '', '99', 'RJ', '01-10-2026')], circle='RJ', expected=403)
        own = self.preview([('UVMP001', '', '', '98', 'MP', '01-10-2026')])
        self.assertEqual(self.client.get(reverse('raw-upload', args=[admin_batch['id']])).status_code, 404)
        self.assertEqual([u['id'] for u in self.client.get(reverse('raw-uploads')).json()['uploads']], [own['id']])

    def test_users_without_the_csv_upload_permission_get_nothing(self):
        nobody = portal_user('raw-ci-none', 'ci')
        self.client.force_login(nobody)
        self.assertEqual(self.client.get(reverse('raw-upload-options')).status_code, 403)
