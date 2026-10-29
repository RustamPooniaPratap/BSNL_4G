"""Historical day-wise backfill (apps.uptimedb.daywise, `manage.py import_daywise`) and the September comparisons it feeds.

Synthetic workbooks only, generated here in the layout of the "Day Wise Outage" sheet: a title row, a header row with
Circle (state names), Site ID as per Nirikshan, the month's Outage Min total, a run of daily outage minutes and a second
run of the same dates with the uptime fraction. No reference file is read.
"""
import tempfile
from datetime import date, datetime
from io import StringIO
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone
from openpyxl import Workbook

from apps.dashboard import metrics
from apps.dashboard.metrics import Selection
from apps.uptimedb import datasource, daywise
from apps.uptimedb.models import AppSetting, DataImportBatch, SiteDailyPerformance, SiteMonthlyPerformance, UptimeSite

SEP = [date(2026, 9, d) for d in range(1, 4)]  # three days keep the fixtures small


def workbook(path: Path, rows, dates=SEP, *, uptime=True, sheet='Day Wise Outage'):
    """rows: (circle, site id, [outage per date]); None = blank cell."""
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(['', '', 'title row'])
    header = ['Circle', 'Site Category', 'Site ID as per Nirikshan', 'On-Air', 'Outage Min', "Sept'26 MTD", 'No. of days',
              *[datetime(d.year, d.month, d.day) for d in dates]]
    if uptime:
        header += ['Bucket', *[datetime(d.year, d.month, d.day) for d in dates]]
    ws.append(header)
    for circle, site_id, values in rows:
        numbers = [v for v in values if isinstance(v, (int, float))]
        line = [circle, 'LWE', site_id, 'Yes', sum(numbers), None, len(dates), *values]
        if uptime:
            line += ['>98.5', *[None if not isinstance(v, (int, float)) else 1 - v / 1440 for v in values]]
        ws.append(line)
    wb.save(path)
    return path


class DaywiseTestCase(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        override = override_settings(DATA_DIR=self.tmp / 'data')
        override.enable()
        self.addCleanup(override.disable)
        self.master = DataImportBatch.objects.create(original_filename='master.xlsx', checksum_sha256='m', sheet_name='Up-Time Report',
                                                     stored_path='-', status=DataImportBatch.Status.COMMITTED, committed_at=timezone.now())
        self.sites = {}
        for project, circle, site_id in (('LWE', 'JH', 'LWEJH0001'), ('LWE', 'JH', 'LWEJH0002'), ('LWE', 'BH', 'LWEBH0001'),
                                         ('LWE', 'MP', 'LWEMP0001'), ('4G Saturation', 'OD', 'UVOR001'), ('4G Saturation', 'MP', 'UVMP001')):
            self.sites[site_id] = UptimeSite.objects.create(project=project, circle=circle, site_id=site_id, site_key=site_id, batch=self.master,
                                                            source_row=len(self.sites) + 1, on_air=True)

    def file(self, rows, name='lwe.xlsx', **kwargs):
        return workbook(self.tmp / name, rows, **kwargs)

    def stored(self, site_id):
        return {d.date: d.outage_minutes for d in SiteDailyPerformance.objects.filter(site=self.sites[site_id])}


class ParseAndMatchTests(DaywiseTestCase):
    def test_multi_day_values_go_to_their_own_dates_with_uptime_from_the_second_run(self):
        path = self.file([('Jharkhand', 'LWEJH0001', [0, 14.4, 1440])])
        parsed = daywise.parse(path)
        self.assertEqual((parsed.header_row, parsed.id_column, parsed.dates, parsed.has_uptime), (2, 'Site ID as per Nirikshan', SEP, True))
        batch = daywise.commit(path, 'LWE')
        rows = {d.date: (d.outage_minutes, d.uptime_pct) for d in SiteDailyPerformance.objects.filter(site=self.sites['LWEJH0001'])}
        self.assertEqual(rows[SEP[0]], (0, 100.0))
        self.assertAlmostEqual(rows[SEP[1]][1], 99.0, places=6)
        self.assertEqual(rows[SEP[2]], (1440, 0.0))
        self.assertEqual((batch.kind, batch.project, batch.status, batch.counts['daily']['inserted']), ('master_workbook', 'LWE', 'committed', 3))
        self.assertTrue(Path(batch.stored_path).is_file())  # a staged copy: the source file is not needed afterwards

    def test_state_names_and_codes_match_only_the_site_in_that_circle(self):
        self.assertEqual([daywise.canonical_circle(n) for n in ('Jharkhand', 'JH', 'Madhya Pradesh', 'Chhattisgarh', 'Atlantis', '')],
                         ['JH', 'JH', 'MP', 'CG', None, None])
        result = daywise.analyse(daywise.parse(self.file([
            ('Jharkhand', 'LWEJH0001', [1, 2, 3]),
            ('Bihar', 'LWEJH0002', [1, 2, 3]),        # the master has it in JH
            ('Jharkhand', 'LWEJH9999', [1, 2, 3]),    # not in the master
            ('Odisha', 'UVOR001', [1, 2, 3]),         # a 4G site in an LWE file
            ('Atlantis', 'LWEMP0001', [1, 2, 3]),     # unknown circle name
            ('Jharkhand', 'LWEJH0001', [9, 9, 9]),    # repeated
            ('Jharkhand', '', [1, 2, 3]),
        ])), 'LWE')
        self.assertEqual(result['summary']['rows_resolved'], 1)
        self.assertEqual(result['summary']['rejected_by_code'], {'circle_mismatch': 1, 'unknown_site': 1, 'other_project': 1, 'unknown_circle': 1,
                                                                 'duplicate_site': 1, 'missing_site_id': 1})

    def test_unresolved_rows_are_never_written_and_block_the_commit_unless_confirmed(self):
        path = self.file([('Jharkhand', 'LWEJH0001', [1, 2, 3]), ('Jharkhand', 'LWEJH9999', [1, 2, 3])])
        with self.assertRaisesMessage(daywise.DaywiseError, '1 rows could not be matched'):
            daywise.commit(path, 'LWE')
        self.assertEqual((SiteDailyPerformance.objects.count(), DataImportBatch.objects.count()), (0, 1))
        batch = daywise.commit(path, 'LWE', allow_rejected=True)
        self.assertEqual((SiteDailyPerformance.objects.count(), batch.rejected_count), (3, 1))
        self.assertEqual(batch.report['rejected'][0]['site_id'], 'LWEJH9999')
        with self.assertRaisesMessage(daywise.DaywiseError, 'No row of the file matches'):
            daywise.commit(self.file([('Jharkhand', 'LWEJH9999', [1, 2, 3])], name='none.xlsx'), 'LWE', allow_rejected=True)

    def test_missing_and_invalid_values_are_not_written_and_never_become_zero(self):
        path = self.file([('Jharkhand', 'LWEJH0001', [None, 'NA', 'abc'])])
        result = daywise.analyse(daywise.parse(path), 'LWE')
        self.assertEqual(result['summary']['site_days'], {'insert': 0, 'fill_missing': 0, 'identical_skipped': 0, 'conflicts_not_changed': 0,
                                                          'invalid_not_written': 1, 'not_reported': 2})
        self.assertEqual(result['invalid'][0]['value'], 'abc')

    def test_out_of_range_outage_is_kept_and_flagged(self):
        result = daywise.analyse(daywise.parse(self.file([('Jharkhand', 'LWEJH0001', [1471.1, 0, 0])])), 'LWE')
        self.assertEqual((result['summary']['site_days']['insert'], result['summary']['flagged_out_of_range']), (3, 1))

    def test_the_sheet_and_its_columns_must_be_present(self):
        with self.assertRaisesMessage(daywise.DaywiseError, 'No "Day Wise Outage" sheet'):
            daywise.parse(workbook(self.tmp / 'other.xlsx', [('Jharkhand', 'LWEJH0001', [1, 2, 3])], sheet='Summary'))
        broken = self.tmp / 'broken.xlsx'
        broken.write_bytes(b'not a workbook')
        with self.assertRaisesMessage(daywise.DaywiseError, 'cannot be opened'):
            daywise.parse(broken)


class IdempotenceAndConflictTests(DaywiseTestCase):
    def test_rerunning_the_same_file_writes_nothing(self):
        path = self.file([('Jharkhand', 'LWEJH0001', [1, 2, 3]), ('Bihar', 'LWEBH0001', [0, 0, 0])])
        daywise.commit(path, 'LWE')
        again = daywise.commit(path, 'LWE')
        self.assertEqual(again.counts['daily'], {'inserted': 0, 'filled': 0, 'unchanged': 6, 'conflicts_not_changed': 0})
        self.assertEqual(SiteDailyPerformance.objects.count(), 6)

    def test_conflicting_stored_values_are_never_overwritten_and_blanks_are_filled(self):
        SiteDailyPerformance.objects.create(site=self.sites['LWEJH0001'], date=SEP[0], outage_minutes=99, batch=self.master)
        SiteDailyPerformance.objects.create(site=self.sites['LWEJH0001'], date=SEP[1], outage_minutes=None, batch=self.master)
        batch = daywise.commit(self.file([('Jharkhand', 'LWEJH0001', [1, 2, 3])]), 'LWE')
        self.assertEqual(self.stored('LWEJH0001'), {SEP[0]: 99, SEP[1]: 2, SEP[2]: 3})
        self.assertEqual(batch.counts['daily'], {'inserted': 1, 'filled': 1, 'unchanged': 0, 'conflicts_not_changed': 1})
        self.assertEqual(batch.report['conflicts'][0] | {}, {'row': 3, 'site_id': 'LWEJH0001', 'date': '2026-09-01', 'stored': 99, 'file': 1,
                                                            'stored_uptime_pct': None, 'file_uptime_pct': batch.report['conflicts'][0]['file_uptime_pct']})

    def test_a_failure_rolls_back_every_write(self):
        path = self.file([('Jharkhand', 'LWEJH0001', [1, 2, 3])])
        with mock.patch.object(daywise.DataImportBatch, 'save', side_effect=RuntimeError('disk full')), self.assertRaises(RuntimeError):
            daywise.commit(path, 'LWE')
        self.assertEqual((SiteDailyPerformance.objects.count(), DataImportBatch.objects.count()), (0, 1))

    def test_master_sites_monthly_figures_and_the_source_setting_are_untouched(self):
        AppSetting.objects.create(key=datasource.SOURCE_KEY, value=datasource.DATABASE)
        before = list(UptimeSite.objects.order_by('id').values())
        daywise.commit(self.file([('Jharkhand', 'LWEJH0001', [1, 2, 3])]), 'LWE')
        self.assertEqual(list(UptimeSite.objects.order_by('id').values()), before)
        self.assertEqual((SiteMonthlyPerformance.objects.count(), datasource.active_source()), (0, datasource.DATABASE))

    def test_the_command_reports_without_writing_and_commits_only_when_asked(self):
        path = self.file([('Jharkhand', 'LWEJH0001', [1, 2, 3])])
        out = StringIO()
        call_command('import_daywise', str(path), '--project', 'LWE', stdout=out)
        self.assertIn('Read only: nothing was written.', out.getvalue())
        self.assertIn('"insert": 3', out.getvalue())
        self.assertEqual(SiteDailyPerformance.objects.count(), 0)
        call_command('import_daywise', str(path), '--project', 'LWE', '--commit', stdout=StringIO())
        self.assertEqual(SiteDailyPerformance.objects.count(), 3)
        with self.assertRaises(CommandError):
            call_command('import_daywise', str(self.tmp / 'missing.xlsx'), '--project', 'LWE', stdout=StringIO())


class SeptemberComparisonTests(DaywiseTestCase):
    """The database dataset uses the backfilled September days for the same-days comparison and trend periods."""

    def setUp(self):
        super().setUp()
        AppSetting.objects.create(key=datasource.SOURCE_KEY, value=datasource.DATABASE)
        datasource.clear_cache()
        self.addCleanup(datasource.clear_cache)
        # October: every site reports 1-2 Oct (the current month).
        for site in self.sites.values():
            for d, outage in ((date(2026, 10, 1), 144.0), (date(2026, 10, 2), 0.0)):
                SiteDailyPerformance.objects.create(site=site, date=d, outage_minutes=outage, batch=self.master)
        # 4G September is already stored (as the Master-workbook import of the 4G report did).
        for site_id in ('UVOR001', 'UVMP001'):
            for d in SEP:
                SiteDailyPerformance.objects.create(site=self.sites[site_id], date=d, outage_minutes=72.0, batch=self.master)

    def snapshot(self, project):
        ds = datasource.current_dataset()
        rows = metrics.breakdown(ds, Selection(report_type=project), date(2026, 10, 2))
        oct_mtd = metrics.period_summary(ds, Selection(report_type=project), dates=[date(2026, 10, 1), date(2026, 10, 2)], label='Oct')
        sep = metrics.period_summary(ds, Selection(report_type=project), dates=SEP, label='Sep')
        return rows, oct_mtd, sep

    def test_lwe_september_appears_after_the_backfill_and_october_is_unchanged(self):
        rows, oct_before, sep_before = self.snapshot('LWE')
        self.assertTrue(all(c['previous_uptime_pct'] is None for c in rows['circles']))  # no LWE September days yet
        self.assertIsNone(sep_before['uptime_pct'])
        daywise.commit(self.file([('Jharkhand', 'LWEJH0001', [0, 0, 0]), ('Jharkhand', 'LWEJH0002', [144, 144, 144]),
                                  ('Bihar', 'LWEBH0001', [1440, None, 0]), ('Madhya Pradesh', 'LWEMP0001', [0, 0, 0])]), 'LWE')
        rows, oct_after, sep_after = self.snapshot('LWE')
        self.assertEqual(oct_after, oct_before)  # October MTD is unchanged
        jh = next(c for c in rows['circles'] if c['circle'] == 'JH')
        # Same days of September (1-2 Sep against 1-2 Oct), pooled: (0+0+144+144) / (1440 x 4 site-days).
        self.assertEqual(jh['previous_uptime_pct'], 95.0)
        bh = next(c for c in rows['circles'] if c['circle'] == 'BH')
        self.assertEqual(bh['previous_uptime_pct'], 0.0)  # 1440 on 1 Sep; 2 Sep blank is excluded, never zero
        # September 1-3 pooled over reported site-days only: 8 reported, 1 blank.
        self.assertEqual((sep_after['days_reported'], sep_after['sites_reported']), (3, 4))
        self.assertEqual(sep_after['uptime_pct'], metrics.uptime_pct(144 * 3 + 1440, 11))

    def test_4g_comparisons_are_unchanged_by_an_lwe_backfill(self):
        before = self.snapshot('4G Saturation')
        self.assertEqual(before[0]['comparison']['available'], True)
        daywise.commit(self.file([('Jharkhand', 'LWEJH0001', [0, 0, 0])]), 'LWE')
        self.assertEqual(self.snapshot('4G Saturation'), before)
