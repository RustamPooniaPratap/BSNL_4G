"""New site master and performance data layer (apps.sitedata, Phase 1): importers, rules, constraints, calculations and
the dashboard dataset. Every file is synthetic and generated here; the test database only."""
import csv
import io
import tempfile
from datetime import date, datetime
from pathlib import Path
from unittest import mock

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from openpyxl import Workbook

from apps.sitedata import bandmap, calculations, daily, dataset, matrix, rawcsv, rules, uploads, uptime_master
from apps.sitedata.models import (DailyPerformanceEvent, DailySitePerformance, IdentifierConflict, LweMappingIdentifier, LweMappingRow,
                                  MonthlySitePerformance, Site, SiteIdentifier, UploadBatch)
from tests.auth_helpers import SignedInTestCase, portal_user
from tests.workbook_factory import write_workbook

G4, LWE = '4G Saturation', 'LWE'
MATRIX_HEADER = ['Entity', 'Circle Name', 'BSNL Site ID', 'Site Name/Village Name', 'BA', 'OA', 'District', 'O&M Start Date',
                 'Site On Air Status', 'Site On Air Date', 'IE Name', 'CI Name', 'BTS Site ID_B1(21MHz)', 'BTS Site ID_B28(7MHz)']
MATRIX = [
    ['4G Saturation', 'Madhya Pradesh', 'UVMP001', 'Alpha', 'BHOPAL', 'SEHORE', 'Sehore', datetime(2025, 10, 1), 'Yes', datetime(2024, 7, 1), 'IE One', 'CI East', 'T4MP01A', 'T4MP28A'],
    ['4G Saturation', 'Madhya Pradesh', 'UVMP002', 'Bravo', 'BHOPAL', 'SEHORE', 'Sehore', None, 'Yes', None, 'IE One', 'CI East', '', ''],
    ['4G Saturation', 'Rajasthan', 'UVRJ001', 'Delta', 'AJMER', 'AJMER', 'Ajmer', None, '', None, 'IE RJ', 'CI RJ', '', ''],
    ['LWE', 'Madhya Pradesh', 'LWEMP01', 'Echo', 'BALAGHAT', 'BALAGHAT', 'Balaghat', None, 'Yes', None, 'IE LWE', 'CI LWE', '', ''],
    ['LWE', 'Odisha', 'LWEOD01', 'Foxtrot', 'KORAPUT', 'KORAPUT', 'Koraput', None, 'Yes', None, 'IE OD', 'CI OD', '', ''],
    ['VI-HPSC', 'Delhi-NCR', 'VIDL001', 'Hotel', 'D', 'D', 'D', None, 'Yes', None, '', '', '', ''],
    ['Sterlite', 'Madhya Pradesh', 'STMP001', 'India', 'D', 'D', 'D', None, 'Yes', None, '', '', '', ''],
]
BAND_HEADER = ['Circle', 'BTS IP ID', 'BTS Site ID (2100)', 'BTS Site ID (700)', 'btsIpId -Master ID']
BAND = [
    ['MP', 'MPBLG001', 'T4MP01BLG001lw', 'T4MP28BLG001lw', 'LWEMP01'],
    ['OD', 'ORKRP001', '', 'T4OD28KRP001lw', 'LWEOD01'],
]
CSV_HEADER = ['SrNo', 'BTS IP ID', 'BTS Name', 'Circle', 'BTS Site ID (2100)', 'BTS Site ID (700)', 'Nw Avail (4G)', 'Nw Avail (4G TCS)', 'Report Date']


def write_sheet(path: Path, header, rows, title='Raw Data', preamble=True) -> Path:
    book = Workbook()
    sheet = book.active
    sheet.title = title
    if preamble:
        sheet.append(['Consolidated Escalation Matrix'])
    sheet.append(header)
    for r in rows:
        sheet.append(r)
    book.save(path)
    return path


def write_csv(path: Path, rows) -> Path:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator='\r\n')
    writer.writerow(CSV_HEADER)
    for i, (site, b2100, b700, tcs, circle, day) in enumerate(rows, start=1):
        writer.writerow([i, site, 'Site', circle, b2100, b700, '', tcs, day])
    path.write_text(out.getvalue(), encoding='utf-8')
    return path


class SiteDataTestCase(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        override = override_settings(SITEDATA_STAGING_DIR=str(self.tmp / 'staged'), SITEDATA_EXCEPTION_DIR=str(self.tmp / 'exceptions'))
        override.enable()
        self.addCleanup(override.disable)
        self.admin = portal_user('sitedata-admin', 'admin')

    def load_matrix(self, rows=MATRIX, name='matrix.xlsx'):
        batch = matrix.preview(write_sheet(self.tmp / name, MATRIX_HEADER, rows), name, user=self.admin)
        self.assertNotEqual(batch.validation_status, UploadBatch.Validation.FAILED, batch.report)
        return matrix.commit(batch, user=self.admin)

    def load_bands(self, rows=BAND):
        batch = bandmap.preview(write_sheet(self.tmp / 'band.xlsx', BAND_HEADER, rows, title='Sheet1', preamble=False), 'LWE Band ID.xlsx', user=self.admin)
        return batch

    def load_uptime(self, sites=None, name='uptime.xlsx'):
        batch = uptime_master.preview(write_workbook(self.tmp / name, sites), name, user=self.admin)
        self.assertNotEqual(batch.validation_status, UploadBatch.Validation.FAILED, batch.report)
        return uptime_master.commit(batch, user=self.admin)

    def raw(self, technology, circle, day, rows, *, commit=True):
        batch = rawcsv.preview(write_csv(self.tmp / f'{technology}-{circle}.csv', rows), 'day.csv', technology=technology, circle=circle,
                               reporting_date=day, user=self.admin)
        return rawcsv.commit(batch, user=self.admin) if commit else batch


class MatrixTests(SiteDataTestCase):
    def test_one_site_per_bsnl_site_id_with_scope_and_identifiers(self):
        batch = self.load_matrix()
        self.assertEqual(Site.objects.count(), 7)
        alpha = Site.objects.get(site_key='UVMP001')
        self.assertEqual((alpha.technology, alpha.circle, alpha.oa, alpha.district, alpha.om_start_date, alpha.on_air), (G4, 'MP', 'SEHORE', 'Sehore', date(2025, 10, 1), True))
        self.assertFalse(Site.objects.get(site_key='UVRJ001').on_air)  # matrix On-Air status blank
        outside = Site.objects.filter(reporting_scope=Site.Scope.OUTSIDE)
        self.assertEqual(sorted(outside.values_list('entity', 'technology')), [('Sterlite', ''), ('VI-HPSC', '')])
        kinds = set(alpha.identifiers.values_list('kind', 'key'))
        self.assertEqual(kinds, {('bsnl_site_id', 'UVMP001'), ('band_2100', 'T4MP01A'), ('band_700', 'T4MP28A')})
        self.assertEqual((batch.records_received, batch.records_accepted, batch.processing_status), (7, 7, 'committed'))

    def test_a_new_matrix_updates_attributes_and_flags_missing_sites_without_deleting(self):
        self.load_matrix()
        changed = [r[:] for r in MATRIX if r[2] != 'UVMP002']
        changed[0][5] = 'NEW OA'
        batch = self.load_matrix(changed, 'matrix2.xlsx')
        self.assertEqual(batch.report['sites'], {'inserted': 0, 'updated': 1, 'unchanged': 5, 'no_longer_in_matrix': 1})
        self.assertEqual(Site.objects.get(site_key='UVMP001').oa, 'NEW OA')
        gone = Site.objects.get(site_key='UVMP002')  # still there, flagged
        self.assertFalse(gone.present_in_latest_matrix)
        self.assertEqual(Site.objects.count(), 7)

    def test_an_id_under_two_entities_is_rejected_not_guessed(self):
        rows = MATRIX + [['LWE', 'Madhya Pradesh', 'uvmp001', 'Twin', 'X', 'X', 'X', None, 'Yes', None, '', '', '', '']]
        batch = matrix.preview(write_sheet(self.tmp / 'm.xlsx', MATRIX_HEADER, rows), 'm.xlsx')
        self.assertEqual(batch.records_rejected, 2)
        matrix.commit(batch)
        self.assertFalse(Site.objects.filter(site_key='UVMP001').exists())


class ConstraintTests(SiteDataTestCase):
    def test_database_constraints(self):
        self.load_matrix()
        site = Site.objects.get(site_key='UVMP001')
        batch = UploadBatch.objects.create(kind=UploadBatch.Kind.CORRECTION, original_filename='x')
        DailySitePerformance.objects.create(site=site, report_date=date(2026, 10, 1), technology=G4, circle='MP', availability_pct=100, outage_minutes=0, batch=batch)
        for values in ({'availability_pct': 100, 'outage_minutes': 0},  # duplicate site, date, technology
                       {'report_date': date(2026, 10, 2), 'availability_pct': 101, 'outage_minutes': 0},
                       {'report_date': date(2026, 10, 3), 'availability_pct': 50, 'outage_minutes': 1500}):
            with self.subTest(values=values), self.assertRaises(IntegrityError), transaction.atomic():
                DailySitePerformance.objects.create(site=site, technology=G4, circle='MP', batch=batch, **{'report_date': date(2026, 10, 1), **values})
        with self.assertRaises(IntegrityError), transaction.atomic():
            SiteIdentifier.objects.create(site=Site.objects.get(site_key='UVMP002'), kind='band_2100', key='T4MP01A', value='T4MP01A', batch=batch)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Site.objects.filter(pk=site.pk).update(reporting_scope=Site.Scope.OUTSIDE)  # outside scope needs a blank technology


class UptimeMasterTests(SiteDataTestCase):
    def test_daily_values_flags_and_no_overwrite_of_matrix_attributes(self):
        self.load_matrix()
        batch = self.load_uptime()
        # Factory sites: UVMP001 / 002 / 003, UVRJ001, LWEMP01, LWEOD01, LWEBH01 with outage for 1-3 Oct.
        self.assertEqual(sorted(batch.report['sites_not_in_site_master']), ['LWEBH01', 'UVMP003'])
        alpha = Site.objects.get(site_key='UVMP001')
        self.assertEqual(alpha.oa, 'SEHORE')  # matrix value kept
        self.assertIn('oa', batch.report['matrix_attribute_differences'])
        rec = DailySitePerformance.objects.get(site=alpha, report_date=date(2026, 10, 2))
        self.assertEqual((rec.outage_minutes, round(rec.availability_pct, 6), rec.batch_id), (144, 90.0, batch.pk))
        # LWEOD01's 3 Oct cell is blank: no record, never 0.
        self.assertFalse(DailySitePerformance.objects.filter(site__site_key='LWEOD01', report_date=date(2026, 10, 3)).exists())
        # O&M Start flags of the workbook are compared with the matrix date, never stored or used: UVRJ001, LWEMP01 and
        # LWEOD01 say "Yes" but have no matrix O&M Start Date.
        self.assertEqual(batch.report['om_start_flags_differing_from_matrix'], 3)
        self.assertIsNone(Site.objects.get(site_key='UVRJ001').om_start_date)

    def test_re_import_is_idempotent_and_a_different_value_is_a_logged_conflict(self):
        self.load_matrix()
        first = self.load_uptime()
        n = DailySitePerformance.objects.count()
        again = self.load_uptime(name='again.xlsx')
        self.assertEqual((again.records_accepted, again.records_duplicate, again.records_conflict), (0, n, 0))
        sites = [('4G Satu.', 'MP', 'UVMP001', 'Alpha', 'Yes', 'Yes', [0, 288, 1440])]  # 2 Oct differs
        changed = self.load_uptime(sites, name='changed.xlsx')
        self.assertEqual(changed.records_conflict, 1)
        rec = DailySitePerformance.objects.get(site__site_key='UVMP001', report_date=date(2026, 10, 2))
        self.assertEqual((rec.outage_minutes, rec.batch_id), (144, first.pk))  # first accepted value wins
        event = DailyPerformanceEvent.objects.get()
        self.assertEqual((event.action, event.proposed_outage_minutes, event.stored_outage_minutes, event.batch_id, event.stored_batch_id),
                         ('conflict', 288, 144, changed.pk, first.pk))

    @override_settings(SITEDATA_MASTER_DAILY_MONTHS=('2026-09',))
    def test_only_months_in_scope_are_imported(self):
        self.load_matrix()
        batch = self.load_uptime()
        self.assertEqual((batch.records_received, DailySitePerformance.objects.count()), (0, 0))


class BandMappingTests(SiteDataTestCase):
    def test_accepted_rows_and_every_rejection_reason(self):
        self.load_matrix()
        rows = BAND + [
            ['MP', 'MPDUP001', 'T4MP01BLG001lw', '', 'LWEMP01'],  # Master ID repeated with other IDs -> both rows rejected
            ['MP', 'MPX001', '', '', 'LWEXX99'],                  # not in the site master
            ['MP', 'MPX002', '', '', 'UVMP001'],                  # a 4G site
            ['RJ', 'ORKRP001', '', 'T4OD28KRP001lw', 'LWEOD01'],  # circle differs; LWEOD01 is now on two rows
            ['MP', 'MPBLG001', 'MPBLG001', 'MPBLG001', 'MPBLG001'],  # identical repeat of the row below: one duplicate
            ['MP', 'MPBLG001', 'MPBLG001', 'MPBLG001', 'MPBLG001'],
        ]
        batch = self.load_bands(rows)
        self.assertEqual(batch.report['rejected_by_reason'],
                         {'duplicate_master_id': 3, 'unknown_master_id': 2, 'not_lwe_site': 1, 'circle_mismatch': 1})
        self.assertEqual((batch.records_received, batch.records_duplicate), (8, 1))
        bandmap.commit(batch)
        self.assertEqual(SiteIdentifier.objects.filter(batch=batch).count(), 0)  # no row was unambiguous
        clean = bandmap.commit(self.load_bands())
        od = Site.objects.get(site_key='LWEOD01')
        self.assertEqual(set(od.identifiers.filter(batch=clean).values_list('kind', 'key')), {('bts_ip_id', 'ORKRP001'), ('band_700', 'T4OD28KRP001LW')})

    def test_an_identifier_of_two_master_ids_is_rejected_on_both_rows(self):
        self.load_matrix()
        batch = self.load_bands([BAND[0], ['OD', 'MPBLG001', '', '', 'LWEOD01']])
        self.assertEqual(batch.report['rejected_by_reason'], {'duplicate_identifier': 2})

    def test_an_identifier_already_naming_another_site_is_not_moved(self):
        self.load_matrix()
        bandmap.commit(self.load_bands())
        batch = self.load_bands([['OD', 'MPBLG001', '', '', 'LWEOD01']])
        self.assertEqual(batch.report['rejected_by_reason'], {'identifier_assigned_elsewhere': 1})


class RawCsvTests(SiteDataTestCase):
    def setUp(self):
        super().setUp()
        self.load_matrix()
        bandmap.commit(self.load_bands())

    def test_lwe_identifiers_must_all_resolve_to_the_same_site(self):
        day = date(2026, 11, 1)
        batch = self.raw(LWE, 'MP', day, [
            ('MPBLG001', 'T4MP01BLG001lw', 'T4MP28BLG001lw', '99.5', 'MP', '01-11-2026'),  # all three IDs -> LWEMP01
            ('MPBLG001', '', 'T4MP28BLG001lw', '99.5', 'MP', '01-11-2026'),               # same site, same value: duplicate
            ('UVMP001', '', '', '100', 'MP', '01-11-2026'),                                # a 4G row: skipped
        ])
        self.assertEqual((batch.records_accepted, batch.records_duplicate, batch.records_rejected), (1, 1, 0))
        self.assertEqual(batch.report['skipped'], {'other_technology': 1})
        rec = DailySitePerformance.objects.get()
        self.assertEqual((rec.site.site_key, rec.technology, round(rec.outage_minutes, 6)), ('LWEMP01', LWE, 7.2))

    def test_lwe_rows_with_unmapped_or_mismatched_identifiers_are_rejected(self):
        batch = self.raw(LWE, 'MP', date(2026, 11, 1), [
            ('MPBLG001', 'T4OTHER01', '', '99', 'MP', '01-11-2026'),        # 2100 ID not in the mapping
            ('MPBLG001', '', 'T4OD28KRP001lw', '99', 'MP', '01-11-2026'),   # 700 ID of another site
            ('MPNEW999', '', '', '99', 'MP', '01-11-2026'),                 # unknown everywhere: unmatched
        ], commit=False)
        self.assertEqual(batch.report['rejected_by_reason'], {'identifier_not_in_mapping': 1, 'identifier_mismatch': 1})
        self.assertEqual(batch.records_unmatched, 1)

    def test_conflicting_rows_of_one_site_are_all_rejected(self):
        batch = self.raw(LWE, 'MP', date(2026, 11, 1), [
            ('MPBLG001', '', '', '99', 'MP', '01-11-2026'), ('', 'T4MP01BLG001lw', '', '98', 'MP', '01-11-2026')], commit=False)
        self.assertEqual(batch.report['rejected_by_reason'], {'conflicting_rows': 2})  # the 2100 ID alone names LWEMP01 too
        batch = self.raw(LWE, 'MP', date(2026, 11, 1), [
            ('MPBLG001', '', '', '99', 'MP', '01-11-2026'), ('MPBLG001', 'T4MP01BLG001lw', '', '98', 'MP', '01-11-2026')], commit=False)
        self.assertEqual(batch.report['rejected_by_reason'], {'conflicting_rows': 2})

    def test_4g_rows_dates_circles_and_blank_availability(self):
        batch = self.raw(G4, 'MP', date(2026, 11, 1), [
            ('UVMP001', '', '', '97.5', 'MP', '01-11-2026'),
            ('UVMP002', '', '', '', 'MP', '01-11-2026'),        # blank: not reported, never 0
            ('UVMP002', '', '', '90', 'MP', '02-11-2026'),      # another date
            ('UVRJ001', '', '', '90', 'RJ', '01-11-2026'),      # another circle
            ('MPBLG001', '', '', '90', 'MP', '01-11-2026'),     # an LWE row
        ])
        self.assertEqual(batch.report['rejected_by_reason'], {'other_report_date': 1, 'other_circle': 1})
        self.assertEqual(batch.report['skipped'], {'other_technology': 1, 'not_reported': 1})
        self.assertEqual(list(DailySitePerformance.objects.values_list('site__site_key', 'availability_pct')), [('UVMP001', 97.5)])

    def test_lwe_availability_is_nw_avail_4g_tcs_as_a_percentage_with_the_4g_rules(self):
        rows = lambda site, avail: [(site, '', '', avail, 'MP', '01-11-2026')]  # noqa: E731
        for technology, site in ((LWE, 'MPBLG001'), (G4, 'UVMP001')):
            with self.subTest(technology=technology):
                for value, code in (('100.5', 'availability_out_of_range'), ('-1', 'availability_out_of_range'), ('abc', 'invalid_availability')):
                    batch = self.raw(technology, 'MP', date(2026, 11, 1), rows(site, value), commit=False)
                    self.assertEqual(batch.report['rejected_by_reason'], {code: 1})
                batch = self.raw(technology, 'MP', date(2026, 11, 1), rows(site, ''), commit=False)
                self.assertEqual((batch.report['skipped'], batch.records_rejected), ({'not_reported': 1}, 0))  # blank: not reported
                self.raw(technology, 'MP', date(2026, 11, 1), rows(site, '98.50'))
        records = {r.site.site_key: r for r in DailySitePerformance.objects.select_related('site')}
        for key in ('LWEMP01', 'UVMP001'):  # 98.50 is 98.50%, not a fraction; same rule for both
            self.assertEqual(records[key].availability_pct, 98.5)
            self.assertAlmostEqual(records[key].outage_minutes, 1440 * (1 - 98.5 / 100))


class CorrectionTests(SiteDataTestCase):
    def test_only_admins_correct_and_every_correction_is_logged(self):
        self.load_matrix()
        self.load_uptime()
        rec = DailySitePerformance.objects.get(site__site_key='UVMP001', report_date=date(2026, 10, 2))
        with self.assertRaises(PermissionDenied):
            daily.correct(rec, 95, user=portal_user('ci-user', 'ci'), reason='x')
        with self.assertRaises(ValueError):
            daily.correct(rec, 95, user=self.admin, reason=' ')
        rec = daily.correct(rec, 95, user=self.admin, reason='CNMC re-run')
        self.assertEqual((rec.revision, round(rec.outage_minutes, 6), rec.batch.kind), (2, 72.0, 'correction'))
        event = DailyPerformanceEvent.objects.get(action='correction')
        self.assertEqual((event.stored_outage_minutes, event.proposed_availability_pct, event.user, event.reason), (144, 95, self.admin, 'CNMC re-run'))
        with self.assertRaises(PermissionDenied):
            event.save()
        with self.assertRaises(PermissionDenied):
            DailyPerformanceEvent.objects.all().delete()


class MonthlyTests(SiteDataTestCase):
    def test_outage_weighted_over_reported_days_with_revisions_and_finalization(self):
        self.load_matrix()
        self.load_uptime()
        october = date(2026, 10, 1)
        summary = calculations.calculate_month(october)
        self.assertEqual((summary['created'], summary['om_start_sites'], summary['on_air_sites'], summary['om_start_date_review_sites']), (7, 1, 1, 4))  # 5 all-days + O&M + On-Air (UVMP001)
        od = MonthlySitePerformance.objects.get(site__site_key='LWEOD01', month=october)
        self.assertEqual((od.reporting_days, od.calendar_days, od.total_outage_minutes), (2, 31, 720))  # 3 Oct missing, not 0
        self.assertAlmostEqual(od.availability_pct, 100 * (1 - 720 / (1440 * 2)))
        self.assertEqual(calculations.calculate_month(october)['unchanged'], 7)
        rec = DailySitePerformance.objects.get(site__site_key='LWEOD01', report_date=date(2026, 10, 2))
        daily.correct(rec, 100, user=self.admin, reason='test')
        self.assertEqual(calculations.calculate_month(october)['revised'], 1)
        self.assertEqual(list(MonthlySitePerformance.objects.filter(site__site_key='LWEOD01', calculation_category='daily_derived').order_by('revision').values_list('revision', 'is_current')),
                         [(1, False), (2, True)])
        calculations.finalize_month(october, user=self.admin)
        with self.assertRaises(calculations.MonthFinalized):
            calculations.calculate_month(october)


class DashboardFromNewLayerTests(SignedInTestCase, SiteDataTestCase):
    """The existing dashboard, Team Performance and All KPI's endpoints run on a dataset built from the new tables."""

    def setUp(self):
        super().setUp()
        self.load_matrix()
        self.load_uptime()
        calculations.calculate_month(date(2026, 10, 1))
        from apps.uptimedb import datasource
        patch = mock.patch.object(datasource, 'current_dataset', dataset.build)
        patch.start()
        self.addCleanup(patch.stop)

    def test_dataset_scope_and_flags(self):
        ds = dataset.build()
        self.assertEqual(sorted(ds.sites['site_id']), ['LWEMP01', 'LWEOD01', 'UVMP001', 'UVMP002', 'UVRJ001'])  # no outside-scope sites
        self.assertEqual(ds.month_label, 'Oct-26')
        # From the matrix O&M Start Date only: UVMP001 (1 Oct 2025); the others have no date.
        self.assertEqual(dict(zip(ds.sites['site_id'], ds.sites['om_start'])),
                         {'LWEMP01': False, 'LWEOD01': False, 'UVMP001': True, 'UVMP002': False, 'UVRJ001': False})

    def test_existing_endpoints_are_populated(self):
        for name, params in (('dashboard-summary', {'date': '2026-10-03'}), ('dashboard-teams', {'date': '2026-10-03'}),
                             ('allkpis-summary', {'date_from': '2026-10-01', 'date_to': '2026-10-03'})):
            with self.subTest(name=name):
                response = self.client.get(reverse(name), params)
                self.assertEqual(response.status_code, 200, response.content[:300])
        kpis = self.client.get(reverse('allkpis-summary'), {'date_from': '2026-10-01', 'date_to': '2026-10-03'}).json()['current']
        self.assertEqual(kpis['total_sites'], 5)


SEP3 = [date(2026, 9, d) for d in (1, 2, 3)]


def _dt(d):
    return datetime(d.year, d.month, d.day)


def _fraction(v):
    return 1 - v / 1440 if isinstance(v, (int, float)) else None


def up_time_report_without_project(path: Path, rows, *, headers=None) -> Path:
    """The "RJ, MP & OD - Uptime Report" layout: totals row, header row without Project, Sep daily outage, weekly columns,
    then the same dates as uptime fractions. rows: (circle, btsIpId, O&M Start - Sep-26, [outage per date])."""
    book = Workbook()
    sheet = book.active
    sheet.title = 'Up-Time Report'
    header = headers or ['Circle', 'btsIpId', 'Site name', 'OA', 'BA', 'On-Air', 'EB', 'O&M Start - Sep-26', 'IE Name', 'CI Name',
                         'Aug-26 Outage Min.', *[_dt(d) for d in SEP3], 'Wk-1', *[_dt(d) for d in SEP3]]
    sheet.append([7] * len(header))
    sheet.append(header)
    for circle, site_id, om, outage in rows:
        sheet.append([circle, site_id, 'Name', 'OA-1', 'BA-1', 'Yes', 'EB', om, 'IE', 'CI', 100, *outage, None, *[_fraction(v) for v in outage]])
    book.create_sheet('Summ')
    book.save(path)
    return path


def day_wise_outage(path: Path, rows, *, id_header='Site ID as per Nirikshan', sheet_name='Day Wise Outage') -> Path:
    """The "LWE Uptime Report day wise" layout: totals row; Circle (state name), Site Category, a serial Site ID, the
    Nirikshan site ID, a month-less O&M Start, a monthly snapshot block, Sep daily outage, weekly columns, uptime fractions.
    rows: (circle, Nirikshan site ID, [outage per date])."""
    book = Workbook()
    sheet = book.active
    sheet.title = sheet_name
    header = ['Circle', 'Site Category', 'Site ID', id_header, 'O&M Start', 'O&M Start Date', 'On-Air', 'BA', 'OA', 'IE', 'CI',
              'Name of District', 'Site Name', 'Outage Min', "Sept'26 MTD", '<60% Sites', 'No. of days', *[_dt(d) for d in SEP3],
              'Wk-40 Outage Min.', 'Wk-40 Uptime', 'Bucket', *[_dt(d) for d in SEP3]]
    sheet.append([None, None, None, 2182, 2150])
    sheet.append(header)
    for serial, (circle, site_id, outage) in enumerate(rows, start=348):
        sheet.append([circle, 'LWE', serial, site_id, 'Yes', datetime(2026, 2, 1), 'Yes', 'BA', 'OA', 'IE', 'CI', 'District', 'Name',
                      100, 0.99, None, 3, *outage, 0, 0.99, '>98.5', *[_fraction(v) for v in outage]])
    book.create_sheet('Circle Wise Summary')
    book.save(path)
    return path


def assert_balanced(test, batch):
    """received = accepted + duplicate + conflict + rejected + unmatched (site-days)."""
    test.assertEqual(batch.records_received, batch.records_accepted + batch.records_duplicate + batch.records_conflict
                     + batch.records_superseded + batch.records_rejected + batch.records_unmatched, batch.report.get('counts'))


@override_settings(SITEDATA_MASTER_DAILY_MONTHS=('2026-09', '2026-10'))
class UpTimeReportWithoutProjectTests(SiteDataTestCase):
    def setUp(self):
        super().setUp()
        self.load_matrix()

    def preview(self, rows, project=G4, **kwargs):
        path = up_time_report_without_project(self.tmp / 'rj_mp_od.xlsx', rows, **kwargs)
        return uptime_master.preview(path, 'RJ, MP & OD - Uptime Report- Sep-26.xlsx', project=project, user=self.admin)

    def test_the_project_must_be_stated_never_assumed(self):
        batch = self.preview([('MP', 'UVMP001', 'Yes', [0, 0, 0])], project=None)
        self.assertEqual(batch.validation_status, UploadBatch.Validation.FAILED)
        self.assertIn('State the project', batch.error)

    def test_values_flags_and_every_rejection_reason(self):
        batch = self.preview([
            ('MP', 'UVMP001', 'Yes', [0, 144, None]),        # 2 values, 1 blank (not reported)
            ('MP', 'UVMP002', 'No', ['abc', 2000, 720]),     # text, out of range, 1 value
            ('RJ', 'UVRJ001', 'Yes', [10, 10, 10]),          # on two rows: all rejected
            ('RJ', 'UVRJ001', 'Yes', [10, 10, 10]),
            ('MP', 'LWEMP01', 'Yes', [0, 0, 0]),             # an LWE site in a 4G file
            ('MP', 'UVMP999', 'Yes', [5, 5, 5]),             # not in the site master
            (None, 'UVMP003', 'Yes', [1, 1, 1]),             # no circle
        ])
        self.assertEqual(batch.report['format'], 'up_time_report')
        self.assertEqual(batch.report['rejected_rows_by_reason'], {'missing_circle': 1, 'duplicate_key': 1, 'duplicate_site': 1, 'technology_mismatch': 1})
        self.assertEqual(batch.report['rejected_site_days_by_reason'],
                         {'missing_circle': 0, 'duplicate_key': 0, 'duplicate_site': 3, 'technology_mismatch': 3, 'invalid_value': 1, 'outage_out_of_range': 1})
        self.assertEqual((batch.records_accepted, batch.records_unmatched, batch.report['not_reported_site_days']), (3, 3, 1))
        assert_balanced(self, batch)
        uptime_master.commit(batch, user=self.admin)
        self.assertEqual(sorted(DailySitePerformance.objects.values_list('site__site_key', 'report_date', 'outage_minutes')),
                         [('UVMP001', date(2026, 9, 1), 0.0), ('UVMP001', date(2026, 9, 2), 144.0), ('UVMP002', date(2026, 9, 3), 720.0)])
        self.assertEqual(batch.report['om_start_flags_differing_from_matrix'], 0)  # compared only: UVMP001 Yes (date 2025), UVMP002 No (no date)
        self.assertIsNone(Site.objects.get(site_key='UVMP002').om_start_date)

    def test_stated_as_the_wrong_project_every_site_is_rejected(self):
        batch = self.preview([('MP', 'UVMP001', 'Yes', [0, 0, 0])], project=LWE)
        self.assertEqual(batch.report['rejected_rows_by_reason'], {'technology_mismatch': 1})
        self.assertEqual(batch.records_accepted, 0)

    def test_first_accepted_value_wins_across_files(self):
        uptime_master.commit(self.preview([('MP', 'UVMP001', 'Yes', [0, 0, 0])]), user=self.admin)
        again = self.preview([('MP', 'UVMP001', 'Yes', [0, 60, 0])])
        self.assertEqual((again.records_duplicate, again.records_conflict), (2, 1))
        uptime_master.commit(again, user=self.admin)
        self.assertEqual(DailySitePerformance.objects.get(site__site_key='UVMP001', report_date=date(2026, 9, 2)).outage_minutes, 0)
        self.assertEqual(DailyPerformanceEvent.objects.get().proposed_outage_minutes, 60)

    def test_a_missing_id_column_is_refused(self):
        headers = ['Circle', 'Site name', 'OA', *[_dt(d) for d in SEP3]]
        batch = self.preview([('MP', 'UVMP001', 'Yes', [0, 0, 0])], headers=headers)
        self.assertEqual(batch.validation_status, UploadBatch.Validation.FAILED)


@override_settings(SITEDATA_MASTER_DAILY_MONTHS=('2026-09', '2026-10'))
class DayWiseOutageTests(SiteDataTestCase):
    def setUp(self):
        super().setUp()
        self.load_matrix()

    def preview(self, rows, project=LWE, **kwargs):
        path = day_wise_outage(self.tmp / 'lwe_daywise.xlsx', rows, **kwargs)
        return uptime_master.preview(path, "LWE Uptime Report day wise - Sept'26.xlsx", project=project, user=self.admin)

    def test_the_project_must_be_stated(self):
        batch = self.preview([('Madhya Pradesh', 'LWEMP01', [0, 0, 0])], project=None)
        self.assertEqual(batch.validation_status, UploadBatch.Validation.FAILED)
        self.assertIn('State the project', batch.error)

    def test_values_by_nirikshan_id_and_state_name_circles(self):
        batch = self.preview([
            ('Madhya Pradesh', 'LWEMP01', [0, 144, None]),
            ('Odisha', 'LWEOD01', ['x', 1500, 288]),
            ('Madhya Pradesh', 'LWEMP77', [1, 1, 1]),   # not in the site master
            ('Madhya Pradesh', '', [1, 1, 1]),          # no site ID
            ('Atlantis', 'UVMP001', [1, 1, 1]),         # unknown circle
        ])
        self.assertEqual(batch.report['format'], 'day_wise_outage')
        self.assertEqual(batch.report['rejected_rows_by_reason'], {'missing_site_id': 1, 'unknown_circle': 1})
        self.assertEqual(batch.report['rejected_site_days_by_reason'], {'missing_site_id': 3, 'unknown_circle': 3, 'invalid_value': 1, 'outage_out_of_range': 1})
        self.assertEqual((batch.records_accepted, batch.records_unmatched, batch.report['not_reported_site_days']), (3, 3, 1))
        self.assertIn('no month in its header', ' '.join(batch.report['notes']))
        assert_balanced(self, batch)
        uptime_master.commit(batch, user=self.admin)
        self.assertEqual(sorted(DailySitePerformance.objects.values_list('site__site_key', 'report_date', 'outage_minutes')),
                         [('LWEMP01', date(2026, 9, 1), 0.0), ('LWEMP01', date(2026, 9, 2), 144.0), ('LWEOD01', date(2026, 9, 3), 288.0)])
        self.assertIn('not used', ' '.join(batch.report['notes']))  # the undated O&M Start column

    def test_repeated_rows_identical_are_duplicates_different_are_all_rejected(self):
        batch = self.preview([
            ('Madhya Pradesh', 'LWEMP01', [0, 0, 0]), ('Madhya Pradesh', 'LWEMP01', [0, 0, 0]),
            ('Odisha', 'LWEOD01', [0, 0, 0]), ('Odisha', 'LWEOD01', [0, 60, 0]),
        ])
        self.assertEqual(batch.report['rejected_rows_by_reason'], {'duplicate_site': 2})
        self.assertEqual((batch.records_accepted, batch.records_duplicate, batch.records_rejected), (3, 3, 6))
        assert_balanced(self, batch)

    def test_a_4g_site_in_an_lwe_file_is_rejected(self):
        batch = self.preview([('Madhya Pradesh', 'UVMP001', [0, 0, 0])])
        self.assertEqual(batch.report['rejected_rows_by_reason'], {'technology_mismatch': 1})

    def test_missing_id_column_and_missing_sheet_are_refused(self):
        batch = self.preview([('Madhya Pradesh', 'LWEMP01', [0, 0, 0])], id_header='Something else')
        self.assertEqual(batch.validation_status, UploadBatch.Validation.FAILED)
        self.assertIn('site ID column', batch.error)
        batch = self.preview([('Madhya Pradesh', 'LWEMP01', [0, 0, 0])], sheet_name='Outage')
        self.assertEqual(batch.validation_status, UploadBatch.Validation.FAILED)
        self.assertIn('neither', batch.error)



def read_exceptions(batch):
    path = batch.report.get('exception_report')
    if not path:
        return []
    with open(path, encoding='utf-8-sig') as handle:
        return list(csv.DictReader(handle))


class OutageRangeTests(SiteDataTestCase):
    def test_outage_above_1440_or_below_0_is_rejected_never_capped_and_valid_days_continue(self):
        self.load_matrix()
        sites = [('4G Satu.', 'MP', 'UVMP001', 'Alpha', 'Yes', 'Yes', [1440.5, -1, 1440])]
        batch = uptime_master.preview(write_workbook(self.tmp / 'range.xlsx', sites), 'range.xlsx', user=self.admin)
        self.assertEqual(batch.report['rejected_site_days_by_reason'], {'outage_out_of_range': 2})
        rows = [r for r in read_exceptions(batch) if r['code'] == 'outage_out_of_range']
        self.assertEqual(sorted((r['source_file'], r['site_id'], r['report_date'], r['value']) for r in rows),
                         [('range.xlsx', 'UVMP001', '2026-10-01', '1440.5'), ('range.xlsx', 'UVMP001', '2026-10-02', '-1')])
        uptime_master.commit(batch, user=self.admin)
        self.assertEqual(list(DailySitePerformance.objects.values_list('report_date', 'outage_minutes')), [(date(2026, 10, 3), 1440.0)])

    def test_rules_reject_out_of_range_in_both_directions(self):
        self.assertEqual(rules.check_outage(1440).value, 1440)
        for value in (1440.01, -0.01):
            self.assertEqual(rules.check_outage(value).code, 'outage_out_of_range')
        self.assertEqual(rules.check_outage('').code, 'not_reported')
        self.assertEqual(rules.check_availability(' ').code, 'not_reported')
        self.assertEqual(rules.check_availability('0.985').value, 0.985)  # a percentage, never scaled


class OmStartFromMatrixTests(SiteDataTestCase):
    def test_effective_date_rule(self):
        october = date(2026, 10, 1)
        self.assertEqual(rules.om_effective_from(date(2025, 1, 1), october), date(2026, 10, 1))
        self.assertEqual(rules.om_effective_from(date(2026, 10, 15), october), date(2026, 10, 15))
        self.assertIsNone(rules.om_effective_from(date(2026, 11, 1), october))
        self.assertIsNone(rules.om_effective_from(None, october))
        self.assertEqual(rules.om_start_date_issue(None, ''), 'missing')
        self.assertEqual(rules.om_start_date_issue(None, 'NO'), 'invalid')

    def test_monthly_om_results_follow_the_matrix_date_and_missing_dates_are_flagged(self):
        rows = [r[:] for r in MATRIX]
        rows[1][7] = datetime(2026, 10, 2)    # UVMP002: O&M from 2 Oct
        rows[2][7] = 'NO'                     # UVRJ001: unreadable
        rows[3][7] = datetime(2026, 11, 15)   # LWEMP01: starts after October
        from unittest import mock
        with mock.patch('apps.sitedata.matrix.timezone.localdate', return_value=date(2026, 11, 5)):  # a fixed "today"
            batch = self.load_matrix(rows)
        flags = dict(Site.objects.filter(reporting_scope='dashboard').values_list('site_key', 'om_start_date_issue'))
        self.assertEqual(flags, {'UVMP001': '', 'UVMP002': '', 'UVRJ001': 'invalid', 'LWEMP01': '', 'LWEOD01': 'missing'})
        review = {r['site_id']: r['code'] for r in read_exceptions(Site.objects.get(site_key='UVMP001').matrix_batch) if r['code'].startswith('om_start_date')}
        # LWEMP01's 15 Nov 2026 is after today (the fixed 5 Nov 2026): flagged for review, still imported.
        self.assertEqual(review, {'UVRJ001': 'om_start_date_invalid', 'LWEMP01': 'om_start_date_in_future', 'LWEOD01': 'om_start_date_missing'})
        self.assertEqual({k: v for k, v in batch.report['effective_date_review'].items() if k.startswith('om_start_date_')},
                         {'om_start_date_invalid': 1, 'om_start_date_missing': 1, 'om_start_date_in_future': 1})
        self.load_uptime()  # Oct 1-3; its O&M flags are not used
        october = date(2026, 10, 1)
        calculations.calculate_month(october)
        om = {m.site.site_key: m for m in MonthlySitePerformance.objects.filter(month=october, calculation_category='om_start').select_related('site')}
        self.assertEqual(sorted(om), ['UVMP001', 'UVMP002'])
        self.assertEqual((om['UVMP002'].effective_from, om['UVMP002'].reporting_days, om['UVMP002'].calendar_days), (date(2026, 10, 2), 2, 30))
        self.assertEqual(om['UVMP002'].total_outage_minutes, 0)  # 2 and 3 Oct only (72 min on 1 Oct is before O&M Start)
        self.assertEqual((om['UVMP001'].effective_from, om['UVMP001'].reporting_days), (october, 3))
        ds = dataset.build()
        self.assertEqual(dict(zip(ds.sites['site_id'], ds.sites['om_start'])),
                         {'LWEMP01': False, 'LWEOD01': False, 'UVMP001': True, 'UVMP002': True, 'UVRJ001': False})

    def test_september_and_october_follow_the_same_rule(self):
        rows = [r[:] for r in MATRIX]
        rows[1][7] = datetime(2026, 9, 20)
        self.load_matrix(rows)
        site = Site.objects.get(site_key='UVMP002')
        self.assertEqual(rules.om_effective_from(site.om_start_date, date(2026, 9, 1)), date(2026, 9, 20))
        self.assertEqual(rules.om_effective_from(site.om_start_date, date(2026, 10, 1)), date(2026, 10, 1))


class UnmatchedSitesTests(SiteDataTestCase):
    def test_the_two_unmatched_sites_stay_unmatched_and_are_reported(self):
        self.load_matrix()
        sites = [('4G Satu.', 'RJ', 'UVRJJPR00057', 'A', 'Yes', 'Yes', [0, 0, 0]), ('4G Satu.', 'RJ', 'UVRJUPR00612', 'B', 'Yes', 'Yes', [10, 10, 10]),
                 ('4G Satu.', 'RJ', 'UVRJ001', 'Delta', 'Yes', 'Yes', [5, 5, 5])]
        batch = self.load_uptime(sites, name='rj.xlsx')
        self.assertEqual((batch.records_unmatched, batch.records_accepted), (6, 3))  # the valid site continues to import
        unmatched = {r['site_id']: r for r in read_exceptions(batch) if r['code'] == 'site_not_in_master'}
        self.assertEqual(sorted(unmatched), ['UVRJJPR00057', 'UVRJUPR00612'])
        self.assertEqual(unmatched['UVRJJPR00057']['severity'], 'unmatched')
        self.assertFalse(Site.objects.filter(site_key__in=['UVRJJPR00057', 'UVRJUPR00612']).exists())  # no automatic master record
        self.assertNotIn('UVRJJPR00057', set(dataset.build().sites['site_id']))


class AmbiguousBandIdTests(SiteDataTestCase):
    def matrix_with_shared_band(self):
        rows = [r[:] for r in MATRIX]
        rows[1][13] = 'T4MP28BLG001lw'  # UVMP002's 700 MHz ID = the LWE site's 700 ID in the mapping
        rows[2][13] = 'T4MP28BLG001lw'  # and UVRJ001's: one band ID, two matrix sites
        return self.load_matrix(rows)

    def test_never_assigned_reported_with_every_claimant_and_blocked_for_lwe(self):
        batch = self.matrix_with_shared_band()
        self.assertFalse(SiteIdentifier.objects.filter(key='T4MP28BLG001LW').exists())
        conflict = IdentifierConflict.objects.get(key='T4MP28BLG001LW')
        self.assertEqual((conflict.kind, conflict.active, sorted(c['site_id'] for c in conflict.claims)), ('band_700', True, ['UVMP002', 'UVRJ001']))
        rows = [r for r in read_exceptions(batch) if r['code'] == 'ambiguous_identifier']
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['identifier'], rows[0]['site_id'], rows[0]['circle']), ('T4MP28BLG001lw', 'UVMP002, UVRJ001', 'MP, RJ'))
        self.assertEqual(Site.objects.count(), 7)  # every site is still imported
        mapping = self.load_bands()
        self.assertEqual(mapping.report['rejected_by_reason'], {'ambiguous_identifier': 1})  # LWEMP01's row uses it
        bandmap.commit(mapping)
        self.assertTrue(SiteIdentifier.objects.filter(site__site_key='LWEOD01', kind='bts_ip_id').exists())  # the other row continues
        raw = self.raw(LWE, 'MP', date(2026, 11, 1), [('MPBLG001', '', 'T4MP28BLG001lw', '99', 'MP', '01-11-2026')], commit=False)
        self.assertEqual(raw.report['rejected_by_reason'], {'ambiguous_identifier': 1})

    def test_an_identifier_that_becomes_ambiguous_loses_its_earlier_assignment(self):
        self.load_matrix()
        bandmap.commit(self.load_bands())  # LWEMP01 gets T4MP28BLG001LW from the mapping
        self.assertTrue(SiteIdentifier.objects.filter(key='T4MP28BLG001LW').exists())
        rows = [r[:] for r in MATRIX]
        rows[1][13] = 'T4MP28BLG001lw'  # a new matrix gives it to a 4G site as well
        self.load_matrix(rows, 'matrix2.xlsx')
        self.assertFalse(SiteIdentifier.objects.filter(key='T4MP28BLG001LW').exists())
        claims = IdentifierConflict.objects.get(key='T4MP28BLG001LW').claims
        self.assertEqual(sorted(c['site_id'] for c in claims), ['LWEMP01', 'UVMP002'])



class PeriodAndOnAirRuleTests(SiteDataTestCase):
    def test_weeks_end_on_the_months_last_day(self):
        self.assertEqual([(a.day, b.day) for _, a, b in rules.weeks(date(2026, 9, 1))], [(1, 7), (8, 14), (15, 21), (22, 30)])
        self.assertEqual(rules.weeks(date(2026, 10, 1))[-1][1:], (date(2026, 10, 22), date(2026, 10, 31)))

    def test_mtd_stops_before_the_first_date_without_data(self):
        have = [date(2026, 10, d) for d in (1, 2, 3, 5, 6)]
        self.assertEqual(rules.mtd_dates(have, date(2026, 10, 1)), [date(2026, 10, d) for d in (1, 2, 3)])
        self.assertEqual(rules.mtd_dates(have, date(2026, 10, 1), until=date(2026, 10, 2)), [date(2026, 10, 1), date(2026, 10, 2)])
        self.assertEqual(rules.mtd_dates([date(2026, 10, 2)], date(2026, 10, 1)), [])  # no data on the 1st: no MTD

    def test_on_air_follows_the_matrix_on_air_date_like_om(self):
        rows = [r[:] for r in MATRIX]
        rows[1][9] = datetime(2026, 10, 2)   # UVMP002 On-Air from 2 Oct
        rows[2][9] = None                    # UVRJ001: no date (status blank as well)
        rows[3][9] = 'NO'                    # LWEMP01: unreadable
        rows[4][9] = datetime(2026, 11, 1)   # LWEOD01: On-Air only from November
        batch = self.load_matrix(rows)
        flags = dict(Site.objects.filter(reporting_scope='dashboard').values_list('site_key', 'on_air_date_issue'))
        self.assertEqual(flags, {'UVMP001': '', 'UVMP002': '', 'UVRJ001': 'missing', 'LWEMP01': 'invalid', 'LWEOD01': ''})
        review = {r['site_id']: r['code'] for r in read_exceptions(batch) if r['code'].startswith('on_air_date')}
        self.assertEqual(review, {'UVRJ001': 'on_air_date_missing', 'LWEMP01': 'on_air_date_invalid'})
        self.load_uptime()
        october = date(2026, 10, 1)
        calculations.calculate_month(october)
        on_air = {m.site.site_key: m for m in MonthlySitePerformance.objects.filter(month=october, calculation_category='on_air').select_related('site')}
        self.assertEqual(sorted(on_air), ['UVMP001', 'UVMP002'])
        self.assertEqual((on_air['UVMP002'].effective_from, on_air['UVMP002'].reporting_days, on_air['UVMP002'].calendar_days), (date(2026, 10, 2), 2, 30))
        self.assertEqual(dict(zip(dataset.build().sites['site_id'], dataset.build().sites['on_air'])),
                         {'LWEMP01': False, 'LWEOD01': False, 'UVMP001': True, 'UVMP002': True, 'UVRJ001': False})



def oct_csv(site, avail, day='01-10-2026', circle='MP'):
    return [(site, '', '', avail, circle, day)]


class SourcePrecedenceTests(SiteDataTestCase):
    """Uptime Master > raw CNMC CSV, whatever the upload order (UVMP001: 0 min = 100% on 1 Oct in the Uptime Master)."""

    def setUp(self):
        super().setUp()
        self.load_matrix()

    def record(self, day=date(2026, 10, 1)):
        return DailySitePerformance.objects.select_related('batch').get(site__site_key='UVMP001', report_date=day)

    def test_uptime_master_after_a_conflicting_csv_supersedes_it_and_keeps_the_trail(self):
        csv_batch = self.raw(G4, 'MP', date(2026, 10, 1), oct_csv('UVMP001', '99'))
        master = self.load_uptime()
        self.assertEqual((master.records_superseded, master.records_conflict), (1, 0))
        rec = self.record()
        self.assertEqual((rec.availability_pct, rec.batch_id, rec.revision), (100.0, master.pk, 2))
        event = DailyPerformanceEvent.objects.get(action='superseded')
        self.assertEqual((event.stored_availability_pct, event.stored_batch_id, event.proposed_availability_pct, event.batch_id), (99.0, csv_batch.pk, 100.0, master.pk))
        self.assertIn('day.csv', event.reason)  # the replaced value's file
        superseded = [r for r in read_exceptions(master) if r['code'] == 'superseded_lower_precedence']
        self.assertEqual(len(superseded), 1)

    def test_a_conflicting_csv_after_the_uptime_master_is_logged_and_never_applied(self):
        master = self.load_uptime()
        csv_batch = self.raw(G4, 'MP', date(2026, 10, 1), oct_csv('UVMP001', '99'))
        self.assertEqual((csv_batch.records_conflict, csv_batch.records_superseded, csv_batch.records_accepted), (1, 0, 0))
        rec = self.record()
        self.assertEqual((rec.availability_pct, rec.batch_id, rec.revision), (100.0, master.pk, 1))
        event = DailyPerformanceEvent.objects.get(action='conflict')
        self.assertEqual((event.proposed_availability_pct, event.batch_id, event.stored_batch_id), (99.0, csv_batch.pk, master.pk))
        self.assertEqual([r['code'] for r in read_exceptions(csv_batch) if r['severity'] == 'conflict'], ['daily_conflict'])

    def test_import_order_does_not_change_the_result(self):
        self.raw(G4, 'MP', date(2026, 10, 1), oct_csv('UVMP001', '99'))
        self.load_uptime()
        first_order = self.record().availability_pct
        DailySitePerformance.objects.all().delete()  # test database only
        self.load_uptime(name='again.xlsx')
        self.raw(G4, 'MP', date(2026, 10, 1), oct_csv('UVMP001', '99'))
        self.assertEqual((first_order, self.record().availability_pct), (100.0, 100.0))

    def test_csv_is_accepted_where_the_uptime_master_has_no_value(self):
        self.load_uptime()  # 1-3 Oct only
        batch = self.raw(G4, 'MP', date(2026, 10, 5), oct_csv('UVMP001', '97.25', day='05-10-2026'))
        self.assertEqual(batch.records_accepted, 1)
        self.assertEqual(self.record(date(2026, 10, 5)).availability_pct, 97.25)

    def test_identical_values_are_matching_duplicates_in_both_orders(self):
        self.raw(G4, 'MP', date(2026, 10, 1), oct_csv('UVMP001', '100'))
        master = self.load_uptime()
        self.assertEqual((master.records_superseded, master.records_conflict), (0, 0))
        again = self.raw(G4, 'MP', date(2026, 10, 1), oct_csv('UVMP001', '100'))
        self.assertEqual((again.records_duplicate, again.records_conflict), (1, 0))
        self.assertFalse(DailyPerformanceEvent.objects.exists())

    def test_equal_sources_keep_the_first_value_and_corrections_are_never_overridden(self):
        self.raw(G4, 'MP', date(2026, 10, 5), oct_csv('UVMP001', '90', day='05-10-2026'))
        second = self.raw(G4, 'MP', date(2026, 10, 5), oct_csv('UVMP001', '91', day='05-10-2026'))
        self.assertEqual(second.records_conflict, 1)
        self.assertEqual(self.record(date(2026, 10, 5)).availability_pct, 90.0)
        self.load_uptime()
        daily.correct(self.record(), 95, user=self.admin, reason='verified')
        later = self.load_uptime(name='later.xlsx')
        self.assertEqual((later.records_conflict, later.records_superseded), (1, 0))
        self.assertEqual(self.record().availability_pct, 95.0)


class LweIdentifierRuleTests(SiteDataTestCase):
    """LWEMP01: BTS IP ID MPBLG001, 2100 T4MP01BLG001lw, 700 T4MP28BLG001lw. LWEOD01: ORKRP001, 700 T4OD28KRP001lw."""

    def setUp(self):
        super().setUp()
        self.load_matrix()
        bandmap.commit(self.load_bands())

    def check(self, *rows):
        batch = self.raw(LWE, 'MP', date(2026, 11, 1), [(ip, b21, b7, '99', 'MP', '01-11-2026') for ip, b21, b7 in rows], commit=False)
        return batch

    def test_split_ids(self):
        from apps.sitedata.identifiers import is_valid_id, split_ids
        self.assertEqual(split_ids('  A1 ;; ;;a1;;B2 ;;'), ['A1', 'B2'])  # trimmed, empty dropped, distinct kept
        self.assertEqual(split_ids(''), [])
        self.assertEqual(split_ids(' - ;;NA;;T4X1'), ['T4X1'])  # placeholders are empty cells
        self.assertFalse(is_valid_id('-'))
        self.assertEqual(split_ids('A;;;B'), ['A', ';B'])
        self.assertFalse(is_valid_id(';B'))
        self.assertFalse(is_valid_id('A;B'))

    def test_accepted_combinations(self):
        cases = {
            'bts ip id not in the mapping, bands match': ('LWE9999', 'T4MP01BLG001lw', 'T4MP28BLG001lw'),
            'no bts ip id, only 700': ('', '', 'T4MP28BLG001lw'),
            'only 2100': ('', 'T4MP01BLG001lw', ''),
            'both bands of one record': ('', 'T4MP01BLG001lw', 'T4MP28BLG001lw'),
            'all three': ('MPBLG001', 'T4MP01BLG001lw', 'T4MP28BLG001lw'),
            ';; cell, whitespace, empty token, repeat': ('', '  T4MP01BLG001lw ;; ;;t4mp01blg001LW', 'T4MP28BLG001lw;;'),
            'bts ip id is the master id': ('LWEMP01', '', ''),
        }
        for label, row in cases.items():
            with self.subTest(label):
                batch = self.check(row)
                self.assertEqual((batch.records_accepted, batch.records_rejected), (1, 0), batch.report.get('rejected_rows'))
        self.assertEqual(self.check(cases['bts ip id not in the mapping, bands match']).report['skipped'], {'bts_ip_id_not_in_mapping': 1})

    def test_rejected_combinations(self):
        cases = {
            'bands of different master ids': (('', 'T4MP01BLG001lw', 'T4OD28KRP001lw'), 'identifier_mismatch'),
            'bts ip id of another site': (('ORKRP001', 'T4MP01BLG001lw', ''), 'identifier_mismatch'),
            ';; tokens of two sites': (('', '', 'T4MP28BLG001lw;;T4OD28KRP001lw'), 'identifier_mismatch'),
            'band token not in the mapping': (('', 'T4MP01BLG001lw', 'T4MP28UNKNOWN'), 'identifier_not_in_mapping'),
            ';; with an unknown token': (('', '', 'T4MP28BLG001lw;;T4MP28OTHER'), 'identifier_not_in_mapping'),
            'single ; separator': (('', 'T4MP01BLG001lw;T4MP01X', ''), 'invalid_identifier'),
            ';;; separator': (('', '', 'T4MP28BLG001lw;;;T4MP28X'), 'invalid_identifier'),
            'no identifier at all': (('', '', ''), 'no_identifier'),
        }
        for label, (row, code) in cases.items():
            with self.subTest(label):
                self.assertEqual(self.check(row).report['rejected_by_reason'], {code: 1})
        unknown = self.check(('NOTASITE', 'T4NOPE', ''))
        self.assertEqual((unknown.records_unmatched, unknown.records_rejected), (1, 0))  # nothing known: not an LWE site
        malformed = self.check(('PUR028', ';T4OD01UNKNOWN', 'T4OD28A;T4OD28B'))  # malformed cells, nothing known: a row of another BTS
        self.assertEqual((malformed.records_unmatched, malformed.records_rejected), (1, 0))

    def test_4g_rows_are_skipped_before_their_band_cells_are_judged(self):
        batch = self.check(('UVMP001', 'X;Y', ''))
        self.assertEqual((batch.report['skipped'], batch.records_rejected), ({'other_technology': 1}, 0))


class BandMappingNormalisationTests(SiteDataTestCase):
    def setUp(self):
        super().setUp()
        self.load_matrix()

    def test_bts_ip_id_is_optional_and_double_semicolon_cells_give_every_identifier(self):
        batch = self.load_bands([['MP', '', 'T4MP01A1;; T4MP01A2 ;;', 'T4MP28A1', 'LWEMP01'], ['OD', 'ORKRP001', '-', 'T4OD28KRP001lw', 'LWEOD01']])
        self.assertEqual(batch.records_rejected, 0)
        bandmap.commit(batch)
        keys = set(Site.objects.get(site_key='LWEMP01').identifiers.values_list('kind', 'key'))
        self.assertEqual({k for k in keys if k[0] != 'bsnl_site_id'}, {('band_2100', 'T4MP01A1'), ('band_2100', 'T4MP01A2'), ('band_700', 'T4MP28A1')})
        q = batch.report['quality']
        self.assertEqual((q['multi_id_cells']['BTS Site ID (2100)'], q['blank_cells']['BTS IP ID'], q['headers_missing']), (1, 1, []))

    def test_invalid_separators_duplicates_and_conflicting_master_ids_are_rejected(self):
        batch = self.load_bands([
            ['MP', 'MPBLG001', 'T4MP01A;T4MP01B', '', 'LWEMP01'],      # single ";": invalid
            ['OD', 'ORKRP001', '', 'T4SHARED;;T4OD28X', 'LWEOD01'],     # T4SHARED also on another Master ID below
            ['MP', 'MPOTHER', '', 'T4SHARED', 'LWEXX01'],
            ['MP', '', '', '', 'LWEMP01'],                              # no identifier (and LWEMP01 repeated)
            ['MP', 'MPZZZ', '', '', ''],                                # no Master ID
        ])
        self.assertEqual(batch.report['rejected_by_reason'],
                         {'invalid_identifier': 1, 'duplicate_identifier': 1, 'unknown_master_id': 1, 'no_identifier': 1, 'missing_master_id': 1})
        q = batch.report['quality']
        self.assertEqual((q['cells_with_other_separators']['BTS Site ID (2100)'], q['identifiers_on_several_master_ids']['BTS Site ID (700)'],
                          q['master_ids_on_several_rows'], q['missing_master_ids']), (1, 1, 1, 1))



class LweMappingDatabaseTests(SiteDataTestCase):
    """The mapping is reference data in the database: every imported row is kept, and matching reads the database only."""

    def setUp(self):
        super().setUp()
        self.load_matrix()

    def mapping(self, rows, name='LWE Band ID.xlsx'):
        return bandmap.commit(bandmap.preview(write_sheet(self.tmp / name, BAND_HEADER, rows, title='Sheet1', preamble=False), name, user=self.admin))

    def active(self, site_key):
        return set(SiteIdentifier.objects.filter(site__site_key=site_key, batch__kind='lwe_band_mapping').values_list('kind', 'key'))

    def test_every_row_is_stored_with_its_outcome_identifiers_and_source(self):
        rows = [['MP', 'MPBLG001', 'T4MP01BLG001lw ;; T4MP01BLG001sa', 'T4MP28BLG001lw', 'LWEMP01'],
                ['OD', 'ORKRP001', '-', 'T4OD28KRP001lw', 'LWEOD01'],
                ['OD', 'ORKRP001', '-', 'T4OD28KRP001lw', 'LWEOD01'],          # identical repeat
                ['MP', 'MPX', 'T4A;T4B', '', 'LWEXX01']]                       # invalid separator
        batch = self.mapping(rows)
        stored = {r.source_row: r for r in LweMappingRow.objects.filter(batch=batch)}
        self.assertEqual({n: (r.status, r.change, r.reject_code) for n, r in stored.items()},
                         {2: ('accepted', 'added', ''), 3: ('accepted', 'added', ''), 4: ('duplicate', '', 'duplicate_row'), 5: ('rejected', '', 'invalid_identifier')})
        self.assertEqual((stored[2].band_2100_raw, stored[2].site.site_key), ('T4MP01BLG001lw ;; T4MP01BLG001sa', 'LWEMP01'))  # as written
        self.assertEqual(set(LweMappingIdentifier.objects.filter(row=stored[2], kind='band_2100').values_list('key', flat=True)), {'T4MP01BLG001LW', 'T4MP01BLG001SA'})
        self.assertEqual(self.active('LWEMP01'), {('bts_ip_id', 'MPBLG001'), ('band_2100', 'T4MP01BLG001LW'), ('band_2100', 'T4MP01BLG001SA'), ('band_700', 'T4MP28BLG001LW')})
        self.assertTrue(all(i.mapping_row_id == stored[2].pk for i in SiteIdentifier.objects.filter(site__site_key='LWEMP01', batch__kind='lwe_band_mapping')))
        self.assertTrue(Path(batch.stored_path).is_file() and batch.checksum_sha256)  # the workbook copy and checksum are kept
        self.assertEqual({r['code'] for r in read_exceptions(batch)}, {'duplicate_row', 'invalid_identifier'})

    def test_matching_reads_the_database_after_the_workbook_is_gone(self):
        batch = self.mapping(BAND)
        Path(batch.stored_path).unlink()
        (self.tmp / 'LWE Band ID.xlsx').unlink()
        with mock.patch('apps.sitedata.bandmap.load_workbook', side_effect=AssertionError('workbook read at runtime')):
            raw = self.raw(LWE, 'MP', date(2026, 11, 1), [('', '', 'T4MP28BLG001lw', '99', 'MP', '01-11-2026')])
        self.assertEqual(raw.records_accepted, 1)
        self.assertEqual(DailySitePerformance.objects.get().site.site_key, 'LWEMP01')

    def test_a_new_version_reports_changes_keeps_history_and_never_removes_automatically(self):
        first = self.mapping(BAND)
        again = self.mapping(BAND, 'again.xlsx')
        self.assertEqual(again.report['changes'], {'added': 0, 'changed': 0, 'unchanged': 2, 'kept_new_row_rejected': 0, 'not_in_this_workbook_kept': 0})
        second = self.mapping([['MP', 'MPBLG001', 'T4MP01BLG001lw', 'T4MP28NEW01lw', 'LWEMP01']], 'v2.xlsx')  # LWEOD01 absent, LWEMP01 700 changed
        self.assertEqual(second.report['changes'], {'added': 0, 'changed': 1, 'unchanged': 0, 'kept_new_row_rejected': 0, 'not_in_this_workbook_kept': 1})
        self.assertIn(('band_700', 'T4MP28NEW01LW'), self.active('LWEMP01'))
        self.assertNotIn(('band_700', 'T4MP28BLG001LW'), self.active('LWEMP01'))
        self.assertEqual(self.active('LWEOD01'), {('bts_ip_id', 'ORKRP001'), ('band_700', 'T4OD28KRP001LW')})  # kept, reported
        self.assertEqual([r['code'] for r in read_exceptions(second)], ['mapping_not_in_workbook'])
        self.assertEqual(LweMappingRow.objects.count(), 5)  # 2 + 2 + 1: no import's rows are deleted
        self.assertEqual(set(LweMappingRow.objects.values_list('batch_id', flat=True)), {first.pk, again.pk, second.pk})
        old = self.raw(LWE, 'MP', date(2026, 11, 1), [('', '', 'T4MP28BLG001lw', '99', 'MP', '01-11-2026')], commit=False)
        self.assertEqual(old.records_unmatched, 1)  # the replaced ID no longer matches

    def test_a_conflicting_update_is_held_for_review_and_the_active_mapping_stays(self):
        self.mapping(BAND)
        update = self.mapping([['MP', 'ORKRP001', 'T4MP01BLG001lw', '', 'LWEMP01']], 'v2.xlsx')  # LWEOD01's BTS IP ID given to LWEMP01
        self.assertEqual(update.report['rejected_by_reason'], {'identifier_assigned_elsewhere': 1})
        self.assertEqual(update.report['changes']['kept_new_row_rejected'], 1)
        self.assertIn(('bts_ip_id', 'MPBLG001'), self.active('LWEMP01'))  # earlier mapping kept
        self.assertEqual(SiteIdentifier.objects.get(kind='bts_ip_id', key='ORKRP001').site.site_key, 'LWEOD01')
        self.assertEqual({r['code'] for r in read_exceptions(update)}, {'identifier_assigned_elsewhere', 'mapping_kept_new_row_rejected', 'mapping_not_in_workbook'})

    def test_the_command_previews_and_commits(self):
        from io import StringIO

        from django.core.management import call_command
        path = write_sheet(self.tmp / 'cmd.xlsx', BAND_HEADER, BAND, title='Sheet1', preamble=False)
        out = StringIO()
        call_command('import_lwe_mapping', str(path), stdout=out)
        self.assertFalse(SiteIdentifier.objects.filter(batch__kind='lwe_band_mapping').exists())  # preview writes nothing
        call_command('import_lwe_mapping', str(path), '--commit', stdout=out)
        self.assertTrue(SiteIdentifier.objects.filter(batch__kind='lwe_band_mapping').exists())
        self.assertIn('Committed upload', out.getvalue())


class LweMappingMatrixOverlapTests(SiteDataTestCase):
    def test_an_identifier_the_matrix_already_gives_the_site_does_not_make_a_reimport_look_changed(self):
        rows = [r[:] for r in MATRIX]
        rows[3][13] = 'T4MP28BLG001lw'  # LWEMP01's 700 ID is in the matrix too
        self.load_matrix(rows)
        first = bandmap.commit(self.load_bands())
        self.assertEqual(first.report['changes']['added'], 2)
        again = bandmap.commit(self.load_bands())
        self.assertEqual((again.report['changes']['unchanged'], again.report['changes']['changed']), (2, 0))
        self.assertEqual(SiteIdentifier.objects.get(kind='band_700', key='T4MP28BLG001LW').batch.kind, 'consolidation_matrix')  # not duplicated



class ProductionReadinessFixTests(SiteDataTestCase):
    """Defects found in the production-readiness audit (4 Nov 2026)."""

    def test_a_matrix_value_longer_than_the_site_master_column_rejects_that_row(self):
        rows = [r[:] for r in MATRIX]
        rows[5][1] = 'Unknown Circle Name Of 30 Chars'  # an outside-scope circle is kept as written (upper case): too long
        batch = matrix.preview(write_sheet(self.tmp / 'long.xlsx', MATRIX_HEADER, rows), 'long.xlsx')
        self.assertEqual(batch.validation_status, UploadBatch.Validation.WARNINGS)  # the other rows can be imported
        self.assertEqual([(r['site_id'], r['code']) for r in batch.report['rejected']], [('VIDL001', 'value_too_long')])
        self.assertIn('circle (31 > 20)', batch.report['rejected'][0]['reason'])

    def test_a_mapping_cell_longer_than_its_column_is_rejected_not_truncated(self):
        self.load_matrix()
        batch = bandmap.commit(self.load_bands([BAND[0], ['OD', 'X' * 201, '', 'T4OD28KRP001lw', 'LWEOD01']]))
        self.assertEqual(batch.report['rejected_by_reason'], {'value_too_long': 1})
        row = LweMappingRow.objects.get(batch=batch, status='rejected')
        self.assertEqual((row.reject_code, len(row.bts_ip_id_raw)), ('value_too_long', 200))

    def test_a_superseded_record_gets_a_new_update_time(self):
        self.load_matrix()
        self.raw(G4, 'MP', date(2026, 10, 1), [('UVMP001', '', '', '99', 'MP', '01-10-2026')])
        before = DailySitePerformance.objects.get(site__site_key='UVMP001', report_date=date(2026, 10, 1)).updated_at
        self.load_uptime()
        rec = DailySitePerformance.objects.get(site__site_key='UVMP001', report_date=date(2026, 10, 1))
        self.assertEqual(rec.batch.kind, 'uptime_master')
        self.assertGreater(rec.updated_at, before)
