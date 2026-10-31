"""Raw daily CSV upload (Data Entry -> Upload CSV): parsing, availability and outage, master scope, dates and circles,
permissions, preview / commit / re-import, validation report, export and the database-backed dashboard.

Every file is synthetic and generated here. The layouts copy what the real CNMC daily dumps showed: a ~60-column
header containing BTS IP ID, Circle, Nw Avail (4G), Nw Avail (4G TCS), Outage Min. and Report Date (DD-MM-YYYY);
an optional title row above the header; the circle written "OR" for Odisha; blank availabilities; repeated IDs.
No test reads a reference file.
"""
import csv
import io
import tempfile
from datetime import date
from pathlib import Path
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from apps.accounts.scope import set_circles
from apps.uptimedb import datasource
from apps.uptimedb.models import AppSetting, DataImportBatch, SiteDailyPerformance, UptimeSite
from apps.uptimedb.raw import parser
from apps.uptimedb.raw.resolvers import FourGResolver, LweResolver, Resolution
from apps.uptimedb.raw.rules import PROJECT_RULES, canonical_circle, outage_minutes, resolve_availability
from tests.auth_helpers import portal_user

HEADER = ['SrNo', 'BTS IP ID', 'BTS Name', 'Circle', 'SSAID', 'TCS Onair', 'Band category', 'Site Type', 'Nw Avail (2G)',
          'Nw Avail (4G)', 'Nw Avail (4G TCS)', 'Outage Min.', 'Site Category', 'Report Date']
DAY = '13-10-2026'


def row(site, tcs, *, circle='OR', day=DAY, g4='', name='Site'):
    return ['1', site, name, circle, 'ORBAL', 'Y', 'B', 'SA', '', g4, tcs, '0', 'NORMAL', day]


def csv_bytes(rows, *, header=HEADER, preamble=None) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator='\r\n')
    if preamble:
        writer.writerow(preamble)
    writer.writerow(header)
    writer.writerows(rows)
    return out.getvalue().encode('utf-8')


def write(tmp: Path, data: bytes, name='day.csv') -> Path:
    path = tmp / name
    path.write_bytes(data)
    return path


class ParserTests(SimpleTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_a_clean_file_with_the_header_on_the_first_line(self):
        parsed = parser.parse(write(self.tmp, csv_bytes([row('UVOR001', '95.5'), row('UVOR002', '')])))
        self.assertEqual((parsed.header_line, parsed.preamble, len(parsed.rows)), (1, [], 2))
        self.assertEqual(parsed.rows[0].values['avail_4g_tcs'], '95.5')
        self.assertEqual(parsed.rows[1].line, 3)
        self.assertEqual(parsed.columns['avail_4g_tcs'], 'Nw Avail (4G TCS)')

    def test_a_title_row_above_the_header_is_reported_as_preamble_not_data(self):
        parsed = parser.parse(write(self.tmp, csv_bytes([row('UVOR001', '99')], preamble=['Network availability report', '', 'Jharkhand'])))
        self.assertEqual((parsed.header_line, len(parsed.rows), parsed.rows[0].line), (2, 1, 3))
        self.assertEqual(parsed.preamble, ['Network availability report, Jharkhand'])

    def test_columns_are_found_by_name_whatever_their_order_or_spacing(self):
        header = ['report date', ' Nw Avail (4G TCS) ', 'Circle', 'BTS  IP  ID', 'Extra column']
        data = csv_bytes([[DAY, '98.2', 'OR', 'UVOR001', 'x']], header=header)
        parsed = parser.parse(write(self.tmp, data))
        self.assertEqual(parsed.rows[0].values, {'report_date': DAY, 'avail_4g_tcs': '98.2', 'circle': 'OR', 'site_id': 'UVOR001'})
        self.assertIn('Extra column', parsed.unknown_headers)

    def test_dates_in_supported_formats(self):
        self.assertEqual(parser.parse_date('13-10-2026'), date(2026, 10, 13))
        self.assertEqual(parser.parse_date('13/10/2026'), date(2026, 10, 13))
        self.assertEqual(parser.parse_date('2026-10-13'), date(2026, 10, 13))
        self.assertIsNone(parser.parse_date('31-02-2026'))
        self.assertIsNone(parser.parse_date(''))

    def test_unsupported_or_damaged_files_are_refused(self):
        cases = [
            (b'', 'empty'),
            (b'\x00\x01PK\x03\x04binary', 'binary data'),
            (csv_bytes([row('UVOR001', '1')], header=[h for h in HEADER if h != 'Report Date']), 'Missing required columns: Report Date'),
            (csv_bytes([], header=HEADER), 'no data rows'),
            (b'a,b,c\n1,2,3\n', 'No header row'),
            (csv_bytes([['1', 'UVOR001', 'MP', '99', 'September', '2026']],
                       header=['SrNo', 'BTS IP ID', 'Circle', 'Nw Avail (4G TCS)', 'MONTH', 'YEAR']), 'monthly summary'),
            (csv_bytes([row('UVOR001', '1')], header=[h if h != 'Circle' else 'Zone' for h in HEADER]), 'Missing required columns: Circle'),
        ]
        for data, message in cases:
            with self.subTest(message), self.assertRaisesRegex(parser.RawParseError, message):
                parser.parse(write(self.tmp, data))
        with self.assertRaisesRegex(parser.RawParseError, 'larger than'):
            parser.parse(write(self.tmp, csv_bytes([row('UVOR001', '1')] * 50)), max_bytes=100)

    def test_malformed_and_blank_lines_are_counted_never_dropped_silently(self):
        data = csv_bytes([row('UVOR001', '99'), ['', '', ''], ['1', 'UVOR002', 'short row']])
        parsed = parser.parse(write(self.tmp, data))
        self.assertEqual((len(parsed.rows), parsed.blank_lines, parsed.malformed), (1, 1, [{'line': 4, 'cells': 3, 'expected': len(HEADER)}]))

    def test_windows_encoded_text_is_read(self):
        data = csv_bytes([row('UVOR001', '99', name='Café')]).decode('utf-8').encode('cp1252')
        parsed = parser.parse(write(self.tmp, data))
        self.assertEqual(parsed.encoding, 'cp1252')


class RulesTests(SimpleTestCase):
    def test_outage_minutes_of_a_full_day(self):
        for availability, minutes in ((100, 0), (95.5, 64.8), (94.44, 80.064), (0, 1440), (89.65, 149.04)):
            self.assertAlmostEqual(outage_minutes(availability), minutes, places=9)
        with self.assertRaises(ValueError):
            outage_minutes(100.5)

    def test_the_tcs_column_is_the_availability_and_blank_is_never_zero(self):
        rules = PROJECT_RULES['4G Saturation']
        ok = resolve_availability({'avail_4g_tcs': '94.44', 'avail_4g': ''}, rules)
        self.assertEqual((ok.value, ok.column, ok.code), (94.44, 'Nw Avail (4G TCS)', None))
        blank = resolve_availability({'avail_4g_tcs': '', 'avail_4g': '97'}, rules)
        self.assertEqual((blank.value, blank.code), (None, 'missing_availability'))
        self.assertIn('not read as 0%', blank.message)
        self.assertIn('not used in its place', blank.message)  # the other column is never substituted
        self.assertEqual(resolve_availability({'avail_4g_tcs': 'n/a'}, rules).code, 'invalid_availability')
        self.assertEqual(resolve_availability({'avail_4g_tcs': '-1'}, rules).code, 'availability_out_of_range')
        self.assertEqual(resolve_availability({'avail_4g_tcs': '100.01'}, rules).code, 'availability_out_of_range')
        both = resolve_availability({'avail_4g_tcs': '98', 'avail_4g': '96'}, rules)
        self.assertEqual((both.value, both.code), (98, None))
        self.assertIn('confirmed source', both.note)  # a disagreement is shown, the confirmed column is used

    def test_lwe_is_not_configured(self):
        self.assertFalse(PROJECT_RULES['LWE'].availability_confirmed)
        self.assertFalse(LweResolver.configured)


@override_settings()
class AliasTests(TestCase):
    """Raw circle codes resolve through Organization > Code Mapping (seeded with the verified OR -> OD only)."""

    def test_only_verified_circle_aliases(self):
        self.assertEqual((canonical_circle('OR'), canonical_circle(' od '), canonical_circle('MP'), canonical_circle('XX')), ('OD', 'OD', 'MP', 'XX'))


class RawUploadTestCase(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        override = override_settings(DATA_DIR=self.tmp / 'data')
        override.enable()
        self.addCleanup(override.disable)
        master = DataImportBatch.objects.create(original_filename='master.xlsx', checksum_sha256='x', sheet_name='Up-Time Report',
                                                stored_path='-', status=DataImportBatch.Status.COMMITTED)
        self.master = master
        self.sites = {}
        for project, circle, site in (('4G Saturation', 'OD', 'UVOR001'), ('4G Saturation', 'OD', 'UVOR002'), ('4G Saturation', 'OD', 'UVOR003'),
                                      ('4G Saturation', 'MP', 'UVMP001'), ('LWE', 'OD', 'LWEOD0001')):
            self.sites[site] = UptimeSite.objects.create(project=project, circle=circle, site_id=site, site_key=site, batch=master,
                                                         source_row=1, site_name=f'{site} name', on_air=True)
        self.admin = portal_user('raw-admin', 'admin')
        self.noc = portal_user('raw-noc', 'noc_lead')
        self.ci_od = portal_user('raw-ci-od', 'ci')
        set_circles(self.ci_od, ['OD'])
        self.ci_mp = portal_user('raw-ci-mp', 'ci')
        set_circles(self.ci_mp, ['MP'])
        self.ci_none = portal_user('raw-ci-none', 'ci')
        self.client.force_login(self.ci_od)

    def upload(self, rows=None, *, data=None, project='4G Saturation', circle='OD', day='2026-10-13', name='nw_aval_day.csv', **extra):
        data = data if data is not None else csv_bytes(rows)
        return self.client.post(reverse('raw-upload-preview'), {'file': SimpleUploadedFile(name, data), 'project': project, 'circle': circle,
                                                                'reporting_date': day, 'remarks': 'daily', **extra})

    def commit(self, batch_id, confirm=True):
        return self.client.post(reverse('raw-upload-commit', args=[batch_id]), {'confirm': confirm}, content_type='application/json')

    def codes(self, body) -> dict:
        return {r['raw_id']: r['code'] for r in body['rows']['rows']}


class ScopeTests(RawUploadTestCase):
    def test_every_row_is_checked_against_the_approved_master_scope(self):
        before = UptimeSite.objects.count()
        body = self.upload([
            row('UVOR001', '95.5'),            # valid, in scope
            row('uvor002 ', '100'),            # same site key, different spelling
            row('ZZOR999', '99'),              # not in the master: outside the project scope
            row('UVMP001', '99'),              # a 4G master site of another circle
            row('LWEOD0001', '99'),            # a master site of another project
            row('', '99'),                     # blank ID
            row('UVOR003', ''),                # in scope, availability missing
        ]).json()
        self.assertEqual(body['status'], 'previewed')
        self.assertEqual(self.codes(body), {'UVOR001': 'ready', 'uvor002': 'ready', 'ZZOR999': 'unknown_site', 'UVMP001': 'other_circle',
                                            'LWEOD0001': 'other_project', '': 'blank_site_id', 'UVOR003': 'missing_availability'})
        s = body['summary']
        self.assertEqual({k: s[k] for k in ('total_rows', 'valid_in_scope', 'ready_to_import', 'out_of_scope', 'project_or_circle_mismatches',
                                            'unresolved_or_ambiguous', 'availability_problems')},
                         {'total_rows': 7, 'valid_in_scope': 2, 'ready_to_import': 2, 'out_of_scope': 1, 'project_or_circle_mismatches': 2,
                          'unresolved_or_ambiguous': 1, 'availability_problems': 1})
        ready = next(r for r in body['rows']['rows'] if r['raw_id'] == 'UVOR001')
        self.assertEqual((ready['site_id'], ready['availability'], ready['outage_minutes']), ('UVOR001', 95.5, 64.8))
        self.assertEqual(body['master_scope']['missing_from_file'], 0)
        self.assertEqual(SiteDailyPerformance.objects.count(), 0)  # a preview writes no daily record
        self.assertEqual(UptimeSite.objects.count(), before)  # no master site is ever created

    def test_an_identifier_matching_several_master_sites_is_ambiguous(self):
        resolver = FourGResolver('4G Saturation', 'OD')
        resolver._by_key['DUP1'] = [self.sites['UVOR001'], self.sites['UVOR002']]
        self.assertEqual(resolver.resolve('dup1').code, 'ambiguous_site')
        self.assertEqual(resolver.resolve('UVOR001'), Resolution(self.sites['UVOR001'], None))

    def test_repeated_sites_identical_skipped_conflicting_rejected(self):
        body = self.upload([row('UVOR001', '99'), row('UVOR001', '99'), row('UVOR002', '98'), row('UVOR002', '97')]).json()
        rows = body['rows']['rows']
        self.assertEqual([r['code'] for r in rows], ['ready', 'duplicate_row', 'conflicting_duplicate', 'conflicting_duplicate'])
        self.assertEqual(body['summary']['ready_to_import'], 1)

    def test_lwe_rows_resolve_to_nothing_until_the_mapping_is_configured(self):
        self.client.force_login(self.admin)
        body = self.upload([row('LWEOD0001', '99'), row('JHDTJN001', '99')], project='LWE').json()
        self.assertEqual(set(self.codes(body).values()), {'lwe_mapping_not_configured'})
        self.assertEqual((body['summary']['ready_to_import'], body['resolver']['configured']), (0, False))
        refused = self.commit(body['id'])
        self.assertEqual(refused.status_code, 409)
        self.assertIn('Nothing in this file can be imported', refused.json()['error'])
        self.assertEqual(SiteDailyPerformance.objects.count(), 0)

    def test_an_empty_master_scope_fails_safely(self):
        self.client.force_login(self.admin)
        response = self.upload([row('UVRJ001', '99', circle='RJ')], circle='RJ')
        self.assertEqual(response.status_code, 409)
        self.assertIn('no 4G Saturation sites for circle RJ', response.json()['error'])


class DateCircleTests(RawUploadTestCase):
    def test_the_report_date_must_be_the_entered_date(self):
        mismatch = self.upload([row('UVOR001', '99')], day='2026-10-14').json()
        self.assertEqual((mismatch['status'], mismatch['blocked'], mismatch['summary']['ready_to_import']), ('rejected', True, 0))
        self.assertEqual(mismatch['file_issues'][0]['code'], 'date_mismatch')
        self.assertEqual(self.commit(mismatch['id']).status_code, 409)
        mixed = self.upload([row('UVOR001', '99'), row('UVOR002', '99', day='14-10-2026'), row('UVOR003', '99', day='not a date')]).json()
        self.assertEqual(mixed['file_issues'][0]['code'], 'mixed_dates')
        self.assertEqual(self.codes(mixed), {'UVOR001': 'ready', 'UVOR002': 'date_mismatch', 'UVOR003': 'invalid_date'})
        self.assertEqual(mixed['status'], 'rejected')

    def test_the_file_circle_must_be_the_selected_circle(self):
        body = self.upload([row('UVOR001', '99', circle='OR'), row('UVOR002', '99', circle='MP')]).json()
        self.assertEqual((body['status'], body['file_issues'][0]['code']), ('rejected', 'circle_mismatch'))
        self.assertEqual(self.codes(body), {'UVOR001': 'ready', 'UVOR002': 'circle_mismatch'})


class PermissionTests(RawUploadTestCase):
    def test_ci_users_upload_only_for_their_assigned_circles(self):
        self.client.force_login(self.ci_mp)
        self.assertEqual(self.upload([row('UVOR001', '99')]).status_code, 403)  # another circle, even with a valid file
        self.client.force_login(self.ci_none)
        self.assertEqual(self.upload([row('UVOR001', '99')]).status_code, 403)  # no circle assigned: nothing
        self.assertEqual(self.client.get(reverse('raw-upload-options')).status_code, 403)  # no CSV Upload permission anywhere
        self.client.force_login(self.ci_od)
        options = self.client.get(reverse('raw-upload-options')).json()
        self.assertEqual((options['assigned_circles'], options['projects'][0]['circles']), (['OD'], ['OD']))
        self.client.force_login(self.noc)
        self.assertEqual(self.client.get(reverse('raw-upload-options')).json()['assigned_circles'], None)

    def test_uploads_results_reports_and_commits_are_limited_to_the_uploader_and_admins(self):
        mine = self.upload([row('UVOR001', '99')]).json()
        for user, expected in ((self.ci_mp, 404), (self.noc, 404), (self.admin, 200)):
            self.client.force_login(user)
            for name in ('raw-upload', 'raw-upload-rows', 'raw-upload-issues'):
                self.assertEqual(self.client.get(reverse(name, args=[mine['id']])).status_code, expected, (user, name))
        self.client.force_login(self.ci_mp)
        self.assertEqual(self.commit(mine['id']).status_code, 404)
        self.assertEqual(self.client.get(reverse('raw-uploads')).json()['uploads'], [])
        self.client.logout()
        self.assertEqual(self.client.get(reverse('raw-uploads')).status_code, 401)
        self.assertEqual(self.upload([row('UVOR001', '99')]).status_code, 401)

    def test_admins_assign_circles_and_the_signed_in_user_sees_their_scope(self):
        self.client.force_login(self.admin)
        target = self.ci_none
        bad = self.client.patch(reverse('auth-user', args=[target.pk]), {'circles': ['XX']}, content_type='application/json')
        self.assertEqual(bad.status_code, 400)
        done = self.client.patch(reverse('auth-user', args=[target.pk]), {'circles': ['od', 'MP'][1:] + ['OD']}, content_type='application/json')
        self.assertEqual(done.json()['user']['circles'], ['MP', 'OD'])
        self.client.force_login(target)
        self.assertEqual(self.client.get(reverse('auth-me')).json()['user']['circles'], ['MP', 'OD'])
        self.assertEqual(self.upload([row('UVOR001', '99')]).status_code, 201)
        self.client.force_login(self.ci_od)
        self.assertEqual(self.client.patch(reverse('auth-user', args=[target.pk]), {'circles': []}, content_type='application/json').status_code, 403)
        self.client.force_login(self.noc)
        self.assertIsNone(self.client.get(reverse('auth-me')).json()['user']['circles'])  # not limited

    def test_only_csv_files_within_the_size_limit(self):
        self.assertEqual(self.upload([row('UVOR001', '99')], name='data.xlsx').status_code, 400)
        with override_settings(MAX_UPLOAD_BYTES=50):
            self.assertEqual(self.upload([row('UVOR001', '99')]).status_code, 400)
        self.assertEqual(self.upload([row('UVOR001', '99')], project='5G').status_code, 400)
        self.assertEqual(self.upload([row('UVOR001', '99')], day='2099-01-01').status_code, 400)


class CommitTests(RawUploadTestCase):
    def test_preview_then_explicit_commit_saves_the_approved_records(self):
        preview = self.upload([row('UVOR001', '95.5'), row('UVOR002', '94.44'), row('ZZOR999', '99')]).json()
        self.assertEqual(self.commit(preview['id'], confirm=False).status_code, 400)  # confirmation is explicit
        self.assertEqual(SiteDailyPerformance.objects.count(), 0)
        result = self.commit(preview['id'])
        self.assertEqual(result.status_code, 200, result.content)
        body = result.json()
        self.assertEqual((body['status'], body['daily']['inserted'], body['daily']['rejected']), ('committed', 2, 1))
        stored = {d.site.site_id: d for d in SiteDailyPerformance.objects.select_related('site')}
        self.assertAlmostEqual(stored['UVOR001'].outage_minutes, 64.8, places=9)
        self.assertEqual((stored['UVOR002'].uptime_pct, stored['UVOR002'].date), (94.44, date(2026, 10, 13)))
        batch = DataImportBatch.objects.get(pk=preview['id'])
        self.assertEqual((batch.kind, batch.imported_by, batch.project, batch.circle, batch.reporting_date, batch.remarks, batch.original_filename),
                         ('raw_daily_csv', self.ci_od, '4G Saturation', 'OD', date(2026, 10, 13), 'daily', 'nw_aval_day.csv'))
        self.assertEqual((batch.rejected_count, stored['UVOR001'].batch_id), (1, batch.pk))
        self.assertTrue(Path(batch.stored_path).is_file())
        self.assertEqual(self.commit(preview['id']).status_code, 409)  # imported once only

    def test_the_same_file_again_adds_nothing_and_a_different_value_never_overwrites(self):
        first = self.upload([row('UVOR001', '95.5'), row('UVOR002', '99')]).json()
        self.commit(first['id'])
        again = self.upload([row('UVOR001', '95.5'), row('UVOR002', '99')]).json()
        self.assertEqual(set(self.codes(again).values()), {'identical'})
        self.assertIsNotNone(again['already_imported'])
        self.assertEqual(self.commit(again['id']).status_code, 409)  # nothing new
        changed = self.upload([row('UVOR001', '90'), row('UVOR003', '99')]).json()
        self.assertEqual(self.codes(changed), {'UVOR001': 'conflict_existing', 'UVOR003': 'ready'})
        self.assertEqual(self.commit(changed['id']).json()['daily']['inserted'], 1)
        self.assertAlmostEqual(SiteDailyPerformance.objects.get(site=self.sites['UVOR001']).outage_minutes, 64.8, places=9)  # kept
        self.assertEqual(SiteDailyPerformance.objects.count(), 3)

    def test_a_day_stored_without_a_value_is_filled(self):
        SiteDailyPerformance.objects.create(site=self.sites['UVOR001'], date=date(2026, 10, 13), outage_minutes=None, batch=self.master)
        body = self.upload([row('UVOR001', '99')]).json()
        self.assertEqual(self.codes(body), {'UVOR001': 'fills_missing'})
        self.assertEqual(self.commit(body['id']).json()['daily']['filled'], 1)
        self.assertAlmostEqual(SiteDailyPerformance.objects.get().outage_minutes, 14.4, places=9)

    def test_a_failed_write_rolls_back_and_a_changed_database_is_refused(self):
        body = self.upload([row('UVOR001', '99'), row('UVOR002', '98')]).json()
        with mock.patch.object(SiteDailyPerformance.objects, 'bulk_create', side_effect=RuntimeError('disk full')):
            self.assertEqual(self.commit(body['id']).status_code, 500)  # the error handler answers; nothing is kept
        self.assertEqual((SiteDailyPerformance.objects.count(), DataImportBatch.objects.get(pk=body['id']).status), (0, 'previewed'))
        # Stored values changed after the preview: the approved records differ, so the commit is refused.
        SiteDailyPerformance.objects.create(site=self.sites['UVOR002'], date=date(2026, 10, 13), outage_minutes=1.0, uptime_pct=99.9, batch=self.master)
        refused = self.commit(body['id'])
        self.assertEqual(refused.status_code, 409)
        self.assertIn('Validate the file again', refused.json()['error'])
        self.assertEqual(SiteDailyPerformance.objects.count(), 1)

    def test_a_staged_file_changed_after_validation_cannot_be_committed(self):
        body = self.upload([row('UVOR001', '99')]).json()
        Path(DataImportBatch.objects.get(pk=body['id']).stored_path).write_bytes(csv_bytes([row('UVOR001', '10')]))
        self.assertEqual(self.commit(body['id']).status_code, 409)
        self.assertFalse(SiteDailyPerformance.objects.exists())

    def test_the_validation_report_lists_every_row_not_imported(self):
        body = self.upload([row('UVOR001', '99'), row('ZZOR999', '99'), row('UVOR002', 'abc')]).json()
        text = self.client.get(reverse('raw-upload-issues', args=[body['id']])).content.decode('utf-8-sig')
        lines = list(csv.reader(io.StringIO(text)))
        self.assertEqual(lines[0][:3], ['file', 'line', 'raw_bts_ip_id'])
        self.assertEqual(sorted((l[2], l[9]) for l in lines[1:]), [('UVOR002', 'invalid_availability'), ('ZZOR999', 'unknown_site')])
        paged = self.client.get(reverse('raw-upload-rows', args=[body['id']]), {'status': 'out_of_scope'}).json()
        self.assertEqual((paged['count'], paged['rows'][0]['raw_id']), (1, 'ZZOR999'))


class ExportAndDashboardTests(RawUploadTestCase):
    def import_od(self):
        self.client.force_login(self.ci_od)
        body = self.upload([row('UVOR001', '95.5'), row('UVOR002', '100')]).json()
        self.client.force_login(self.admin)
        mp = self.upload([row('UVMP001', '50', circle='MP')], circle='MP').json()
        self.commit(mp['id'])
        self.client.force_login(self.ci_od)
        return self.commit(body['id']).json()

    def test_the_database_dashboard_shows_the_import_and_the_source_setting_is_unchanged(self):
        AppSetting.objects.create(key=datasource.SOURCE_KEY, value=datasource.EXCEL)
        datasource.clear_cache()
        self.import_od()
        self.assertEqual(datasource.active_source(), datasource.EXCEL)  # never switched by an import
        dataset = datasource.database_dataset()
        column = dataset.dates.index(date(2026, 10, 13))
        values = dict(zip(dataset.sites['site_id'], dataset.outage[:, column]))
        self.assertAlmostEqual(values['UVOR001'], 64.8, places=6)
        self.assertNotEqual(values['UVOR003'], values['UVOR003'])  # not uploaded: a gap (NaN), never 0

    def test_master_workbook_imports_never_list_raw_uploads(self):
        self.import_od()
        self.client.force_login(self.admin)
        files = [b['file'] for b in self.client.get(reverse('import-list')).json()['imports']]
        self.assertNotIn('nw_aval_day.csv', files)


class ReferenceIndependenceTests(SimpleTestCase):
    def test_no_application_code_refers_to_temporary_reference_files(self):
        root = Path(__file__).resolve().parents[2]
        needles = ('4G - Data', 'nw_aval_btsipid_wise_day_new(', '/ref/', '\\ref\\', "'ref'", '"ref"')
        hits = []
        for folder, patterns in ((root / 'backend' / 'apps', ('*.py',)), (root / 'backend' / 'config', ('*.py',)),
                                 (root / 'frontend' / 'src', ('*.ts', '*.tsx'))):
            for pattern in patterns:
                for path in folder.rglob(pattern):
                    text = path.read_text(encoding='utf-8', errors='ignore').replace('djangoproject.com/en/5.1/ref/', '')  # Django docs links
                    hits += [f'{path.name}: {n}' for n in needles if n in text]
        self.assertEqual(hits, [])
