import tempfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from apps.dashboard import workbook

from .auth_helpers import SignedInTestCase
from .workbook_factory import write_workbook


class DashboardApiTestCase(SignedInTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._tmp = tempfile.TemporaryDirectory()
        cls.path = write_workbook(Path(cls._tmp.name) / 'master.xlsx')
        cls._override = override_settings(MASTER_WORKBOOK_PATH=str(cls.path))
        cls._override.enable()
        workbook.clear_cache()

    @classmethod
    def tearDownClass(cls):
        cls._override.disable()
        workbook.clear_cache()
        cls._tmp.cleanup()
        super().tearDownClass()

    def get(self, name, expected_status=200, **params):
        response = self.client.get(reverse(name), params)
        self.assertEqual(response.status_code, expected_status, response.content[:500])
        return response.json()


class FiltersApiTests(DashboardApiTestCase):
    def test_filter_options_come_from_workbook(self):
        data = self.get('dashboard-filters')
        self.assertEqual([t['value'] for t in data['report_types']], ['4G Saturation', 'LWE'])
        self.assertEqual([c['value'] for c in data['circles'] if c['has_data']], ['BH', 'MP', 'OD', 'RJ'])
        # Circles of the Organization without data in this workbook are listed too, with nothing counted for them.
        self.assertEqual({c['value']: c['site_count'] for c in data['circles'] if not c['has_data']},
                         {'AP': 0, 'CG': 0, 'JH': 0, 'MH': 0, 'TL': 0, 'UP': 0, 'WB': 0})
        mp = next(c for c in data['circles'] if c['value'] == 'MP')
        self.assertEqual(mp['report_types'], ['4G Saturation', 'LWE'])
        self.assertEqual(data['default_date'], '2026-10-03')
        self.assertEqual(data['default_trend_range'], {'start': '2026-10-01', 'end': '2026-10-03'})
        self.assertEqual(data['source']['workbook'], 'master.xlsx')
        self.assertNotIn(self._tmp.name, str(data))


class SummaryApiTests(DashboardApiTestCase):
    def test_an_organization_circle_without_data_is_selectable_and_reports_nothing(self):
        for name in ('dashboard-summary', 'dashboard-trends', 'dashboard-breakdowns', 'dashboard-records', 'dashboard-thresholds', 'dashboard-monthly', 'dashboard-teams', 'dashboard-teams-top'):
            data = self.get(name, circle='AP', report_type='LWE')  # AP is an LWE circle with no site in this workbook
            self.assertEqual((data.get('filters') or {}).get('circle', 'AP'), 'AP', name)
        summary = self.get('dashboard-summary', circle='AP')
        self.assertEqual(summary['metrics']['sites_in_scope'], 0)
        self.assertIsNone(summary['metrics']['daily_uptime_pct'])  # no data: no uptime, never 0
        self.get('dashboard-summary', 400, circle='ZZ')  # not a circle at all

    def test_defaults_to_latest_date_all_circles_on_air(self):
        data = self.get('dashboard-summary')
        self.assertEqual(data['reporting_date'], '2026-10-03')
        self.assertEqual(data['filters'], {'report_type': None, 'circle': None, 'scope': 'on_air'})
        self.assertEqual(data['metrics']['sites_in_scope'], 5)
        self.assertEqual(data['metrics']['daily_uptime_pct'], 75.0)

    def test_filters_are_applied(self):
        data = self.get('dashboard-summary', report_type='4G Saturation', circle='MP', reporting_date='2026-10-03')
        self.assertEqual(data['metrics']['daily_uptime_pct'], 50.0)

    def test_workbook_spelling_of_report_type_is_accepted(self):
        data = self.get('dashboard-summary', report_type='4G Satu.')
        self.assertEqual(data['filters']['report_type'], '4G Saturation')

    def test_invalid_parameters_are_rejected(self):
        for params, field in [
            ({'circle': 'XX'}, 'circle'),
            ({'report_type': 'Unknown'}, 'report_type'),
            ({'scope': 'everything'}, 'scope'),
            ({'reporting_date': 'yesterday'}, 'reporting_date'),
            ({'reporting_date': '2026-10-20'}, 'reporting_date'),  # in the month but not reported yet
        ]:
            with self.subTest(params=params):
                data = self.get('dashboard-summary', 400, **params)
                self.assertEqual(data['error'], 'Invalid request parameters.')
                self.assertIn(field, data['details'])


class TrendBreakdownApiTests(DashboardApiTestCase):
    def test_trend_range(self):
        data = self.get('dashboard-trends', start_date='2026-10-01', end_date='2026-10-04')
        self.assertEqual(len(data['series']), 4)
        self.assertIsNone(data['series'][3]['uptime_pct'])
        self.assertEqual(data['filters']['end_date'], '2026-10-04')
        self.assertEqual(len(data['weeks']), 4)

    def test_trend_defaults_to_reported_range(self):
        data = self.get('dashboard-trends')
        self.assertEqual([p['date'] for p in data['series']], ['2026-10-01', '2026-10-02', '2026-10-03'])

    def test_trend_range_validation(self):
        self.get('dashboard-trends', 400, start_date='2026-10-05', end_date='2026-10-01')
        self.get('dashboard-trends', 400, start_date='2026-01-01', end_date='2026-10-01')

    def test_breakdown(self):
        data = self.get('dashboard-breakdowns', report_type='LWE', scope='all')
        self.assertEqual([c['circle'] for c in data['circles']], ['BH', 'MP', 'OD'])
        self.assertEqual(len(data['buckets']), 5)


class RecordsApiTests(DashboardApiTestCase):
    def test_pagination_and_sorting(self):
        data = self.get('dashboard-records', scope='all', page_size=3, sort='site_id', direction='desc')
        self.assertEqual(data['count'], 7)
        self.assertEqual(data['pages'], 3)
        self.assertEqual([r['site_id'] for r in data['records']], ['UVRJ001', 'UVMP003', 'UVMP002'])
        last = self.get('dashboard-records', scope='all', page_size=3, page=3)
        self.assertEqual(len(last['records']), 1)

    def test_search_and_bucket_filter(self):
        self.assertEqual(self.get('dashboard-records', scope='all', search='charlie')['count'], 1)
        self.assertEqual(self.get('dashboard-records', scope='all', bucket='lt_60')['count'], 1)

    def test_record_shape(self):
        record = self.get('dashboard-records', search='UVMP001')['records'][0]
        self.assertEqual(record['outage_minutes'], 1440)
        self.assertEqual(record['daily_uptime_pct'], 0.0)
        self.assertEqual(record['bucket'], '60_90')
        self.assertNotIn('ie_contact', record)

    def test_invalid_paging_is_rejected(self):
        self.get('dashboard-records', 400, page='abc')
        self.get('dashboard-records', 400, page_size=1000)
        self.get('dashboard-records', 400, sort='password')

    def test_site_detail(self):
        response = self.client.get(reverse('dashboard-record-detail', args=['LWEOD01']))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['site']['circle'], 'OD')
        self.assertEqual(data['site']['circle_as_in_workbook'], 'Odisha')
        self.assertEqual(len(data['daily']), 31)
        self.assertFalse(data['daily'][2]['reported'])

    def test_unknown_site_is_404(self):
        response = self.client.get(reverse('dashboard-record-detail', args=['NOPE']))
        self.assertEqual(response.status_code, 404)
        self.assertIn('error', response.json())


class SourceAndErrorApiTests(DashboardApiTestCase):
    def test_source_status_lists_warnings(self):
        data = self.get('dashboard-source')
        self.assertEqual(data['status'], 'warning')  # 2026-10-03 is partially reported
        self.assertEqual(data['site_counts']['by_report_type'], {'4G Saturation': 4, 'LWE': 3})
        self.assertEqual(data['missing_dates'], [])
        self.assertEqual(len(data['unreported_dates_in_month']), 28)
        self.assertIn('partial_dates', [w['code'] for w in data['warnings']])

    def test_missing_workbook_returns_503_json(self):
        with override_settings(MASTER_WORKBOOK_PATH=str(Path(self._tmp.name) / 'gone.xlsx')):
            data = self.get('dashboard-summary', 503)
        self.assertIn("'gone.xlsx' was not found", data['error'])

    def test_unexpected_error_returns_generic_500_without_trace(self):
        with mock.patch('apps.dashboard.views.metrics.summary', side_effect=KeyError('secret detail')):
            with self.assertLogs('apps.common.exceptions', level='ERROR'):
                data = self.get('dashboard-summary', 500)
        self.assertEqual(data['error'], 'An unexpected server error occurred.')
        self.assertNotIn('secret detail', str(data))
