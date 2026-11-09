"""The same Up-Time Report into the legacy tables and into the new data layer: duplicate detection is scoped to each
destination (apps.uptimedb.importer vs apps.sitedata.uptime_master, /api/sitedata/uptime/). Test database only."""
from datetime import date
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from apps.sitedata import daily, portfolio, uptime_master
from apps.sitedata.models import DailyPerformanceEvent, DailySitePerformance, UploadBatch
from apps.uptimedb import importer as legacy
from apps.uptimedb.models import DataImportBatch, SiteDailyPerformance, UptimeSite
from tests.auth_helpers import SignedInTestCase, portal_user
from tests.test_sitedata import SiteDataTestCase
from tests.workbook_factory import write_workbook

XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


class DestinationCase(SignedInTestCase, SiteDataTestCase):
    def setUp(self):
        super().setUp()
        portfolio.clear_cache()
        self.addCleanup(portfolio.clear_cache)
        self.load_matrix()
        self.path = write_workbook(self.tmp / 'RJ, MP & OD - Uptime Report.xlsx')

    def legacy_import(self):
        return legacy.commit(legacy.preview(self.path, self.path.name, user=self.admin), user=self.admin)

    def new_preview(self):
        return uptime_master.preview(self.path, self.path.name, user=self.admin)


class ScopedDuplicateDetectionTests(DestinationCase):
    def test_a_file_imported_into_the_legacy_tables_can_still_be_imported_into_the_new_layer(self):
        old = self.legacy_import()
        self.assertEqual(legacy.preview(self.path, self.path.name, user=self.admin).report['already_imported']['batch'], old.pk)  # legacy: protected
        legacy_rows = SiteDailyPerformance.objects.count()
        batch = self.new_preview()
        self.assertIsNone(batch.report['already_imported'])  # another destination does not count
        self.assertEqual([x['batch'] for x in batch.report['legacy_imports']], [old.pk])  # listed for information
        self.assertGreater(batch.records_accepted, 0)
        uptime_master.commit(batch, user=self.admin)
        self.assertEqual(DailySitePerformance.objects.count(), batch.records_accepted)
        self.assertEqual(SiteDailyPerformance.objects.count(), legacy_rows)  # the legacy import is untouched
        self.assertEqual(DataImportBatch.objects.get(pk=old.pk).status, DataImportBatch.Status.COMMITTED)

    def test_within_the_new_layer_a_repeat_is_reported_and_adds_nothing(self):
        first = self.new_preview()
        uptime_master.commit(first, user=self.admin)
        stored = DailySitePerformance.objects.count()
        again = self.new_preview()
        self.assertEqual(again.report['already_imported']['batch'], first.pk)
        self.assertTrue(any('already imported into the new data layer' in w for w in again.report['warnings']))
        self.assertEqual((again.records_accepted, again.records_duplicate), (0, first.records_accepted))
        uptime_master.commit(again, user=self.admin)
        self.assertEqual(DailySitePerformance.objects.count(), stored)  # one record per site, date and technology
        self.assertEqual(again.checksum_sha256, first.checksum_sha256)  # the original fingerprint is kept on both uploads

    def test_an_authorized_correction_is_never_overwritten_by_a_re_import(self):
        uptime_master.commit(self.new_preview(), user=self.admin)
        record = DailySitePerformance.objects.filter(site__site_key='UVMP001', report_date=date(2026, 10, 1)).get()
        daily.correct(record, 50.0, user=self.admin, reason='Verified with the circle')
        again = self.new_preview()
        self.assertEqual(again.records_conflict, 1)  # the file's value is lower precedence than the correction
        uptime_master.commit(again, user=self.admin)
        record.refresh_from_db()
        self.assertEqual(record.availability_pct, 50.0)
        self.assertEqual(record.batch.kind, UploadBatch.Kind.CORRECTION)
        self.assertTrue(DailyPerformanceEvent.objects.filter(site=record.site, report_date=record.report_date, action='conflict').exists())

    def test_the_new_layer_never_writes_legacy_tables(self):
        uptime_master.commit(self.new_preview(), user=self.admin)
        self.assertEqual((UptimeSite.objects.count(), SiteDailyPerformance.objects.count(), DataImportBatch.objects.count()), (0, 0, 0))


class MonthScopeTests(DestinationCase):
    def test_months_from_september_2026_to_the_current_month_unless_listed(self):
        with self.settings(SITEDATA_MASTER_DAILY_MONTHS=None), mock.patch('apps.sitedata.uptime_master.timezone.localdate', return_value=date(2026, 11, 7)):
            self.assertEqual(uptime_master.months_in_scope(), {date(2026, 9, 1), date(2026, 10, 1), date(2026, 11, 1)})
        with self.settings(SITEDATA_MASTER_DAILY_MONTHS=None), mock.patch('apps.sitedata.uptime_master.timezone.localdate', return_value=date(2027, 1, 3)):
            self.assertEqual(max(uptime_master.months_in_scope()), date(2027, 1, 1))  # across a year end
            self.assertEqual(min(uptime_master.months_in_scope()), date(2026, 9, 1))  # earlier snapshot months stay out
        with override_settings(SITEDATA_MASTER_DAILY_MONTHS=('2026-09',)):
            self.assertEqual(uptime_master.months_in_scope(), {date(2026, 9, 1)})  # an explicit list wins


class ApiTests(DestinationCase):
    def upload(self, **data):
        return self.client.post(reverse('sitedata-uptime-preview'), {'file': SimpleUploadedFile(self.path.name, self.path.read_bytes(), XLSX), **data})

    def test_preview_confirm_and_commit_through_the_api(self):
        self.client.force_login(self.admin)
        self.legacy_import()
        preview = self.upload()
        self.assertEqual(preview.status_code, 201, preview.content[:300])
        body = preview.json()
        self.assertEqual((body['kind'], body['report']['already_imported'], len(body['report']['legacy_imports'])), ('uptime_master', None, 1))
        self.assertEqual(DailySitePerformance.objects.count(), 0)  # a preview writes no record
        url = reverse('sitedata-uptime-commit', args=[body['id']])
        self.assertEqual(self.client.post(url, {}, content_type='application/json').status_code, 400)  # confirmation required
        done = self.client.post(url, {'confirm': True}, content_type='application/json')
        self.assertEqual((done.status_code, done.json()['status']), (200, 'committed'))
        self.assertEqual(DailySitePerformance.objects.count(), body['counts']['accepted'])
        self.assertEqual(self.client.get(reverse('sitedata-uptime-issues', args=[body['id']])).status_code, 200)
        self.assertEqual(self.upload(project='Unknown').status_code, 400)

    def test_only_admins_may_import(self):
        self.client.force_login(portal_user('uptime-ci', 'ci'))
        self.assertEqual(self.upload().status_code, 403)
