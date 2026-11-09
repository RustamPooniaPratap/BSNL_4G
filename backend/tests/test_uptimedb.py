"""PostgreSQL import of the Up-Time Report and the global data source selector."""
import tempfile
from datetime import date
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.dashboard import metrics, workbook
from apps.dashboard.metrics import Selection
from apps.uptimedb import datasource, importer
from apps.uptimedb.models import DataImportBatch, SiteDailyPerformance, SiteMonthlyPerformance, UptimeSite
from apps.uptimedb.parser import parse_workbook

from .auth_helpers import portal_user
from .test_metrics import SEPTEMBER
from .workbook_factory import DEFAULT_SITES, write_workbook

OCT1, OCT3 = date(2026, 10, 1), date(2026, 10, 3)
MONTHLY = {  # one value per DEFAULT_SITES row; None = blank cell
    'FF Count-Sep-26': [3, 1, None, 0, 2, 1, 0],
    'Sep-26 Outage Min.': [1440, 0, None, 720, 0, 288, 0],
    'Sep-26 UpTime': [0.9667, 1, None, 0.9833, 1, 0.9933, 1],
    'Aug-26 Outage Min.': [0, 43.2, 2880, None, 0, 0, 14.4],
    'Aug-26 UpTime': [1, 0.999, 0.9355, None, 1, 1, 0.9997],
}
XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


class ImportTestCase(TestCase):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._override = override_settings(DATA_DIR=self.tmp / 'data', MASTER_WORKBOOK_PATH='')
        self._override.enable()
        datasource.clear_cache()
        workbook.clear_cache()

    def tearDown(self):
        self._override.disable()
        datasource.clear_cache()
        workbook.clear_cache()
        self._tmp.cleanup()
        super().tearDown()

    def workbook(self, name='master.xlsx', **kwargs) -> Path:
        return write_workbook(self.tmp / name, monthly=kwargs.pop('monthly', MONTHLY), **kwargs)

    def imported(self, path=None, **kwargs) -> DataImportBatch:
        path = path or self.workbook()
        return importer.commit(importer.preview(path, path.name), **kwargs)


class ParserTests(ImportTestCase):
    def test_reads_sites_months_and_both_daily_blocks_keeping_blanks_empty(self):
        parsed = parse_workbook(self.workbook())
        self.assertEqual(len(parsed.sites), 7)
        foxtrot = parsed.sites[('LWE', 'OD', 'LWEOD01')]
        self.assertEqual((foxtrot['circle_raw'], foxtrot['on_air']), ('Odisha', True))
        days = parsed.daily[('LWE', 'OD', 'LWEOD01')]
        self.assertEqual(days[date(2026, 10, 2)], (720.0, 50.0))  # outage from the first run, uptime % from the second
        self.assertIsNone(days[OCT3][0])  # blank outage stays None, never 0
        sep = parsed.monthly[('4G Saturation', 'MP', 'UVMP003')][date(2026, 9, 1)]
        self.assertEqual((sep['outage_minutes'], sep['uptime_pct'], sep['ff_count']), (None, None, None))
        self.assertEqual(parsed.monthly[('4G Saturation', 'MP', 'UVMP001')][date(2026, 9, 1)]['uptime_pct'], 96.67)
        self.assertEqual(parsed.daily_months['2026-10']['reported_dates'], ['2026-10-01', '2026-10-02', '2026-10-03'])

    def test_rejects_duplicates_and_rows_without_ids_and_skips_totals(self):
        sites = DEFAULT_SITES + [
            ('4G Satu.', 'MP', 'UVMP001', 'Alpha copy', 'Yes', 'Yes', [0]),  # same identity
            ('4G Satu.', 'MP', '', 'No ID', 'Yes', 'Yes', [0]),
            ('Grand Total', '', '', '', None, None, [10]),
        ]
        parsed = parse_workbook(self.workbook(sites=sites, monthly={}))
        self.assertEqual(len(parsed.sites), 7)
        self.assertEqual(sorted(i['code'] for i in parsed.issues if i['severity'] == 'rejected'), ['duplicate_key', 'missing_site_id'])
        self.assertEqual(parsed.skipped, {'summary': 1})

    def test_a_sheet_without_project_column_needs_a_stated_project(self):
        path = self.workbook()
        from openpyxl import load_workbook
        book = load_workbook(path)
        book['Up-Time Report'].delete_cols(1)
        book.save(path)
        with self.assertRaisesMessage(Exception, "no 'Project' column"):
            parse_workbook(path)
        self.assertEqual({k[0] for k in parse_workbook(path, default_project='4G Saturation').sites}, {'4G Saturation'})


class CommitTests(ImportTestCase):
    def test_preview_writes_nothing_and_commit_writes_sites_months_and_reported_days(self):
        batch = importer.preview(self.workbook(), 'master.xlsx')
        self.assertEqual(batch.report['primary']['sites'], 7)
        self.assertEqual(UptimeSite.objects.count(), 0)
        batch = importer.commit(batch)
        self.assertEqual(batch.counts['sites'], {'inserted': 7, 'updated': 0, 'unchanged': 0})
        self.assertEqual(UptimeSite.objects.count(), 7)
        self.assertEqual(SiteMonthlyPerformance.objects.count(), 7 * 3)  # Aug, Sep, Oct
        self.assertEqual(SiteDailyPerformance.objects.count(), 7 * 3)  # 1-3 Oct only: the reported dates
        row = SiteDailyPerformance.objects.get(site__site_id='LWEOD01', date=OCT3)
        self.assertIsNone(row.outage_minutes)
        site = UptimeSite.objects.get(site_id='LWEOD01')
        self.assertEqual((site.source_file, site.source_row, site.batch_id), ('master.xlsx', 8, batch.pk))

    def test_reimporting_the_same_file_changes_nothing(self):
        path = self.workbook()  # the same file twice (saving a workbook again changes its bytes)
        self.imported(path)
        again = self.imported(path)
        for kind in ('sites', 'monthly', 'daily'):
            self.assertEqual(again.counts[kind]['inserted'] + again.counts[kind]['updated'], 0, kind)
        self.assertEqual((UptimeSite.objects.count(), SiteDailyPerformance.objects.count()), (7, 21))
        self.assertIn('already_imported', DataImportBatch.objects.filter(status='committed').order_by('pk').last().report)

    def test_a_changed_value_is_updated_and_sites_missing_from_a_file_are_kept(self):
        self.imported()
        changed = [*DEFAULT_SITES[:5], (*DEFAULT_SITES[5][:6], [0, 700, None])]  # Golf dropped, Foxtrot changed
        batch = self.imported(self.workbook('v2.xlsx', sites=changed, monthly={}))
        self.assertEqual(batch.counts['daily']['updated'], 1)
        self.assertEqual(SiteDailyPerformance.objects.get(site__site_id='LWEOD01', date=date(2026, 10, 2)).outage_minutes, 700)
        self.assertTrue(UptimeSite.objects.filter(site_id='LWEBH01').exists())  # never deleted

    def test_a_failed_commit_leaves_no_partial_data(self):
        batch = importer.preview(self.workbook(), 'master.xlsx')
        with self.assertRaises(importer.ImportRejected):
            from unittest import mock
            with mock.patch.object(SiteDailyPerformance.objects, 'bulk_create', side_effect=RuntimeError('disk full')):
                importer.commit(batch)
        self.assertEqual((UptimeSite.objects.count(), SiteMonthlyPerformance.objects.count()), (0, 0))
        self.assertEqual(DataImportBatch.objects.get(pk=batch.pk).status, 'failed')


class ReconciliationTests(ImportTestCase):
    def test_differences_are_listed_and_a_choice_is_required_before_commit(self):
        primary = self.workbook()
        other_sites = [(*s[:6], [999, 0, 0]) if s[2] == 'UVMP001' else s for s in DEFAULT_SITES if s[0] == '4G Satu.']
        other = self.workbook('rj.xlsx', sites=other_sites)
        batch = importer.preview(primary, 'master.xlsx', reconciliation=other, reconciliation_name='rj.xlsx')
        comparison = batch.report['comparison']
        self.assertEqual((comparison['overlapping_sites'], comparison['sites_with_differences']), (4, 1))
        self.assertEqual(comparison['differences']['daily.Oct-26.outage_minutes']['examples'][0]['site_id'], 'UVMP001')
        with self.assertRaisesMessage(importer.ImportRejected, 'Choose which file'):
            importer.commit(batch)
        importer.commit(batch, conflict_source='reconciliation')
        self.assertEqual(SiteDailyPerformance.objects.get(site__site_id='UVMP001', date=OCT1).outage_minutes, 999)
        self.assertEqual(UptimeSite.objects.get(site_id='UVMP001').source_file, 'rj.xlsx')
        self.assertEqual(UptimeSite.objects.get(site_id='LWEOD01').source_file, 'master.xlsx')


class DatabaseSourceTests(ImportTestCase):
    """The PostgreSQL dataset must give exactly the Excel results for every dashboard calculation."""

    def assert_same_results(self, path):
        excel = workbook.load_dataset(path)
        self.imported(path)
        db = datasource.database_dataset()
        self.assertEqual((db.dates, db.reported_dates, db.month_label, db.has_om_start), (excel.dates, excel.reported_dates, excel.month_label, excel.has_om_start))
        day = excel.latest_date
        for selection in (Selection(None, None, 'on_air'), Selection(None, None, 'all'), Selection('LWE', None, 'om_start'),
                          Selection('4G Saturation', 'MP', 'all')):
            with self.subTest(selection=selection):
                self.assertEqual(metrics.summary(db, selection, day), metrics.summary(excel, selection, day))
                self.assertEqual(metrics.breakdown(db, selection, day), metrics.breakdown(excel, selection, day))
                self.assertEqual(metrics.trend(db, selection, OCT1, day), metrics.trend(excel, selection, OCT1, day))
                self.assertEqual(metrics.monthly(db, selection, day), metrics.monthly(excel, selection, day))
                self.assertEqual(metrics.threshold_analysis(db, selection, day), metrics.threshold_analysis(excel, selection, day))
                self.assertEqual(metrics.team_performance(db, selection, day, 'ci'), metrics.team_performance(excel, selection, day, 'ci'))
                for group in ('ci', 'ie'):
                    self.assertEqual(metrics.team_monthly_nsla(db, selection, day, group),
                                     metrics.team_monthly_nsla(excel, selection, day, group))
                self.assertEqual(metrics.circle_top_performers(db, selection, day), metrics.circle_top_performers(excel, selection, day))

    def test_every_calculation_matches_the_excel_source(self):
        self.assert_same_results(self.workbook())

    def test_september_daily_history_is_used_once_imported(self):
        path = self.workbook(september=SEPTEMBER)
        self.assert_same_results(path)
        state = datasource.completeness()
        self.assertTrue(state['previous_month_daily'])
        self.assertIn('2026-09', state['daily_months'])

    def test_missing_previous_month_daily_history_is_reported(self):
        self.imported()
        state = datasource.completeness()
        self.assertFalse(state['previous_month_daily'])
        self.assertTrue(any('Sep-26 daily history is missing' in w for w in state['warnings']))


class ApiTests(ImportTestCase):
    def upload(self, client, path):
        return client.post(reverse('import-preview'), {'file': SimpleUploadedFile(path.name, path.read_bytes(), XLSX)})

    def test_admin_previews_commits_and_switches_the_dashboard_source(self):
        admin = portal_user('asha.admin', 'admin')
        self.client.force_login(admin)
        self.assertEqual(self.client.get(reverse('data-source')).json()['active'], 'excel')  # Excel stays the default
        refused = self.client.put(reverse('data-source'), {'source': 'database', 'confirm': True}, content_type='application/json')
        self.assertEqual(refused.status_code, 409)  # empty database
        preview = self.upload(self.client, self.workbook())
        self.assertEqual(preview.status_code, 201)
        commit = self.client.post(reverse('import-commit', args=[preview.json()['id']]), {}, content_type='application/json')
        self.assertEqual(commit.json()['status'], 'committed')
        unconfirmed = self.client.put(reverse('data-source'), {'source': 'database'}, content_type='application/json')
        self.assertEqual(unconfirmed.status_code, 400)
        incomplete = self.client.put(reverse('data-source'), {'source': 'database', 'confirm': True}, content_type='application/json')
        self.assertEqual(incomplete.status_code, 409)  # Sep daily history missing: must be acknowledged
        switched = self.client.put(reverse('data-source'), {'source': 'database', 'confirm': True, 'acknowledge_warnings': True},
                                   content_type='application/json')
        self.assertEqual(switched.json()['active'], 'database')
        # The dashboard pages read only the new data layer (sitedata): the imported uptimedb tables are never used, whatever
        # this legacy switch says. Here the new layer is empty, so the page reports that instead of showing old data.
        summary = self.client.get(reverse('dashboard-summary'))
        self.assertEqual(summary.status_code, 503)
        self.assertIn('new data layer', summary.json()['error'])
        self.assertIsNone(self.client.get(reverse('dashboard-workbook')).json()['active'])

    def test_ci_cannot_import_or_switch_the_source_but_sees_which_is_active(self):
        self.client.force_login(portal_user('ravi.ci', 'ci'))
        self.assertEqual(self.client.get(reverse('data-source')).json()['active'], 'excel')
        self.assertEqual(self.client.put(reverse('data-source'), {'source': 'database', 'confirm': True}, content_type='application/json').status_code, 403)
        self.assertEqual(self.upload(self.client, self.workbook()).status_code, 403)
        self.assertEqual(self.client.get(reverse('import-list')).status_code, 403)
        self.assertEqual(DataImportBatch.objects.count(), 0)

    def test_signed_out_requests_are_refused(self):
        self.assertEqual(self.client.get(reverse('data-source')).status_code, 401)
        self.assertEqual(self.client.get(reverse('import-list')).status_code, 401)


class DailyOnlyImportTests(ImportTestCase):
    def test_adds_a_previous_months_days_without_touching_sites_or_monthly_figures(self):
        self.imported()
        renamed = [(*s[:3], f'{s[3]} (Sep name)', *s[4:]) for s in DEFAULT_SITES]  # different site names in the Sep file
        sep_file = self.workbook('sep.xlsx', sites=renamed, monthly={'Sep-26 Outage Min.': [9999] * 7}, september=SEPTEMBER)
        batch = importer.preview(sep_file, 'sep.xlsx', daily_only=True)
        effect = batch.report['daily_effect']
        self.assertEqual((effect['months'], effect['sites_in_database']), (['2026-09', '2026-10'], 7))
        batch = importer.commit(batch)
        self.assertEqual(batch.counts['daily']['inserted'], 7 * 4)  # 1-4 Sep (the fixture reports 4 days); October values are unchanged
        self.assertNotIn('sites', batch.counts)
        self.assertEqual(UptimeSite.objects.get(site_id='UVMP001').site_name, 'Alpha')  # not renamed
        self.assertEqual(SiteMonthlyPerformance.objects.get(site__site_id='UVMP001', month=date(2026, 9, 1)).outage_minutes, 1440)  # not 9999
        self.assertEqual(SiteDailyPerformance.objects.get(site__site_id='UVMP002', date=date(2026, 9, 1)).outage_minutes, 1440)
        self.assertTrue(datasource.completeness()['previous_month_daily'])

    def test_a_sheet_without_project_column_is_read_with_the_stated_project(self):
        self.imported()
        path = self.workbook('rj.xlsx', september=SEPTEMBER)
        from openpyxl import load_workbook
        book = load_workbook(path)
        book['Up-Time Report'].delete_cols(1)
        book.save(path)
        with self.assertRaisesMessage(importer.ImportRejected, "no 'Project' column"):
            importer.preview(path, 'rj.xlsx', daily_only=True)
        batch = importer.commit(importer.preview(path, 'rj.xlsx', daily_only=True, project='4G Saturation'))
        self.assertEqual(batch.counts['sites_not_in_database'], 3)  # the LWE rows read as 4G do not exist as 4G sites
        self.assertEqual(SiteDailyPerformance.objects.filter(date__month=9).count(), 4 * 4)  # only the 4 real 4G sites, 1-4 Sep
