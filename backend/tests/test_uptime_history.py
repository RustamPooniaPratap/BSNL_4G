"""Historical monthly Uptime import into MonthlySitePerformance (category historical_import, apps.sitedata.history).

Synthetic workbooks in the two source layouts (Up-Time Report monthly columns; LWE "Outage Min" + month label) and
synthetic sites; files go to a temporary directory.
"""
import tempfile
from datetime import date, datetime
from pathlib import Path

from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from openpyxl import Workbook

from apps.sitedata import calculations, daily, dataset, history
from apps.sitedata.models import MonthlySitePerformance, Technology, UploadBatch
from tests.auth_helpers import portal_user
from tests.sitedata_factory import batch as make_batch
from tests.sitedata_factory import make_daily, make_site

HIST = MonthlySitePerformance.Category.HISTORICAL_IMPORT
G4, LWE = Technology.G4, Technology.LWE
OCT25, NOV25, MAR26, SEP26 = date(2025, 10, 1), date(2025, 11, 1), date(2026, 3, 1), date(2026, 9, 1)
UPTIME_HEADER = ['Project', 'Circle', 'btsIpId', 'Site name', 'O&M Start - Nov-25', 'Oct-25 Outage Min.', 'Oct-25 Up-Time',
                 'FF Count - Nov-25', 'Nov-25 Outage Min.', 'Nov-25 UpTime', 'Bucket', 'Mar-26 Outage Min.', 'Mar-26 UpTime',
                 'Sep-26 Outage Min.', 'Sep-26 UpTime', datetime(2026, 10, 1)]


def frac(outage, month):
    """The Up-Time fraction that matches ``outage`` over the full month (as the workbook writes it)."""
    return 1 - outage / history.month_minutes(month)


def up_time_row(project, circle, site_id, oct_=None, nov=None, mar=None, *, ff=2, bucket='>=98.5%', om='Yes', sep=0.0):
    def pair(v, m):
        return (v, frac(v, m)) if v is not None else (None, None)
    return [project, circle, site_id, site_id, om, *pair(oct_, OCT25), ff, *pair(nov, NOV25), bucket, *pair(mar, MAR26), *pair(sep, SEP26), None]


def write_up_time(path: Path, rows) -> Path:
    book = Workbook()
    sheet = book.active
    sheet.title = 'Up-Time Report'
    sheet.append(['summary row'])
    sheet.append(UPTIME_HEADER)
    for row in rows:
        sheet.append(row)
    book.save(path)
    return path


def write_lwe(path: Path, rows, jul_label="July'26 MTD") -> Path:
    book = Workbook()
    sheet = book.active
    sheet.title = 'Up-Time Report'
    sheet.append([None, None, None, 3])
    sheet.append(['Circle', 'Site ID', 'btsIpId', 'Site Name', 'Outage Min', "Jan'26", 'Outage Min', jul_label])
    for i, (circle, site_id, jan, jul) in enumerate(rows, start=1):
        sheet.append([circle, i, site_id, site_id, jan, frac(jan, date(2026, 1, 1)) if jan is not None else None,
                      jul, frac(jul, date(2026, 7, 1)) if jul is not None else None])
    book.save(path)
    return path


class HistoryTestCase(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        override = override_settings(SITEDATA_STAGING_DIR=str(self.tmp / 'staged'), SITEDATA_EXCEPTION_DIR=str(self.tmp / 'exceptions'),
                                     SITEDATA_DAILY_FROM='2026-09')
        override.enable()
        self.addCleanup(override.disable)
        self.admin = portal_user('history-admin', 'admin')
        self.mp1 = make_site('UVMPBPL00012', technology=G4, circle='MP', on_air_date=date(2025, 1, 1))
        self.no_date = make_site('UVMPBPL00020', technology=G4, circle='MP', on_air_date=None)          # no On-Air date
        self.late = make_site('UVRJJPR00001', technology=G4, circle='RJ', on_air_date=date(2026, 3, 15))  # On-Air in Mar-26
        self.bh = make_site('LWEBH0063', technology=LWE, circle='BH', on_air_date=date(2025, 6, 1))

    def workbook(self, rows=None, name='consolidated.xlsx'):
        rows = rows if rows is not None else [
            up_time_row('4G Satu.', 'MP', 'UVMPBPL00012', 1200.5, 0.0, 300),
            up_time_row('4G Satu.', 'MP', 'UVMPBPL00020', 4000, 5000, 600),
            up_time_row('4G Satu.', 'RJ', 'UVRJJPR00001', 0.0, 44640 * 0 + 100, 15000),
        ]
        return write_up_time(self.tmp / name, rows)

    def run_import(self, path, allocation=None, fmt=history.UP_TIME_REPORT, **kwargs):
        allocation = allocation or {G4: [OCT25, NOV25, MAR26]}
        upload = history.preview(path, fmt, allocation, user=self.admin, **kwargs)
        return upload, history.commit(upload, user=self.admin)

    def current(self, site, month):
        return MonthlySitePerformance.objects.get(site=site, month=month, calculation_category=HIST, is_current=True)


class ImportTests(HistoryTestCase):
    def test_values_are_imported_as_written_with_their_source_and_no_reporting_days(self):
        upload, done = self.run_import(self.workbook())
        self.assertEqual((done.processing_status, done.records_accepted), (UploadBatch.Processing.COMMITTED, 9))
        r = self.current(self.mp1, OCT25)
        self.assertEqual((r.total_outage_minutes, r.reporting_days, r.calendar_days, r.effective_from, r.technology), (1200.5, None, 31, OCT25, G4))
        self.assertAlmostEqual(r.availability_pct, 100 * frac(1200.5, OCT25), places=4)
        self.assertEqual((r.import_batch_id, r.source_row, r.source_batches, r.revision), (upload.pk, 3, [upload.pk], 1))
        nov = self.current(self.mp1, NOV25)
        self.assertEqual((nov.total_outage_minutes, nov.source_values['ff_count'], nov.source_values['bucket'], nov.source_values['om_start_flag']),
                         (0.0, 2.0, '>=98.5%', 'Yes'))  # a zero outage is a value

    def test_eligibility_never_rejects_a_value_and_is_noted_for_audit(self):
        self.run_import(self.workbook())
        notes = {(r.site.bsnl_site_id, r.month): r.source_values['on_air_note'] for r in MonthlySitePerformance.objects.filter(calculation_category=HIST)}
        self.assertEqual(notes[('UVMPBPL00020', OCT25)], 'no_on_air_date')
        self.assertEqual(notes[('UVRJJPR00001', OCT25)], 'before_on_air')
        self.assertEqual(notes[('UVRJJPR00001', MAR26)], 'on_air_during_month')
        self.assertEqual(notes[('UVMPBPL00012', OCT25)], 'on_air_whole_month')
        self.assertEqual(self.current(self.late, OCT25).total_outage_minutes, 0.0)

    def test_blank_cells_stay_missing(self):
        upload, _ = self.run_import(self.workbook([up_time_row('4G Satu.', 'MP', 'UVMPBPL00012', None, 10, None)]))
        self.assertEqual(upload.report['outcome'], {'blank': 2, 'new': 1})
        self.assertFalse(MonthlySitePerformance.objects.filter(month=OCT25).exists())

    def test_invalid_values_and_unknown_sites_are_rejected_or_held_never_imported(self):
        bad_uptime = up_time_row('4G Satu.', 'RJ', 'UVRJJPR00001', 100, 200, 300)
        bad_uptime[6] = 0.5  # Oct-25 Up-Time that does not match its outage
        rows = [up_time_row('4G Satu.', 'MP', 'UVMPBPL00012', 44640.6, -5, 300),  # over the month (held), negative (rejected)
                up_time_row('4G Satu.', 'MP', 'UVUNKNOWN0001', 10, 10, 10),       # not in the master
                up_time_row('4G Satu.', 'OD', 'UVMPBPL00020', 10, 10, 10),        # circle differs from the master
                bad_uptime]
        analysis = history.analyse(self.workbook(rows), history.UP_TIME_REPORT, {G4: [OCT25, NOV25, MAR26]})
        codes = sorted((i['site_id'], i['month'].isoformat(), i['code'], i['status']) for i in analysis['items'])
        self.assertIn(('UVMPBPL00012', '2025-10-01', 'over_month_minutes', 'held'), codes)
        self.assertIn(('UVMPBPL00012', '2025-11-01', 'negative_outage', 'rejected'), codes)
        self.assertIn(('UVRJJPR00001', '2025-10-01', 'uptime_inconsistent', 'held'), codes)
        self.assertEqual({c for s, _, c, _ in codes if s == 'UVUNKNOWN0001'}, {'unmatched_site'})
        self.assertEqual({c for s, _, c, _ in codes if s == 'UVMPBPL00020'}, {'circle_mismatch'})
        held = next(i for i in analysis['items'] if i['code'] == 'over_month_minutes')
        self.assertEqual((held['outage'], held['row'], held['source_file']), (44640.6, 3, 'consolidated.xlsx'))  # the original value and row
        self.assertTrue(held['action'])
        self.assertEqual(analysis['report']['ready'], 3)  # MP Mar-26, RJ Nov-25 and Mar-26

    def test_a_site_on_two_rows_is_refused_on_both(self):
        rows = [up_time_row('4G Satu.', 'MP', 'UVMPBPL00012', 10, 10, 10), up_time_row('4G Satu.', 'MP', 'UVMPBPL00012', 20, 20, 20)]
        analysis = history.analyse(self.workbook(rows), history.UP_TIME_REPORT, {G4: [OCT25]})
        self.assertEqual((analysis['report']['outcome'], analysis['report']['ready']), ({'duplicate_row': 2}, 0))

    def test_months_of_the_daily_data_layer_are_refused(self):
        analysis = history.analyse(self.workbook(), history.UP_TIME_REPORT, {G4: [SEP26]})
        self.assertEqual(analysis['report']['outcome'], {'daily_month': 3})

    def test_lwe_report_layout_and_mtd_months_are_held_until_confirmed(self):
        path = write_lwe(self.tmp / 'lwe.xlsx', [('Bihar', 'LWEBH0063', 1500, 2000)])
        allocation = {LWE: [date(2026, 1, 1), date(2026, 7, 1)]}
        analysis = history.analyse(path, history.LWE_MONTHLY, allocation)
        self.assertEqual(analysis['report']['outcome'], {'new': 1, 'mtd_unconfirmed': 1})
        self.assertEqual(analysis['report']['held_mtd_months'], ['LWE Jul-26'])
        _, done = self.run_import(path, allocation, history.LWE_MONTHLY, confirmed_full_months={(LWE, date(2026, 7, 1))})
        self.assertEqual(done.records_accepted, 2)
        jul = self.current(self.bh, date(2026, 7, 1))
        self.assertEqual((jul.total_outage_minutes, jul.source_values['column_label'], jul.source_values['circle_as_written']), (2000.0, "July'26 MTD", 'Bihar'))


class IdempotencyTests(HistoryTestCase):
    def test_an_unchanged_reimport_writes_nothing(self):
        self.run_import(self.workbook())
        again, done = self.run_import(self.workbook(name='again.xlsx'))
        self.assertEqual((again.report['outcome'], done.records_accepted), ({'unchanged': 9}, 0))
        self.assertEqual(MonthlySitePerformance.objects.filter(calculation_category=HIST).count(), 9)

    def test_a_changed_value_adds_a_revision_and_retiring_restores_the_earlier_one(self):
        self.run_import(self.workbook())
        rows = [up_time_row('4G Satu.', 'MP', 'UVMPBPL00012', 1300, 0.0, 300)]
        fix, done = self.run_import(self.workbook(rows, name='fix.xlsx'))
        self.assertEqual(fix.report['outcome'], {'changed': 1, 'unchanged': 2})
        rows_ = MonthlySitePerformance.objects.filter(site=self.mp1, month=OCT25, calculation_category=HIST).order_by('revision')
        self.assertEqual([(r.revision, r.is_current, r.total_outage_minutes) for r in rows_], [(1, False, 1200.5), (2, True, 1300.0)])
        self.assertEqual(history.retire(done, reason='Wrong file', user=self.admin), {'withdrawn': 1, 'restored': 1})
        self.assertEqual(self.current(self.mp1, OCT25).revision, 1)
        self.assertEqual(MonthlySitePerformance.objects.filter(site=self.mp1, month=OCT25).count(), 2)  # nothing deleted
        done.refresh_from_db()
        self.assertEqual((done.processing_status, done.report['retired']['reason']), (UploadBatch.Processing.RETIRED, 'Wrong file'))
        with self.assertRaises(history.HistoryError):
            history.retire(done, reason='again')

    def test_a_preview_cannot_be_committed_twice(self):
        upload, _ = self.run_import(self.workbook())
        with self.assertRaises(Exception):
            history.commit(upload)


class ConstraintTests(HistoryTestCase):
    def record(self, **fields):
        base = dict(site=self.mp1, month=OCT25, technology=G4, total_outage_minutes=0, availability_pct=100, calendar_days=31, effective_from=OCT25)
        return MonthlySitePerformance.objects.create(**{**base, **fields})

    def test_reporting_days_are_required_for_calculated_and_forbidden_for_historical_records(self):
        upload = make_batch(UploadBatch.Kind.UPTIME_HISTORY)
        for fields in ({'calculation_category': MonthlySitePerformance.Category.DAILY_DERIVED, 'reporting_days': None},
                       {'calculation_category': HIST, 'reporting_days': 31, 'import_batch': upload},
                       {'calculation_category': HIST, 'reporting_days': None}):  # no upload
            with self.subTest(fields=fields), self.assertRaises(IntegrityError), transaction.atomic():
                self.record(**fields)
        self.record(calculation_category=MonthlySitePerformance.Category.DAILY_DERIVED, reporting_days=31)
        self.record(calculation_category=HIST, reporting_days=None, import_batch=upload)  # both coexist for the month
        self.assertEqual(MonthlySitePerformance.objects.filter(site=self.mp1, month=OCT25, is_current=True).count(), 2)


class ProtectionTests(HistoryTestCase):
    """Historical records never reach the calculated results, the finalization, the daily-import checks or the dashboard."""

    def setUp(self):
        super().setUp()
        self.upload = make_batch(UploadBatch.Kind.UPTIME_HISTORY)
        # A historical record in a month of the daily data layer (the importer refuses it; written directly to prove the guards).
        self.hist_sep = MonthlySitePerformance.objects.create(site=self.mp1, month=SEP26, technology=G4, calculation_category=HIST,
                                                             total_outage_minutes=999, availability_pct=97.7, reporting_days=None, calendar_days=30,
                                                             effective_from=SEP26, import_batch=self.upload)
        for day in range(1, 4):
            make_daily(self.mp1, date(2026, 9, day), 30)

    def test_calculate_month_manages_only_its_own_categories(self):
        summary = calculations.calculate_month(SEP26)
        self.assertEqual(summary['created'], 2)  # daily_derived and on_air for the one site with daily records
        derived = MonthlySitePerformance.objects.get(site=self.mp1, month=SEP26, calculation_category=MonthlySitePerformance.Category.DAILY_DERIVED)
        self.assertEqual((derived.total_outage_minutes, derived.reporting_days), (90, 3))
        self.hist_sep.refresh_from_db()
        self.assertEqual((self.hist_sep.is_current, self.hist_sep.total_outage_minutes, self.hist_sep.revision), (True, 999, 1))
        self.assertEqual(calculations.calculate_month(SEP26)['unchanged'], 2)  # recalculating leaves both alone

    def test_finalization_never_marks_historical_records_and_they_never_block_daily_imports(self):
        calculations.calculate_month(SEP26)
        n = calculations.finalize_month(SEP26, user=self.admin)
        self.assertEqual(n, 2)
        self.hist_sep.refresh_from_db()
        self.assertIsNone(self.hist_sep.finalized_at)
        MonthlySitePerformance.objects.filter(calculation_category=MonthlySitePerformance.Category.DAILY_DERIVED).update(finalized_at=None)
        MonthlySitePerformance.objects.filter(calculation_category=MonthlySitePerformance.Category.ON_AIR).update(finalized_at=None)
        MonthlySitePerformance.objects.filter(pk=self.hist_sep.pk).update(finalized_at=timezone.now())  # even if marked
        self.assertEqual(daily.finalized_months([date(2026, 9, 5)]), [])

    def test_the_monthly_results_list_and_the_dashboard_ignore_historical_months(self):
        MonthlySitePerformance.objects.create(site=self.mp1, month=OCT25, technology=G4, calculation_category=HIST, total_outage_minutes=10,
                                              availability_pct=99.9, reporting_days=None, calendar_days=31, effective_from=OCT25, import_batch=self.upload)
        calculations.calculate_month(SEP26)
        self.client.force_login(self.admin)
        months = [m['month'] for m in self.client.get(reverse('sitedata-months')).json()['months']]
        self.assertEqual(months, ['2026-09-01'])
        make_daily(self.mp1, date(2026, 10, 1), 0)
        ds = dataset.build()
        self.assertEqual([m['label'] for m in ds.months], ['Sep-26'])  # Oct-25 (historical only) is not a dashboard month
        self.assertEqual(float(ds.monthly_outage[list(ds.sites['site_id']).index('UVMPBPL00012'), 0]), 90.0)  # the calculated value


class CrossCheckTests(HistoryTestCase):
    def test_another_source_of_the_same_months_is_compared_not_imported(self):
        primary = self.workbook()
        other = write_up_time(self.tmp / 'g4.xlsx', [up_time_row('4G Satu.', 'MP', 'UVMPBPL00012', 1200.5, 7.0, 300)])
        analysis = history.analyse(primary, history.UP_TIME_REPORT, {G4: [OCT25, NOV25]},
                                   cross_checks=[(other, history.UP_TIME_REPORT, {G4: [OCT25, NOV25]})])
        self.assertEqual(analysis['report']['cross_checks'][0]['months'], {'4G Saturation Nov-25': {'different': 1}, '4G Saturation Oct-25': {'equal': 1}})
        self.assertFalse(MonthlySitePerformance.objects.filter(calculation_category=HIST).exists())
