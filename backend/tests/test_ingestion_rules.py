"""Ingestion rules of the data layer (apps.sitedata), regression tests for the data-pipeline audit fixes: whole-circle raw
CSV classification, future dates, Uptime Master circles and duplicate site-days, out-of-scope months, Organization set-up,
pending processing (uncapped, under the lock, finalized months), relative stored paths, missing exception reports and the
matrix effective-date audit. Synthetic files, test database only."""
import shutil
from datetime import date, datetime
from pathlib import Path
from unittest import mock

from django.db import IntegrityError
from django.test import override_settings
from django.urls import reverse

from apps.sitedata import calculations, daily, matrix, rawcsv, unmatched, uploads, uptime_master
from apps.sitedata.models import DailyPerformanceEvent, DailySitePerformance, IdentifierConflict, Site, SiteIdentifier, UploadBatch
from tests.auth_helpers import SignedInTestCase
from tests.sitedata_factory import make_site
from tests.test_sitedata import (MATRIX, MATRIX_HEADER, SiteDataTestCase, day_wise_outage, up_time_report_without_project, write_csv,
                                 write_sheet)
from tests.workbook_factory import write_workbook

G4, LWE = '4G Saturation', 'LWE'
UVMP003 = ['4G Saturation', 'Madhya Pradesh', 'UVMP003', 'Charlie', 'B', 'O', 'D', datetime(2025, 1, 1), 'Yes', datetime(2025, 1, 1), 'IE One', 'CI West', '', '']
TODAY = 'django.utils.timezone.localdate'


class RawCsvClassificationTests(SignedInTestCase, SiteDataTestCase):
    def setUp(self):
        super().setUp()
        self.load_matrix()  # UVMP001 has the matrix band IDs T4MP01A / T4MP28A
        IdentifierConflict.objects.create(kind='bsnl_site_id', key='AMBIG1', value='AMBIG1', claims=[], active=True, batch=UploadBatch.objects.first())
        IdentifierConflict.objects.create(kind='band_2100', key='OLDCONF1', value='OLDCONF1', claims=[], active=False, batch=UploadBatch.objects.first())

    def test_every_row_is_in_exactly_one_category_and_only_programme_rows_are_pending(self):
        day = '01-11-2026'
        rows = [
            ('UVMP001', '', '', '99', 'MP', day),       # matched: ready
            ('UVMP002', '', '', '', 'MP', day),         # matched: blank availability = not reported
            ('LWEMP01', '', '', '99', 'MP', day),       # matched: a programme site of the other technology (not imported)
            ('STMP001', '', '', '99', 'MP', day),       # outside: Sterlite site
            ('RANDOM01', '', '', '99', 'MP', day),      # outside: nothing known anywhere
            ('UVRJ001', '', '', '99', 'MP', day),       # pending: site of another circle
            ('T4MP01A', '', '', '99', 'MP', day),       # pending: a matrix band ID of UVMP001, not a BTS IP ID
            ('OLDCONF1', '', '', '99', 'MP', day),      # pending: known from an identifier conflict
            ('AMBIG1', '', '', '99', 'MP', day),        # pending: blocked (ambiguous) identifier
            ('UVMP002', '', '', '101', 'MP', day),      # invalid: availability out of range
            ('A B;C', '', '', '99', 'MP', day),         # invalid: identifier format
            ('UVMP001', '', '', '99', 'MP', '02-11-2026'),  # invalid: another report date
        ]
        batch = self.raw(G4, 'MP', date(2026, 11, 1), rows, commit=False)
        report = batch.report
        self.assertEqual(report['classification'], {'matched': 3, 'unmatched_programme': 4, 'outside_programme': 2, 'invalid': 3})
        self.assertEqual(sum(report['classification'].values()), batch.records_received)
        self.assertEqual(report['classification_by_code']['unmatched_programme'],
                         {'site_of_other_circle': 1, 'unmatched_programme': 2, 'ambiguous_identifier': 1})
        self.assertEqual(report['classification_by_code']['outside_programme'], {'outside_scope': 1, 'outside_programme': 1})
        self.assertEqual((batch.records_unmatched, batch.records_rejected, batch.records_accepted), (4, 3, 1))
        self.assertEqual(len(report['rows']), len(rows))  # every raw row kept, with its category and code
        self.assertTrue(all(r['category'] in rawcsv.CATEGORIES and r['code'] for r in report['rows']))
        self.client.force_login(self.admin)
        detail = self.client.get(reverse('raw-upload', args=[batch.pk])).json()
        self.assertEqual(detail['summary']['classification'], report['classification'])
        self.assertEqual(detail['pending_sites'], ['AMBIG1', 'OLDCONF1', 'T4MP01A', 'UVRJ001'])

    def test_outside_programme_rows_are_information_not_warnings(self):
        batch = self.raw(G4, 'MP', date(2026, 11, 1), [('UVMP001', '', '', '99', 'MP', '01-11-2026'), ('RANDOM01', '', '', '99', 'MP', '01-11-2026'),
                                                       ('RANDOM02', '', '', '98', 'MP', '01-11-2026')], commit=False)
        self.assertEqual((batch.records_unmatched, batch.validation_status), (0, UploadBatch.Validation.PASSED))
        self.assertEqual(batch.report['classification']['outside_programme'], 2)
        self.assertEqual(batch.report['exceptions']['by_severity'], {'info': 2})

    def test_lwe_identifier_of_an_earlier_mapping_is_pending_not_outside(self):
        self.mapping_history('T4MPOLD99')
        batch = self.raw(LWE, 'MP', date(2026, 11, 1), [('', 'T4MPOLD99', '', '99', 'MP', '01-11-2026')], commit=False)
        self.assertEqual((batch.records_unmatched, batch.report['classification']['unmatched_programme']), (1, 1))

    def mapping_history(self, key):
        from apps.sitedata.models import LweMappingIdentifier, LweMappingRow
        row = LweMappingRow.objects.create(batch=UploadBatch.objects.first(), source_row=2, status='rejected', reject_code='x')
        LweMappingIdentifier.objects.create(row=row, kind='band_2100', value=key, key=key)


class FutureDateTests(SiteDataTestCase):
    def setUp(self):
        super().setUp()
        self.load_matrix()

    def test_daily_write_refuses_a_future_date_centrally(self):
        site = Site.objects.get(site_key='UVMP001')
        value = daily.DailyValue(site.pk, G4, 'MP', date(2027, 1, 15), 100.0, 0.0)
        batch = uploads.new_batch(UploadBatch.Kind.UPTIME_MASTER, write_csv(self.tmp / 'x.csv', []), 'x.csv')
        with self.assertRaises(daily.FutureDate):
            daily.write(batch, daily.Classified([value], [], []))
        self.assertFalse(DailySitePerformance.objects.exists())

    def test_uptime_master_rejects_future_cells(self):
        with mock.patch(TODAY, return_value=date(2026, 10, 2)):
            batch = uptime_master.preview(write_workbook(self.tmp / 'u.xlsx'), 'u.xlsx', user=self.admin)
            self.assertIn('future_date', batch.report['rejected_site_days_by_reason'])
            uptime_master.commit(batch, user=self.admin)
        self.assertFalse(DailySitePerformance.objects.filter(report_date=date(2026, 10, 3)).exists())
        self.assertTrue(DailySitePerformance.objects.filter(report_date=date(2026, 10, 2)).exists())

    def test_raw_csv_service_refuses_a_future_reporting_date_and_rejects_future_rows(self):
        batch = self.raw(G4, 'MP', date(2027, 1, 1), [('UVMP001', '', '', '99', 'MP', '01-01-2027')], commit=False)
        self.assertEqual(batch.validation_status, UploadBatch.Validation.FAILED)
        self.assertIn('future', batch.error)
        batch = self.raw(G4, 'MP', date(2026, 11, 1), [('UVMP001', '', '', '99', 'MP', '01-01-2027')], commit=False)
        self.assertEqual(batch.report['rejected_by_reason'], {'future_date': 1})

    def test_corrections_refuse_future_dates(self):
        site = Site.objects.get(site_key='UVMP001')
        with self.assertRaises(daily.FutureDate):
            daily.add_correction(site, date(2027, 1, 15), 99.0, user=self.admin, reason='typo')
        with self.assertRaises(ValueError):  # the correction API answers 400 on ValueError
            daily.add_correction(site, date(2027, 1, 15), 99.0, user=self.admin, reason='typo')


@override_settings(SITEDATA_MASTER_DAILY_MONTHS=('2026-09', '2026-10'))
class UptimeCircleAndDuplicateTests(SiteDataTestCase):
    def setUp(self):
        super().setUp()
        self.load_matrix()

    def up_time(self, rows, name='u.xlsx'):
        return uptime_master.preview(up_time_report_without_project(self.tmp / name, rows), name, project=G4, user=self.admin)

    def test_unknown_and_other_circles_are_rejected_in_the_up_time_report(self):
        batch = self.up_time([('ZZ', 'UVMP001', 'Yes', [0, 0, 0]), ('RJ', 'UVMP002', 'Yes', [0, 0, 0]), ('RJ', 'UVRJ001', 'Yes', [0, 0, 0])])
        self.assertEqual(batch.report['rejected_rows_by_reason'], {'unknown_circle': 1, 'site_of_other_circle': 1})
        self.assertEqual(batch.records_accepted, 3)  # UVRJ001 in RJ is fine

    def test_other_circle_is_rejected_in_the_day_wise_sheet(self):
        path = day_wise_outage(self.tmp / 'd.xlsx', [('Odisha', 'LWEMP01', [0, 0, 0]), ('Odisha', 'LWEOD01', [0, 0, 0])])
        batch = uptime_master.preview(path, 'd.xlsx', project=LWE, user=self.admin)
        self.assertEqual(batch.report['rejected_rows_by_reason'], {'site_of_other_circle': 1})

    def test_attribute_differences_are_warnings(self):
        batch = self.up_time([('MP', 'UVMP001', 'Yes', [0, 0, 0])])
        self.assertTrue(batch.report['matrix_attribute_differences'])
        self.assertTrue(any('differ from the Consolidation Matrix' in w for w in batch.report['warnings']))

    def alternate(self, value='ALT001', site='UVMP001'):
        unmatched.map_alternate(value, Site.objects.get(site_key=site), user=self.admin, reason='evidence')

    def test_master_and_alternate_rows_of_one_site_in_the_up_time_report(self):
        self.alternate()
        batch = self.up_time([('MP', 'UVMP001', 'Yes', [0, 0, 10]), ('MP', 'ALT001', 'Yes', [0, 60, 10])])
        self.assertNotEqual(batch.validation_status, UploadBatch.Validation.FAILED)
        self.assertEqual(batch.report['rejected_site_days_by_reason'], {'duplicate_site': 2})  # 2 Sep differs: both values rejected
        self.assertEqual((batch.records_accepted, batch.records_duplicate), (2, 2))
        uptime_master.commit(batch, user=self.admin)  # the preview passed, so the commit succeeds (no IntegrityError)
        self.assertEqual(DailySitePerformance.objects.filter(site__site_key='UVMP001').count(), 2)

    def test_master_and_alternate_rows_of_one_site_in_the_day_wise_sheet(self):
        self.alternate('ALTLWE1', 'LWEMP01')
        path = day_wise_outage(self.tmp / 'd.xlsx', [('Madhya Pradesh', 'LWEMP01', [0, 0, 0]), ('Madhya Pradesh', 'ALTLWE1', [0, 0, 5])])
        batch = uptime_master.preview(path, 'd.xlsx', project=LWE, user=self.admin)
        self.assertEqual(batch.report['rejected_site_days_by_reason'], {'duplicate_site': 2})
        uptime_master.commit(batch, user=self.admin)
        self.assertEqual(DailySitePerformance.objects.filter(site__site_key='LWEMP01').count(), 2)

    def test_integrity_error_at_commit_is_a_conflict_not_a_server_error(self):
        batch = self.up_time([('MP', 'UVMP001', 'Yes', [0, 0, 0])])
        self.client.force_login(self.admin)
        with mock.patch('apps.sitedata.uptime_master.commit', side_effect=IntegrityError('duplicate key')):
            r = self.client.post(reverse('sitedata-uptime-commit', args=[batch.pk]), {'confirm': True}, content_type='application/json')
        self.assertEqual(r.status_code, 409)
        self.assertIn('Preview the file again', r.json()['error'])


class OutOfScopeMonthTests(SiteDataTestCase):
    @override_settings(SITEDATA_MASTER_DAILY_MONTHS=('2026-09',))
    def test_values_of_months_outside_the_scope_are_counted_and_warned(self):
        self.load_matrix()
        batch = uptime_master.preview(write_workbook(self.tmp / 'u.xlsx'), 'u.xlsx', user=self.admin)
        self.assertEqual(batch.report['out_of_scope_site_days'], {'2026-10': 20})
        self.assertTrue(any('outside the months in scope' in w for w in batch.report['warnings']))
        self.assertEqual(batch.validation_status, UploadBatch.Validation.WARNINGS)


class OrganizationSetupTests(SiteDataTestCase):
    def test_matrix_preview_fails_for_a_circle_not_associated_with_its_project(self):
        rows = MATRIX + [['4G Saturation', 'Bihar', 'UVBH001', 'X', 'B', 'O', 'D', None, 'Yes', None, '', '', '', '']]  # BH is LWE only
        batch = matrix.preview(write_sheet(self.tmp / 'm.xlsx', MATRIX_HEADER, rows), 'm.xlsx', user=self.admin)
        self.assertEqual(batch.validation_status, UploadBatch.Validation.FAILED)
        self.assertIn('Set up the Organization first', batch.error)
        self.assertIn('BH under 4G Saturation', batch.error)

    @override_settings(SITEDATA_MASTER_DAILY_MONTHS=('2026-10',))
    def test_uptime_preview_fails_for_a_pair_not_set_up(self):
        make_site('UVBH001', technology=G4, circle='BH')
        sites = [('4G Satu.', 'BH', 'UVBH001', 'X', 'Yes', 'Yes', [0, 0, 0])]
        batch = uptime_master.preview(write_workbook(self.tmp / 'u.xlsx', sites), 'u.xlsx', user=self.admin)
        self.assertEqual(batch.validation_status, UploadBatch.Validation.FAILED)
        self.assertIn('Set up the Organization first', batch.error)
        with self.assertRaises(uploads.UploadRejected):
            uptime_master.commit(batch, user=self.admin)


class PendingProcessingTests(SiteDataTestCase):
    def test_more_than_200_unmatched_sites_are_all_processable(self):
        self.load_matrix()
        sites = [('4G Satu.', 'MP', f'UVX{n:03d}', 'S', 'Yes', 'Yes', [0, 0, 0]) for n in range(205)]
        batch = self.load_uptime(sites, name='many.xlsx')
        self.assertEqual((len(batch.report['sites_not_in_site_master']), len(batch.report['unmatched_keys'])), (200, 205))
        last = ['4G Saturation', 'Madhya Pradesh', 'UVX204', 'Last', 'B', 'O', 'D', None, 'Yes', datetime(2025, 1, 1), '', '', '', '']
        self.load_matrix([*MATRIX, last], name='matrix2.xlsx')
        self.assertEqual(next(s for s in unmatched.report()['sites'] if s['site_id'] == 'UVX204')['status'], 'ready')
        result = unmatched.process_pending(user=self.admin)
        self.assertEqual(result['counts']['accepted'], 3)
        self.assertEqual(DailySitePerformance.objects.filter(site__site_key='UVX204').count(), 3)

    def test_a_correction_made_while_processing_is_kept(self):
        self.load_matrix()
        upload = self.load_uptime()
        self.load_matrix([*MATRIX, UVMP003], name='matrix2.xlsx')
        site = Site.objects.get(site_key='UVMP003')
        real_lock, state = uploads.write_lock, {'done': False}

        def concurrent_correction():
            if not state['done']:  # another user's correction commits just before the pending processing gets the lock
                state['done'] = True
                daily.add_correction(site, date(2026, 10, 2), 99.0, user=self.admin, reason='Verified with the circle', refresh=False)
            real_lock()

        with mock.patch('apps.sitedata.uploads.write_lock', side_effect=concurrent_correction):
            result = unmatched.process_pending(user=self.admin)
        record = DailySitePerformance.objects.get(site=site, report_date=date(2026, 10, 2))
        self.assertEqual((record.availability_pct, record.batch.kind), (99.0, UploadBatch.Kind.CORRECTION))
        self.assertEqual((result['counts']['accepted'], result['counts']['conflict']), (2, 1))
        self.assertTrue(DailyPerformanceEvent.objects.filter(site=site, action='conflict', batch=upload).exists())

    def test_a_finalized_month_is_skipped_without_blocking_the_others(self):
        self.load_matrix()
        both = [('4G Satu.', 'MP', 'UVMP001', 'Alpha', 'Yes', 'Yes', [0, 0, 0]), ('4G Satu.', 'MP', 'UVMP003', 'Charlie', None, None, [5, 5, 5])]
        september = self.load_uptime_with(both, [[0] * 30, [7] * 30], 'sep.xlsx')  # committed first: Sep + Oct
        calculations.finalize_month(date(2026, 9, 1), user=self.admin)
        october = self.load_uptime([('4G Satu.', 'MP', 'UVMP003', 'Charlie', None, None, [5, 5, 5])], name='oct.xlsx')
        self.load_matrix([*MATRIX, UVMP003], name='matrix2.xlsx')
        result = unmatched.process_pending(user=self.admin)
        self.assertEqual([u['upload'] for u in result['skipped']], [september.pk])
        self.assertIn('Sep 2026', result['skipped'][0]['reason'])
        self.assertEqual([u['upload'] for u in result['uploads']], [october.pk])
        self.assertEqual(DailySitePerformance.objects.filter(site__site_key='UVMP003', report_date__month=10).count(), 3)
        self.assertFalse(DailySitePerformance.objects.filter(site__site_key='UVMP003', report_date__month=9).exists())

    def load_uptime_with(self, sites, september, name):
        batch = uptime_master.preview(write_workbook(self.tmp / name, sites, september=september), name, user=self.admin)
        return uptime_master.commit(batch, user=self.admin)


class StoredPathTests(SignedInTestCase, SiteDataTestCase):
    def test_relative_paths_survive_moving_the_data_directory(self):
        self.load_matrix()
        batch = self.raw(G4, 'MP', date(2026, 11, 1), [('UVMP001', '', '', '99', 'MP', '01-11-2026'), ('UVMP002', '', '', 'x', 'MP', '01-11-2026')],
                         commit=False)
        self.assertFalse(Path(batch.stored_path).is_absolute())
        self.assertFalse(Path(batch.report['exception_report']).is_absolute())
        moved = self.tmp / 'moved'
        shutil.copytree(self.tmp / 'staged', moved / 'staged')
        shutil.copytree(self.tmp / 'exceptions', moved / 'exceptions')
        shutil.rmtree(self.tmp / 'staged')
        shutil.rmtree(self.tmp / 'exceptions')
        with override_settings(SITEDATA_STAGING_DIR=str(moved / 'staged'), SITEDATA_EXCEPTION_DIR=str(moved / 'exceptions')):
            from apps.sitedata import exceptions
            self.assertTrue(exceptions.resolve(batch.report['exception_report']).is_file())
            rawcsv.commit(batch, user=self.admin)  # the staged copy is found and its checksum verified
        self.assertEqual(DailySitePerformance.objects.count(), 1)

    def test_a_legacy_absolute_path_falls_back_to_the_file_name_in_the_current_root(self):
        self.load_matrix()
        batch = self.raw(G4, 'MP', date(2026, 11, 1), [('UVMP001', '', '', '99', 'MP', '01-11-2026')], commit=False)
        batch.stored_path = 'C:\\Users\\someone\\OneDrive\\Data\\processed\\sitedata\\' + batch.stored_path  # another machine
        batch.save(update_fields=['stored_path'])
        self.assertTrue(uploads.staged_path(batch).is_file())
        rawcsv.commit(batch, user=self.admin)
        missing = UploadBatch.objects.create(kind=UploadBatch.Kind.RAW_CSV_4G, original_filename='x.csv', stored_path='C:\\nowhere\\gone.csv')
        with self.assertRaisesRegex(uploads.UploadRejected, 'missing'):
            uploads.staged_file(missing)


class MissingExceptionReportTests(SignedInTestCase, SiteDataTestCase):
    def test_issue_downloads_answer_410_when_the_file_is_missing(self):
        from apps.sitedata import exceptions
        self.client.force_login(self.admin)
        rows = MATRIX + [['Nonsense', 'Madhya Pradesh', 'BAD001', 'X', 'B', 'O', 'D', None, 'Yes', None, '', '', '', '']]
        mbatch = matrix.preview(write_sheet(self.tmp / 'm.xlsx', MATRIX_HEADER, rows), 'm.xlsx', user=self.admin)
        ubatch = uptime_master.preview(write_workbook(self.tmp / 'u.xlsx'), 'u.xlsx', user=self.admin)
        for name, batch in (('sitedata-matrix-issues', mbatch), ('sitedata-uptime-issues', ubatch)):
            with self.subTest(name):
                self.assertEqual(self.client.get(reverse(name, args=[batch.pk])).status_code, 200)
                exceptions.resolve(batch.report['exception_report']).unlink()
                r = self.client.get(reverse(name, args=[batch.pk]))
                self.assertEqual(r.status_code, 410)
                self.assertEqual(r.json()['error'], f'The exception report of upload #{batch.pk} is not available on this server '
                                                    '(its file is missing). Upload the file again to regenerate it.')


class MatrixEffectiveDateAuditTests(SiteDataTestCase):
    def test_changed_effective_dates_are_recorded_and_months_with_data_recalculated(self):
        self.load_matrix()
        self.load_uptime()  # October daily data
        rows = [r[:] for r in MATRIX]
        rows[0][9] = datetime(2026, 10, 2)  # UVMP001 On-Air 1 Jul 2024 -> 2 Oct 2026
        rows[1][7] = datetime(2026, 10, 1)  # UVMP002 O&M Start: none -> 1 Oct 2026
        with mock.patch('apps.sitedata.uploads.refresh_after_daily_write', wraps=uploads.refresh_after_daily_write) as refresh:
            batch = self.load_matrix(rows, 'matrix2.xlsx')
        changes = {(c['site_id'], c['field']): (c['old'], c['new']) for c in batch.report['effective_date_changes']}
        self.assertEqual(changes, {('UVMP001', 'on_air_date'): ('2024-07-01', '2026-10-02'), ('UVMP002', 'om_start_date'): (None, '2026-10-01')})
        months = list(refresh.call_args.args[0])
        self.assertIn(date(2026, 10, 1), months)
