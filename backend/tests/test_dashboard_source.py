"""Every 4G / LWE dashboard page on the new data layer (apps.sitedata.dashboard_source): one source, one set of rules.

Synthetic Consolidation Matrix and Uptime Master files in the test database only (as tests.test_site_portfolio).
"""
from datetime import date, datetime

import numpy as np
from django.urls import reverse
from django.utils import timezone

from apps.dashboard import metrics
from apps.dashboard.metrics import Selection
from apps.sitedata import portfolio, uptime_master
from apps.sitedata.models import DailySitePerformance, Site, UploadBatch
from tests.auth_helpers import SignedInTestCase
from tests.test_site_portfolio import MATRIX, SITES
from tests.test_sitedata import SiteDataTestCase
from tests.workbook_factory import write_workbook

G4, LWE = '4G Saturation', 'LWE'
OCT3 = '2026-10-03'
DASHBOARD = ('dashboard-filters', 'dashboard-summary', 'dashboard-trends', 'dashboard-breakdowns', 'dashboard-records', 'dashboard-period',
             'dashboard-thresholds', 'dashboard-monthly', 'dashboard-teams', 'dashboard-teams-top', 'dashboard-teams-monthly')


class DashboardSourceTestCase(SignedInTestCase, SiteDataTestCase):
    def setUp(self):
        super().setUp()
        portfolio.clear_cache()
        self.addCleanup(portfolio.clear_cache)

    def load(self, sites=SITES):
        self.load_matrix(MATRIX)
        path = write_workbook(self.tmp / 'oct.xlsx', sites)
        uptime_master.commit(uptime_master.preview(path, 'oct.xlsx', user=self.admin), user=self.admin)
        portfolio.clear_cache()

    def get(self, name, expected=200, **params):
        response = self.client.get(reverse(name), params)
        self.assertEqual(response.status_code, expected, response.content[:400])
        return response.json()

    def add_day(self, day: date, sites: list[str], outage: float = 0.0):
        """Daily records of ``day`` for some sites (as an upload of only some files would add)."""
        batch = UploadBatch.objects.create(kind=UploadBatch.Kind.RAW_CSV_4G, original_filename=f'{day}.csv', processing_status='committed',
                                           committed_at=timezone.now())
        for key in sites:
            site = Site.objects.get(site_key=key)
            DailySitePerformance.objects.create(site=site, report_date=day, technology=site.technology, circle=site.circle,
                                                availability_pct=100 * (1 - outage / 1440), outage_minutes=outage, batch=batch)
        portfolio.clear_cache()


class NewLayerOnlyTests(DashboardSourceTestCase):
    def test_every_page_reads_the_new_layer(self):
        self.load()
        for name in DASHBOARD:
            params = {'group': 'ci'} if 'teams' in name else {}
            self.assertEqual(self.get(name, **params)['source']['data_layer'], 'sitedata', name)
        self.assertEqual(self.get('dashboard-summary')['reporting_date'], OCT3)
        for name in ('allkpis-summary', 'allkpis-filters'):
            self.get(name)
        self.assertEqual(self.get('allkpis-summary')['period']['end'], OCT3)

    def test_no_daily_data_in_the_layer_is_an_error(self):
        self.load_matrix(MATRIX)  # sites, but no daily records in the new layer
        portfolio.clear_cache()
        self.assertIn('new data layer', self.get('dashboard-summary', 503)['error'])


class ReportingMonthTests(DashboardSourceTestCase):
    def units(self):
        from tests.sitedata_factory import make_units
        make_units((Site.objects.filter(reporting_scope='dashboard').values_list('technology', 'circle')))
        portfolio.clear_cache()

    def test_missing_lwe_data_never_holds_back_the_4g_data(self):
        # Approved rule B-7: only the 4G CSVs of 1 Nov arrived. November is reported with the data received, labelled
        # Provisional with the missing units; nothing waits for LWE, and nothing is counted as zero.
        self.load()
        self.units()
        self.add_day(date(2026, 11, 1), ['UVMP001', 'UVRJ001'])
        filters = self.get('dashboard-filters')
        self.assertEqual((filters['default_date'], filters['source']['latest_reporting_date']), ('2026-11-01', '2026-11-01'))
        continuity = filters['source']['continuity']
        self.assertEqual((continuity['incomplete_dates'], continuity['mtd_status']), (['2026-11-01'], 'Provisional'))
        self.assertTrue({'LWE MP', 'LWE OD'} <= set(continuity['missing'][0]['units']))
        summary = self.get('dashboard-summary', scope='all', report_type=G4)
        self.assertEqual(summary['reporting_date'], '2026-11-01')
        self.assertEqual(self.get('allkpis-summary')['period']['end'], '2026-11-01')
        self.assertEqual(self.get('site-portfolio-summary', scope='all')['reporting_date'], '2026-11-01')

    def test_november_becomes_the_reporting_month_once_its_first_day_is_complete(self):
        self.load()
        self.add_day(date(2026, 11, 1), [s[2] for s in MATRIX if s[0] in (G4, LWE) and s[2] not in ('UVMP002',)])
        self.assertEqual(self.get('dashboard-filters')['default_date'], '2026-11-01')
        months = [m['key'] for m in self.get('dashboard-monthly')['months']]
        self.assertEqual(months[-2:], ['2026-10', '2026-11'])  # October is history now, from its daily records

    def test_an_incomplete_date_is_provisional_and_still_shown(self):
        # On 3 Oct no Odisha LWE site reported (LWEOD01 blank, LWEOD02 not in the file): 3 Oct is Provisional, and the
        # other units' data of 3 Oct stays visible (approved rules B-4 / B-7).
        self.load([s for s in SITES if s[2] != 'LWEOD02'])
        self.units()
        filters = self.get('dashboard-filters')
        self.assertEqual(filters['default_date'], OCT3)
        continuity = filters['source']['continuity']
        self.assertEqual((continuity['continuous_until'], continuity['excluded_after_gap']), (OCT3, []))
        status = {s['date']: s for s in continuity['date_status']}
        self.assertEqual(status[OCT3]['status'], 'Provisional')
        self.assertIn('LWE OD', status[OCT3]['missing_units'])
        self.get('dashboard-summary', 200, reporting_date=OCT3)


class WeekAndMonthRuleTests(DashboardSourceTestCase):
    def test_a_provisional_week_shows_its_figures(self):
        seven = [(p, c, sid, n, a, o, [10, 20, 30, 40, 50, 60, 70, 80]) for p, c, sid, n, a, o, _ in SITES]  # 1-8 Oct
        self.load(seven)
        weeks = self.get('dashboard-trends', scope='all')['weeks']
        sites = len(self.get('dashboard-records', scope='all')['records'])
        self.assertTrue(weeks[0]['complete'])
        self.assertEqual(weeks[0]['uptime_pct'], round(100 * (1 - (280 * sites) / (1440 * 7 * sites)), 4))
        # 8 Oct only: Week 2 is Provisional and shows its figures (approved rule B-4).
        self.assertEqual((weeks[1]['complete'], weeks[1]['status'], weeks[1]['uptime_pct'], weeks[1]['days_reported']),
                         (False, 'Provisional', round(100 * (1 - 80 / 1440), 4), 1))
        periods = {p['key']: p for p in self.get('dashboard-thresholds', scope='all')['periods']}
        self.assertEqual((periods['w1']['days_reported'], periods['w2']['days_reported'], periods['w2']['status']), (7, 1, 'Provisional'))
        period = self.get('dashboard-period', scope='all', period='weeks', weeks='1,2')
        self.assertEqual((period['days_reported'], period['status']), (8, 'Provisional'))

    def test_history_months_exclude_missing_days(self):
        # A history month from its daily records: a site with 2 of 30 reported days counts 2 days, not 30 (never zero outage).
        ds = portfolio_dataset_stub()
        outage, days, down = metrics.month_values(ds, 0, np.array([0, 1]))
        self.assertEqual((list(outage), list(days), list(down)), ([1440.0, 0.0], [2, 30], [True, False]))
        uptime = metrics.monthly(ds, Selection(None, None, 'all'), date(2026, 10, 1))['months'][0]['uptime_pct']
        self.assertEqual(uptime, metrics.uptime_pct(1440.0, 32))


class ExportTests(DashboardSourceTestCase):
    def test_exports_use_the_new_layer_sites_and_matrix_o_and_m_dates(self):
        import io

        from openpyxl import load_workbook
        self.load()
        response = self.client.get(reverse('dashboard-export-consolidated'), {'reporting_date': OCT3, 'report_type': G4})
        self.assertEqual(response.status_code, 200, response.content[:300])
        ws = load_workbook(io.BytesIO(response.content))['Up-Time Report']
        head = [c.value for c in ws[2]]
        rows = {ws.cell(row=r, column=3).value: [c.value for c in ws[r]] for r in range(3, ws.max_row + 1)}
        self.assertEqual(sorted(rows), ['UVMP001', 'UVMP002', 'UVRJ001'])  # matrix sites only (UVMP003 is not in the matrix)
        om = head.index('O&M Start - Oct-26')
        self.assertEqual((rows['UVMP001'][om], rows['UVMP002'][om]), ('Yes', 'No'))  # from the matrix O&M Start Date
        daily = self.client.get(reverse('dashboard-export-daily'), {'date': OCT3})
        self.assertEqual(daily.status_code, 200)


class ConsistencyTests(DashboardSourceTestCase):
    def test_the_same_filters_give_the_same_figures_on_every_page(self):
        self.load()
        for scope in ('all', 'on_air', 'om_start'):
            for params in ({}, {'report_type': G4}, {'report_type': LWE, 'circle': 'OD'}):
                summary = self.get('dashboard-summary', scope=scope, **params)['metrics']
                portfolio_ = self.get('site-portfolio-summary', scope=scope, **params)['metrics']
                self.assertEqual({k: summary[k] for k in ('sites_in_scope', 'mtd_uptime_pct', 'mtd_outage_minutes')},
                                 {k: portfolio_[k] for k in ('sites_in_scope', 'mtd_uptime_pct', 'mtd_outage_minutes')}, (scope, params))
                breakdown = self.get('dashboard-breakdowns', scope=scope, **params)
                self.assertEqual(sum(c['sites_in_scope'] for c in breakdown['circles']), summary['sites_in_scope'])
                self.assertEqual(sum(b['count'] for b in breakdown['buckets']), summary['sites_with_mtd_value'])
                mtd = self.get('dashboard-thresholds', scope=scope, **params)['total']['values']['mtd']
                self.assertEqual((mtd['gte_98_5']['count'], mtd['lt_60']['count']),
                                 (summary['sites_at_or_above_98_5_mtd'], summary['sites_below_60_mtd']))
        kpi = self.get('allkpis-summary')['current']
        on_air = self.get('dashboard-summary', scope='on_air')['metrics']
        self.assertEqual((kpi['on_air_sites'], kpi['availability_pct'], kpi['above_98_5_sites'], kpi['below_60_sites']),
                         (on_air['sites_in_scope'], on_air['mtd_uptime_pct'], on_air['sites_at_or_above_98_5_mtd'], on_air['sites_below_60_mtd']))
        self.assertEqual(kpi['om_start_sites'], self.get('dashboard-summary', scope='om_start')['metrics']['sites_in_scope'])


def portfolio_dataset_stub():
    """A Dataset with one history month (Sep) of daily records: site 0 reports 2 days (720 + 720), site 1 all 30 (0)."""
    import pandas as pd

    from apps.dashboard.workbook import Dataset
    sep = tuple(date(2026, 9, d) for d in range(1, 31))
    history = np.full((2, 30), np.nan)
    history[0, :2] = 720.0
    history[1, :] = 0.0
    oct_ = tuple(date(2026, 10, d) for d in range(1, 32))
    sites = pd.DataFrame({'site_id': ['A', 'B'], 'report_type': [G4, G4], 'circle': ['MP', 'MP'], 'on_air': [True, True], 'om_start': [True, True],
                          'ie_name': ['', ''], 'ci_name': ['', '']})
    return Dataset(sites=sites, outage=np.full((2, 31), np.nan), dates=oct_, reported_dates=(), month_label='Oct-26', has_om_start=True,
                   workbook_name='stub', modified_at=datetime(2026, 11, 1), loaded_at=datetime(2026, 11, 1), warnings=(),
                   months=({'label': 'Sep-26', 'start': date(2026, 9, 1), 'days': 30},), monthly_outage=np.array([[1440.0], [0.0]]),
                   daily_history=({'key': '2026-09', 'label': 'Sep-26', 'dates': sep, 'outage': history},))
