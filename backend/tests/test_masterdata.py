"""Master Data explorer on the data layer (apps.sitedata): registered datasets only, server-side filters, periods,
sorting, paging, scope and exports. Synthetic records in the test database."""
import csv
import io
from datetime import date

from django.test import TestCase
from django.urls import reverse
from openpyxl import load_workbook

from apps.accounts.scope import set_pairs
from apps.rca.models import RcaRecord
from apps.sitedata.models import MonthlySitePerformance
from tests.auth_helpers import portal_user
from tests.sitedata_factory import make_daily, make_site


class MasterDataTests(TestCase):
    def setUp(self):
        self.sites = {}
        for technology, circle, sid in (('4G Saturation', 'MP', 'UVMP1'), ('4G Saturation', 'OD', 'UVOD1'), ('LWE', 'MP', 'LWEMP1')):
            self.sites[sid] = make_site(sid, technology=technology, circle=circle, site_name=f'{sid} name', ci_name='CI A', ci_contact='9999900000',
                                        il_name='IL A', il_contact='8888800000')
        self.outside = make_site('STMP1', circle='MP', outside_scope=True)
        for day, minutes in ((date(2026, 10, 1), 10), (date(2026, 10, 9), 20), (date(2026, 9, 30), 30)):
            for s in self.sites.values():
                make_daily(s, day, minutes)
        MonthlySitePerformance.objects.create(
            site=self.sites['UVMP1'], month=date(2026, 9, 1), technology='4G Saturation', calculation_category=MonthlySitePerformance.Category.DAILY_DERIVED,
            total_outage_minutes=30, availability_pct=97.9, reporting_days=1, calendar_days=30, effective_from=date(2026, 9, 1))
        MonthlySitePerformance.objects.create(
            site=self.sites['UVMP1'], month=date(2026, 8, 1), technology='4G Saturation', calculation_category=MonthlySitePerformance.Category.DAILY_DERIVED,
            total_outage_minutes=0, availability_pct=100, reporting_days=1, calendar_days=31, effective_from=date(2026, 8, 1), is_current=False)
        RcaRecord.objects.create(reporting_date=date(2026, 10, 9), project='LWE', project_raw='LWE', circle='MP', circle_raw='MP', site_id='LWEMP1',
                                 site_key='LWEMP1', final_bucket='BSNL Media', final_bucket_key='bsnl media', bucket_2='Fluctuation', bucket_2_key='fluctuation',
                                 rca_text='x', rca_key='x')
        self.admin = portal_user('md-admin', 'admin')
        self.client.force_login(self.admin)

    def get(self, key, **params):
        response = self.client.get(reverse('master-records', args=[key]), params)
        self.assertEqual(response.status_code, 200, response.content[:300])
        return response.json()

    def test_only_registered_business_datasets(self):
        keys = [d['key'] for d in self.client.get(reverse('master-datasets')).json()['datasets']]
        self.assertEqual(keys, ['uptime_sites', 'uptime_daily', 'uptime_monthly', 'escalation', 'rca'])
        for key in ('auth_user', 'django_session', 'accountprofile'):
            self.assertEqual(self.client.get(reverse('master-records', args=[key])).status_code, 404)

    def test_site_master_lists_every_matrix_site_with_its_attributes(self):
        sites = self.get('uptime_sites', sort='-site_id')
        self.assertEqual((sites['total'], [r['site_id'] for r in sites['rows']]), (4, ['UVOD1', 'UVMP1', 'STMP1', 'LWEMP1']))
        outside = next(r for r in sites['rows'] if r['site_id'] == 'STMP1')
        self.assertEqual((outside['project'], outside['reporting_scope'], outside['present_in_latest_matrix']), ('', 'outside_scope', True))
        mp = next(r for r in sites['rows'] if r['site_id'] == 'UVMP1')
        self.assertEqual((mp['project'], mp['circle'], mp['on_air_date'], mp['ci_name']), ('4G Saturation', 'MP', '2025-01-01', 'CI A'))
        self.assertEqual(self.get('uptime_sites', project='LWE')['total'], 1)
        self.assertEqual(self.get('uptime_sites', reporting_scope='outside_scope')['total'], 1)
        self.assertEqual(self.get('uptime_sites', q='uvod')['total'], 1)

    def test_daily_records_with_sorting_and_paging(self):
        page = self.get('uptime_daily', period='overall', page_size=2, page=2, sort='date')
        self.assertEqual((page['total'], page['pages'], len(page['rows'])), (9, 5, 2))
        row = self.get('uptime_daily', period='daily', year=2026, month=10, date='2026-10-01', site_id='UVMP1')['rows'][0]
        self.assertEqual((row['project'], row['circle'], row['outage_minutes'], row['source'], row['revision']), ('4G Saturation', 'MP', 10, 'uptime_master', 1))
        self.assertAlmostEqual(row['availability_pct'], 100 * (1 - 10 / 1440))
        self.assertEqual(self.client.get(reverse('master-records', args=['uptime_daily']), {'sort': 'password'}).status_code, 400)

    def test_period_views_use_the_portal_weeks(self):
        self.assertEqual(self.get('uptime_daily', period='daily', year=2026, month=10)['total'], 6)
        self.assertEqual(self.get('uptime_daily', period='daily', year=2026, month=10, date='2026-10-09')['total'], 3)
        self.assertEqual(self.get('uptime_daily', period='weekly', year=2026, month=10, week=2)['total'], 3)  # days 8-14
        self.assertEqual(self.get('uptime_daily', period='monthly', year=2026, month_from=9, month_to=9)['total'], 3)
        self.assertEqual(self.get('uptime_daily', period='overall', date_from='2026-10-01')['total'], 6)
        rca = self.get('rca', period='weekly', year=2026, month=10, week=2)
        self.assertEqual((rca['total'], rca['rows'][0]['final_bucket']), (1, 'BSNL Media'))

    def test_monthly_shows_the_current_results_only(self):
        rows = self.get('uptime_monthly', period='overall')['rows']
        self.assertEqual([(r['month'], r['site_id'], r['project'], r['outage_minutes']) for r in rows], [('2026-09-01', 'UVMP1', '4G Saturation', 30)])

    def test_escalation_matrix_comes_from_the_site_master(self):
        rows = self.get('escalation', site_id='UVMP1')['rows']
        self.assertEqual((rows[0]['ci_name'], rows[0]['il_name'], rows[0]['il_contact'], rows[0]['entity']), ('CI A', 'IL A', '8888800000', '4G Saturation'))

    def test_ci_users_see_their_pairs_and_no_phone_numbers(self):
        ci = portal_user('md-ci', 'ci')
        set_pairs(ci, [('4G Saturation', 'MP')])
        self.client.force_login(ci)
        rows = self.get('uptime_sites')['rows']
        self.assertEqual([r['site_id'] for r in rows], ['UVMP1'])  # not MP LWE, not OD, not outside the dashboard scope
        self.assertNotIn('ci_contact', rows[0])
        self.assertEqual([r['site_id'] for r in self.get('uptime_daily', period='overall')['rows']], ['UVMP1'] * 3)
        self.assertEqual(self.client.get(reverse('master-options', args=['uptime_sites'])).json()['projects'], ['4G Saturation'])
        cols = next(d for d in self.client.get(reverse('master-datasets')).json()['datasets'] if d['key'] == 'escalation')['columns']
        self.assertFalse(any(c['key'].endswith('_contact') for c in cols))
        self.assertNotIn('il_contact', self.get('escalation')['rows'][0])
        self.assertEqual(self.get('rca')['total'], 0)
        self.client.force_login(self.admin)
        self.assertEqual(self.get('uptime_sites', site_id='UVMP1')['rows'][0]['ci_contact'], '9999900000')

    def test_exports_follow_the_filters_and_columns(self):
        response = self.client.get(reverse('master-export', args=['uptime_daily']), {'period': 'daily', 'year': 2026, 'month': 10, 'project': 'LWE',
                                                                                     'columns': 'date,site_id,outage_minutes', 'file': 'csv'})
        lines = list(csv.reader(io.StringIO(b''.join(response.streaming_content).decode('utf-8-sig'))))
        self.assertEqual(lines[0], ['Reporting date', 'Site ID', 'Outage minutes'])
        self.assertEqual(len(lines) - 1, 2)
        xlsx = self.client.get(reverse('master-export', args=['uptime_sites']), {'project': '4G Saturation', 'file': 'xlsx'})
        book = load_workbook(io.BytesIO(xlsx.content))
        self.assertEqual(book.active.max_row - 1, 2)
        escalation = self.client.get(reverse('master-export', args=['escalation']), {'file': 'csv'})
        self.assertEqual(len(list(csv.reader(io.StringIO(b''.join(escalation.streaming_content).decode('utf-8-sig'))))) - 1, 4)

    def test_options_are_read_from_the_data(self):
        o = self.client.get(reverse('master-options', args=['uptime_daily'])).json()
        self.assertEqual((o['projects'], o['circles']), (['4G Saturation', 'LWE'], ['MP', 'OD']))
        self.assertEqual(o['months'], [{'year': 2026, 'month': 9}, {'year': 2026, 'month': 10}])
        self.assertEqual(o['choices']['source'], ['uptime_master'])
