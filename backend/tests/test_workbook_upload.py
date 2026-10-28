"""End-to-end tests of the Master workbook upload flow and the features that depend on it."""
import io
import tempfile
import zipfile
from pathlib import Path

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from openpyxl import load_workbook

from apps.dashboard import store, workbook

from .auth_helpers import SignedInTestCase
from .workbook_factory import DEFAULT_SITES, write_workbook

XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
# Sep-26 has 30 days; one site-month is 43,200 minutes.
MONTHLY = {
    'June-26 Outage Min.': [0, 0, 0, 0, 0, 0, 0],
    'Sep-26 Outage Min.': [4320, 0, None, 0, 1440, 0, 0],
}


class UploadTestCase(SignedInTestCase):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._override = override_settings(WORKBOOK_STORE_DIR=self.tmp / 'store', MASTER_WORKBOOK_PATH='')
        self._override.enable()
        workbook.clear_cache()

    def tearDown(self):
        self._override.disable()
        workbook.clear_cache()
        self._tmp.cleanup()

    def make(self, name='master.xlsx', sites=None, **kwargs) -> Path:
        return write_workbook(self.tmp / 'src' / name, sites, **kwargs)

    def upload(self, path: Path, name: str | None = None):
        content = path.read_bytes()
        return self.client.post(reverse('dashboard-workbook'), {'file': SimpleUploadedFile(name or path.name, content, XLSX)})

    def upload_bytes(self, name: str, content: bytes):
        return self.client.post(reverse('dashboard-workbook'), {'file': SimpleUploadedFile(name, content, XLSX)})


class UploadFlowTests(UploadTestCase):
    def test_no_workbook_state(self):
        status = self.client.get(reverse('dashboard-workbook')).json()
        self.assertIsNone(status['active'])
        self.assertEqual(status['code'], 'no_workbook')
        response = self.client.get(reverse('dashboard-summary'))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['details'], {'code': 'no_workbook'})

    def test_valid_upload_becomes_the_dashboard_source(self):
        source = self.make("4G_LWE_Consolidated_Oct'26.xlsx")
        original = source.read_bytes()
        response = self.upload(source)
        self.assertEqual(response.status_code, 201, response.content[:400])
        data = response.json()
        self.assertEqual(data['status'], 'accepted')
        active = data['active']
        self.assertEqual(active['workbook'], "4G_LWE_Consolidated_Oct'26.xlsx")
        self.assertEqual(active['sites'], 7)
        self.assertEqual(active['circles'], ['BH', 'MP', 'OD', 'RJ'])
        self.assertEqual(active['latest_reporting_date'], '2026-10-03')
        self.assertIsNotNone(active['uploaded_at'])
        self.assertIn({'name': 'Up-Time Report', 'role': workbook.SHEET_ROLES['Up-Time Report']}, active['sheets'])
        self.assertNotIn(str(self.tmp), response.content.decode())
        self.assertEqual(source.read_bytes(), original)  # the uploaded original is untouched

        summary = self.client.get(reverse('dashboard-summary')).json()
        self.assertEqual(summary['metrics']['sites_in_scope'], 5)
        self.assertEqual(summary['source']['workbook'], "4G_LWE_Consolidated_Oct'26.xlsx")

    def test_new_upload_replaces_the_previous_dataset(self):
        self.assertEqual(self.upload(self.make()).status_code, 201)
        self.assertEqual(self.upload(self.make('second.xlsx', DEFAULT_SITES[:2])).status_code, 201)
        summary = self.client.get(reverse('dashboard-summary'), {'scope': 'all'}).json()
        self.assertEqual(summary['metrics']['sites_in_scope'], 2)
        self.assertEqual(summary['source']['workbook'], 'second.xlsx')

    def test_rejected_upload_keeps_previous_dataset(self):
        self.assertEqual(self.upload(self.make()).status_code, 201)
        bad = self.make('bad.xlsx', sheet_name='Wrong sheet')
        response = self.upload(bad)
        self.assertEqual(response.status_code, 422)
        body = response.json()
        self.assertIn("'master.xlsx' is still in use", body['error'])
        self.assertTrue(body['details']['previous_workbook_kept'])
        self.assertIn("no 'Up-Time Report' sheet", body['details']['problems'][0])
        summary = self.client.get(reverse('dashboard-summary')).json()
        self.assertEqual(summary['source']['workbook'], 'master.xlsx')
        self.assertEqual(list((self.tmp / 'store').glob('.incoming-*')), [])  # staging file removed

    def test_missing_required_column_is_reported(self):
        path = self.make()
        book = load_workbook(path)
        book['Up-Time Report']['C2'] = 'Site ID'
        book.save(path)
        response = self.upload(path)
        self.assertEqual(response.status_code, 422)
        self.assertIn('btsIpId', response.json()['details']['problems'][0])
        self.assertIsNone(store.active_record())

    def test_workbook_without_reported_dates_is_rejected(self):
        sites = [('4G Satu.', 'MP', 'A', 'A', 'Yes', 'Yes', [])]
        response = self.upload(self.make(sites=sites))
        self.assertEqual(response.status_code, 422)
        self.assertIn('no daily outage values', response.json()['error'])

    def test_wrong_extension_and_macro_workbooks_are_rejected(self):
        self.assertEqual(self.upload_bytes('data.csv', b'a,b\n1,2\n').status_code, 400)
        response = self.upload_bytes('macro.xlsm', self.make().read_bytes())
        self.assertEqual(response.status_code, 400)
        self.assertIn('.xlsm', response.json()['error'])

    def test_embedded_vba_project_is_rejected(self):
        buffer = io.BytesIO(self.make().read_bytes())
        with zipfile.ZipFile(buffer, 'a') as package:
            package.writestr('xl/vbaProject.bin', b'\x00' * 16)
        response = self.upload_bytes('sneaky.xlsx', buffer.getvalue())
        self.assertEqual(response.status_code, 400)
        self.assertIn('macros', response.json()['error'])

    def test_renamed_non_excel_file_is_rejected(self):
        response = self.upload_bytes('fake.xlsx', b'this is not a workbook')
        self.assertEqual(response.status_code, 422)
        self.assertIn('not a valid Excel', response.json()['error'])

    def test_oversized_upload_is_rejected(self):
        with override_settings(MAX_WORKBOOK_BYTES=1000):
            response = self.upload(self.make())
        self.assertEqual(response.status_code, 413)

    def test_missing_file_field(self):
        response = self.client.post(reverse('dashboard-workbook'), {})
        self.assertEqual(response.status_code, 400)

    def test_only_recent_uploads_are_kept(self):
        for i in range(store.KEEP_ACCEPTED + 2):
            self.assertEqual(self.upload(self.make(f'm{i}.xlsx', DEFAULT_SITES[: i + 1])).status_code, 201)
        stored = list((self.tmp / 'store').glob('*.xlsx'))
        self.assertLessEqual(len(stored), store.KEEP_ACCEPTED)
        self.assertTrue(store.active_record()['path'].is_file())


class FormulaCacheTests(UploadTestCase):
    def test_uncached_formulas_are_flagged(self):
        path = self.make()
        book = load_workbook(path)
        sheet = book['Up-Time Report']
        sheet['M3'] = '=1-L3/1440'  # Oct-26 UpTime: openpyxl writes formulas without cached values
        sheet['O4'] = '=0+0'  # first daily outage column
        book.save(path)
        response = self.upload(path)
        self.assertEqual(response.status_code, 201)
        codes = {w['code']: w for w in response.json()['active']['warnings']}
        self.assertEqual(codes['formula_not_cached']['count'], 2)
        self.assertEqual(codes['outage_formula_not_cached']['count'], 1)

    def test_values_only_workbook_has_no_formula_warnings(self):
        response = self.upload(self.make())
        codes = {w['code'] for w in response.json()['active']['warnings']}
        self.assertNotIn('formula_not_cached', codes)


class MonthlyAndTeamTests(UploadTestCase):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.upload(self.make(monthly=MONTHLY)).status_code, 201)

    def test_monthly_history_in_calendar_order_with_mtd(self):
        data = self.client.get(reverse('dashboard-monthly'), {'report_type': '4G Saturation', 'circle': 'MP', 'scope': 'all'}).json()
        labels = [m['label'] for m in data['months']]
        self.assertEqual(labels, ['Jun-26', 'Sep-26', 'Oct-26 MTD'])
        sep = data['months'][1]
        self.assertEqual(sep['days'], 30)
        self.assertEqual(sep['sites_reported'], 2)
        self.assertEqual(sep['uptime_pct'], 95.0)  # 4320 / (1440 x 2 sites x 30 days)
        self.assertEqual(sep['uptime_pct_blank_as_zero'], round(100 * (1 - 4320 / (1440 * 3 * 30)), 4))
        self.assertTrue(data['months'][-1]['partial'])

    def test_monthly_change_by_type_and_overall(self):
        data = self.client.get(reverse('dashboard-monthly'), {'report_type': '4G Saturation', 'circle': 'MP', 'scope': 'all'}).json()
        jun, sep, mtd = data['months']
        self.assertIsNone(jun['change_pts'])
        self.assertEqual(sep['change_pts'], -5.0)  # 95.00 - 100.00
        # Oct MTD: (1584 + 72 + 4320) minutes over 9 site-days
        self.assertEqual(mtd['uptime_pct'], round(100 * (1 - 5976 / (1440 * 9)), 4))
        self.assertEqual(sep['by_report_type'], {'4G Saturation': 95.0})
        overall = data['overall']
        # Pooled: 10,296 minutes over 90 (Jun) + 60 (Sep) + 9 (Oct) site-days
        self.assertEqual(overall['uptime_pct'], round(100 * (1 - 10296 / (1440 * 159)), 4))
        self.assertEqual((overall['start'], overall['end'], overall['months']), ('2026-06-01', '2026-10-03', 3))

    def test_selected_months_only_with_change_against_previous_shown(self):
        options = self.client.get(reverse('dashboard-filters')).json()['months']
        self.assertEqual(options, [{'key': '2026-06', 'label': 'Jun-26'}, {'key': '2026-09', 'label': 'Sep-26'},
                                   {'key': '2026-10', 'label': 'Oct-26 MTD'}])
        params = {'report_type': '4G Saturation', 'circle': 'MP', 'scope': 'all'}
        data = self.client.get(reverse('dashboard-monthly'), {**params, 'months': '2026-06,2026-10'}).json()
        self.assertEqual([m['key'] for m in data['months']], ['2026-06', '2026-10'])
        mtd = data['months'][1]['uptime_pct']
        self.assertEqual(data['months'][1]['change_pts'], round(mtd - 100.0, 2))  # vs Jun, Sep not shown
        # Pooled over Jun (90 site-days, no outage) and Oct MTD (5,976 minutes over 9 site-days)
        self.assertEqual(data['overall']['uptime_pct'], round(100 * (1 - 5976 / (1440 * 99)), 4))
        self.assertEqual(data['overall']['months'], 2)

        history = self.client.get(reverse('dashboard-monthly'), {**params, 'months': '2026-06,2026-09'}).json()
        self.assertEqual((history['overall']['start'], history['overall']['end']), ('2026-06-01', '2026-09-30'))

    def test_unknown_month_is_rejected(self):
        response = self.client.get(reverse('dashboard-monthly'), {'months': '2026-06,2025-01'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('2025-01', str(response.json()))

    def test_monthly_outage_minutes(self):
        data = self.client.get(reverse('dashboard-monthly'), {'report_type': '4G Saturation', 'circle': 'MP', 'scope': 'all'}).json()
        jun, sep, mtd = data['months']
        self.assertEqual((jun['outage_minutes'], sep['outage_minutes'], mtd['outage_minutes']), (0, 4320, 5976))
        self.assertEqual(sep['outage_by_report_type'], {'4G Saturation': 4320})

    def test_monthly_splits_report_types_when_not_filtered(self):
        data = self.client.get(reverse('dashboard-monthly'), {'scope': 'all'}).json()
        self.assertEqual(data['report_types'], ['4G Saturation', 'LWE'])
        sep = data['months'][1]
        # LWE Sep: LWEMP01 1440 + LWEOD01 0 + LWEBH01 0 minutes over 3 sites x 30 days
        self.assertEqual(sep['by_report_type']['LWE'], round(100 * (1 - 1440 / (1440 * 90)), 4))
        self.assertEqual(set(data['overall']['by_report_type']), {'4G Saturation', 'LWE'})

    def test_team_performance_worst_first(self):
        data = self.client.get(reverse('dashboard-teams'), {'report_type': '4G Saturation', 'circle': 'MP', 'group': 'ci'}).json()
        self.assertEqual([t['name'] for t in data['teams']], ['CI East', 'CI West'])
        self.assertEqual(data['teams'][0]['mtd_uptime_pct'], round(100 * (1 - 1584 / 4320), 4))
        self.assertEqual(data['teams'][0]['sites_below_60_mtd'], 0)

    def test_team_buckets_links_and_totals(self):
        data = self.client.get(reverse('dashboard-teams'), {'report_type': '4G Saturation', 'circle': 'MP',
                                                            'scope': 'all', 'group': 'ci'}).json()
        east = data['teams'][0]
        self.assertEqual((east['name'], east['sites_in_scope'], east['sites_below_60_mtd']), ('CI East', 2, 1))
        # Alpha 63.3% (60-90), Charlie 0% (<60)
        self.assertEqual(east['buckets'], {'lt_60': 1, '60_90': 1, '90_97': 0, '97_98_5': 0, 'gte_98_5': 0})
        self.assertEqual(east['linked_names'], ['IE MP'])
        self.assertEqual(east['mtd_outage_minutes'], 1584 + 4320)
        self.assertEqual(data['totals'], {'teams': 2, 'teams_with_sites_below_60': 1, 'sites_in_scope': 3,
                                          'sites_below_60_mtd': 1, 'unassigned_sites': 0,
                                          'unassigned_sites_below_60_mtd': 0})
        ie = self.client.get(reverse('dashboard-teams'), {'circle': 'MP', 'scope': 'all', 'group': 'ie'}).json()
        self.assertEqual({t['name']: t['linked_names'] for t in ie['teams'] if t['report_type'] == '4G Saturation'},
                         {'IE MP': ['CI East', 'CI West']})

    def test_records_show_and_filter_by_responsible_team(self):
        params = {'report_type': '4G Saturation', 'circle': 'MP', 'scope': 'all', 'ci_name': 'CI East'}
        data = self.client.get(reverse('dashboard-records'), params).json()
        self.assertEqual([r['site_id'] for r in data['records']], ['UVMP001', 'UVMP003'])
        self.assertEqual((data['records'][0]['ci_name'], data['records'][0]['ie_name']), ('CI East', 'IE MP'))
        below = self.client.get(reverse('dashboard-records'), {**params, 'bucket': 'lt_60'}).json()
        self.assertEqual([r['site_id'] for r in below['records']], ['UVMP003'])
        by_name = self.client.get(reverse('dashboard-records'), {'scope': 'all', 'search': 'ci west'}).json()
        self.assertEqual({r['ci_name'] for r in by_name['records']}, {'CI West'})

    def period(self, **params):
        return self.client.get(reverse('dashboard-period'), {'report_type': '4G Saturation', 'circle': 'MP',
                                                             'scope': 'all', **params})

    def test_period_kpi_matches_mtd_and_monthly_overall(self):
        mtd = self.client.get(reverse('dashboard-summary'), {'report_type': '4G Saturation', 'circle': 'MP', 'scope': 'all'}).json()
        whole_month = self.period(period='range').json()
        self.assertEqual(whole_month['label'], '01 Oct – 03 Oct')
        self.assertEqual(whole_month['uptime_pct'], mtd['metrics']['mtd_uptime_pct'])
        self.assertEqual(whole_month['sites_below_60'], mtd['metrics']['sites_below_60_mtd'])
        monthly = self.client.get(reverse('dashboard-monthly'), {'report_type': '4G Saturation', 'circle': 'MP', 'scope': 'all'}).json()
        months = self.period(period='months').json()
        self.assertEqual(months['uptime_pct'], monthly['overall']['uptime_pct'])
        self.assertEqual((months['label'], months['months']), ('Jun-26 – Oct-26 MTD (3 months)', 3))

    def test_period_kpi_for_picked_dates_weeks_and_months(self):
        # 1 and 3 Oct for MP 4G (all sites): Alpha 0 + 1440, Bravo 72 + 0, Charlie 1440 + 1440 over 6 site-days.
        days = self.period(period='days', days='2026-10-03,2026-10-01').json()
        self.assertEqual((days['label'], days['days_reported']), ('01 Oct, 03 Oct', 2))
        self.assertEqual(days['uptime_pct'], round(100 * (1 - 4392 / (1440 * 6)), 4))
        self.assertEqual(days['outage_minutes'], 4392)
        self.assertEqual((days['sites_below_60'], days['sites_at_or_above_98_5']), (2, 0))  # Alpha 50%, Charlie 0%; Bravo 97.5%
        week = self.period(period='weeks', weeks='1').json()
        self.assertEqual((week['label'], week['days_reported']), ('Week 1', 3))
        sep = self.period(period='months', months='2026-09').json()
        # Sep-26: 4,320 minutes over 2 sites with a value x 30 days; Charlie (blank) is not counted.
        self.assertEqual((sep['label'], sep['days_reported'], sep['sites_reported']), ('Sep-26', 0, 2))
        self.assertEqual(sep['uptime_pct'], 95.0)
        self.assertEqual(sep['sites_below_60'], 0)

    def test_period_parameters_are_validated(self):
        self.assertEqual(self.period(period='months', months='2025-01').status_code, 400)
        self.assertEqual(self.period(period='weeks', weeks='5').status_code, 400)
        self.assertEqual(self.period(period='days', days='').status_code, 400)
        self.assertEqual(self.period(period='days', days='14-10-2026').status_code, 400)

    def test_team_group_is_validated(self):
        self.assertEqual(self.client.get(reverse('dashboard-teams'), {'group': 'boss'}).status_code, 400)

    def test_daily_bucket_distribution(self):
        data = self.client.get(reverse('dashboard-breakdowns'), {'scope': 'all', 'reporting_date': '2026-10-01'}).json()
        counts = {b['id']: b['count'] for b in data['daily_buckets']}
        # 1 Oct uptimes: 100, 95, 0, 100, 80, 100, 100 (%)
        self.assertEqual(counts, {'lt_60': 1, '60_90': 1, '90_97': 1, '97_98_5': 0, 'gte_98_5': 4})


@override_settings()
class RunnerIsolationTests(SimpleTestCase):
    def test_tests_never_use_the_real_workbook_store(self):
        self.assertNotEqual(Path(settings.WORKBOOK_STORE_DIR), Path(settings.REAL_WORKBOOK_STORE_DIR))
