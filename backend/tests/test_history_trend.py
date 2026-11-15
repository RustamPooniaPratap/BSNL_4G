"""Historical monthly totals (historical_import) in the dashboard's monthly trend, kept out of every operational KPI.

Synthetic sites with daily records for Sep and Oct 2026 (calculated months) and imported historical totals before them.
"""
import tempfile
from datetime import date
from pathlib import Path

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.scope import set_pairs
from apps.sitedata import calculations, history_trend, portfolio
from apps.sitedata.models import MonthlySitePerformance, Technology, UploadBatch
from tests.auth_helpers import portal_user
from tests.sitedata_factory import batch as make_batch
from tests.sitedata_factory import make_daily, make_site

HIST = MonthlySitePerformance.Category.HISTORICAL_IMPORT
G4, LWE = Technology.G4, Technology.LWE
OCT25, NOV25, DEC25, JAN26, AUG26, SEP26, OCT26 = (date(2025, 10, 1), date(2025, 11, 1), date(2025, 12, 1), date(2026, 1, 1), date(2026, 8, 1),
                                                   date(2026, 9, 1), date(2026, 10, 1))
VOLATILE = {'source', 'loaded_at', 'generated_at'}


def strip(value):
    """A response without the fields that change on every load (timestamps of the dataset)."""
    if isinstance(value, dict):
        return {k: strip(v) for k, v in value.items() if k not in VOLATILE}
    if isinstance(value, list):
        return [strip(v) for v in value]
    return value


class TrendTestCase(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        override = override_settings(SITEDATA_STAGING_DIR=str(Path(self._tmp.name) / 'staged'))
        override.enable()
        self.addCleanup(override.disable)
        self.admin = portal_user('trend-admin', 'admin')
        self.mp = make_site('UVMPBPL00012', technology=G4, circle='MP', on_air_date=date(2025, 1, 1))
        self.rj = make_site('UVRJJPR00001', technology=G4, circle='RJ', on_air_date=None)  # no On-Air date: still a historical value
        self.bh = make_site('LWEBH0063', technology=LWE, circle='BH', on_air_date=date(2026, 3, 1))
        for site in (self.mp, self.rj, self.bh):
            for day in (date(2026, 9, 1), date(2026, 9, 2), date(2026, 10, 1), date(2026, 10, 2), date(2026, 11, 1)):
                make_daily(site, day, 60)
        calculations.calculate_month(SEP26)
        calculations.calculate_month(OCT26)
        portfolio.clear_cache()
        self.upload = make_batch(UploadBatch.Kind.UPTIME_HISTORY)
        self.client.force_login(self.admin)

    def hist(self, site, month, outage, *, revision=1, current=True, note='on_air_whole_month'):
        days = 31 if month.month in (1, 3, 5, 7, 8, 10, 12) else 30 if month.month != 2 else 28
        return MonthlySitePerformance.objects.create(
            site=site, month=month, technology=site.technology, calculation_category=HIST, total_outage_minutes=outage,
            availability_pct=100 * (1 - outage / (1440 * days)), reporting_days=None, calendar_days=days, effective_from=month,
            import_batch=self.upload, revision=revision, is_current=current, source_values={'on_air_note': note})

    def load_history(self):
        self.hist(self.mp, OCT25, 4464)        # 10% down over 31 days
        self.hist(self.rj, OCT25, 0, note='no_on_air_date')
        self.hist(self.mp, NOV25, 0)
        # Dec-25: no record at all (missing month)
        self.hist(self.mp, JAN26, 2232)
        self.hist(self.bh, JAN26, 446.4, note='before_on_air')  # LWE begins in Jan-26
        self.hist(self.mp, AUG26, 0)

    def monthly(self, **params):
        response = self.client.get(reverse('dashboard-monthly'), {'scope': 'on_air', 'reporting_date': '2026-11-01', **params})
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()


class MonthlyTrendTests(TrendTestCase):
    def test_historical_months_come_first_and_the_calculated_months_follow_without_duplicates(self):
        self.load_history()
        self.hist(self.mp, SEP26, 999)  # a historical total in a calculated month is never shown
        data = self.monthly()
        hist = data['historical_months']
        self.assertEqual([m['key'] for m in hist], ['2025-10', '2025-11', '2026-01', '2026-08'])  # Dec-25 stays missing
        self.assertEqual({m['source'] for m in hist}, {'historical_import'})
        self.assertEqual([(m['key'], m['source']) for m in data['months'] if not m['partial']], [('2026-09', 'daily_derived'), ('2026-10', 'daily_derived')])
        self.assertTrue(all(h['key'] < data['months'][0]['key'] for h in hist))
        self.assertEqual(data['sources']['historical_import'], 'Historical monthly (Excel source)')

    def test_availability_is_outage_weighted_over_site_minutes_without_reporting_days(self):
        self.load_history()
        oct25 = self.monthly(report_type=G4)['historical_months'][0]
        # MP 4464 min + RJ 0 min over 2 sites x 31 days: 100 x (1 - 4464 / (1440 x 62)) = 95.0
        self.assertEqual((oct25['uptime_pct'], oct25['outage_minutes'], oct25['sites_reported']), (95.0, 4464.0, 2))
        self.assertEqual(oct25['by_circle'], {'4G Saturation|MP': 90.0, '4G Saturation|RJ': 100.0})
        self.assertEqual(oct25['on_air_notes'], {'on_air_whole_month': 1, 'no_on_air_date': 1})  # imported as reported, noted

    def test_4g_and_lwe_start_in_different_months_and_a_combined_figure_needs_both(self):
        self.load_history()
        hist = {m['key']: m for m in self.monthly()['historical_months']}
        self.assertEqual(hist['2025-10']['by_report_type']['LWE'], None)          # no LWE history before Jan-26: a gap, not 0
        self.assertIsNone(hist['2025-10']['uptime_pct'])                          # combined would be 4G only: left empty
        self.assertEqual(hist['2025-10']['missing_report_types'], ['LWE'])
        self.assertEqual(hist['2026-01']['by_report_type']['LWE'], 99.0)
        self.assertIsNotNone(hist['2026-01']['uptime_pct'])
        lwe = self.monthly(report_type=LWE)['historical_months']
        self.assertEqual([m['key'] for m in lwe], ['2026-01'])

    def test_circle_filter_and_only_current_revisions(self):
        self.load_history()
        MonthlySitePerformance.objects.filter(site=self.mp, month=OCT25, calculation_category=HIST).update(is_current=False)
        self.hist(self.mp, OCT25, 0, revision=2)  # the current revision
        mp = self.monthly(report_type=G4, circle='MP')['historical_months']
        self.assertEqual([(m['key'], m['uptime_pct'], m['sites_reported']) for m in mp][0], ('2025-10', 100.0, 1))
        rj = self.monthly(report_type=G4, circle='RJ')['historical_months']
        self.assertEqual([m['key'] for m in rj], ['2025-10'])

    def test_a_user_sees_only_the_historical_values_of_their_circles(self):
        self.load_history()
        ci = portal_user('trend-ci', 'ci')
        set_pairs(ci, [(LWE, 'BH')])
        self.client.force_login(ci)
        data = self.monthly()
        self.assertEqual([(m['key'], m['sites_reported']) for m in data['historical_months']], [('2026-01', 1)])
        options = self.client.get(reverse('dashboard-filters')).json()
        self.assertEqual([m['key'] for m in options['history_months']], ['2026-01'])

    def test_filter_options_list_historical_months_apart_from_the_calculated_months(self):
        self.load_history()
        before = self.client.get(reverse('dashboard-filters')).json()
        self.assertEqual([m['key'] for m in before['history_months']], ['2025-10', '2025-11', '2026-01', '2026-08'])
        self.assertNotIn('2025-10', [m['key'] for m in before['months']])  # period KPIs never get a historical month
        bad = self.client.get(reverse('dashboard-period'), {'scope': 'on_air', 'period': 'months', 'months': '2025-10'})
        self.assertEqual(bad.status_code, 400)

    def test_a_team_site_filter_has_no_historical_points(self):
        self.load_history()
        params = {'team_group': 'ci', 'team': 'Nobody', 'team_project': G4, 'team_circle': 'MP'}
        response = self.client.get(reverse('dashboard-monthly'), {'scope': 'on_air', 'reporting_date': '2026-11-01', **params})
        if response.status_code == 200:
            self.assertEqual(response.json()['historical_months'], [])

    def test_no_historical_records_means_no_historical_points(self):
        self.assertEqual(self.monthly()['historical_months'], [])
        self.assertEqual(history_trend.month_options(None, SEP26), [])


class OperationalKpiTests(TrendTestCase):
    """The same responses before and after historical records exist: no KPI reads them."""

    ENDPOINTS = (
        ('dashboard-summary', {'scope': 'on_air', 'reporting_date': '2026-11-01'}),
        ('dashboard-period', {'scope': 'on_air', 'period': 'months'}),
        ('dashboard-trends', {'scope': 'on_air'}),
        ('dashboard-breakdowns', {'scope': 'on_air', 'reporting_date': '2026-11-01'}),
        ('dashboard-thresholds', {'scope': 'on_air', 'reporting_date': '2026-11-01'}),
        ('allkpis-summary', {'date_from': '2026-09-01', 'date_to': '2026-11-01'}),
        ('allkpis-trends', {'date_from': '2026-09-01', 'date_to': '2026-11-01'}),
        ('site-portfolio-summary', {}),
    )

    def snapshot(self):
        out = {}
        for name, params in self.ENDPOINTS:
            response = self.client.get(reverse(name), params)
            out[name] = (response.status_code, strip(response.json()) if response.status_code == 200 else None)
        return out

    def test_kpis_all_kpis_and_portfolio_are_unchanged_by_historical_records(self):
        before = self.snapshot()
        self.assertTrue(all(code == 200 for code, _ in before.values()), {k: v[0] for k, v in before.items()})
        self.load_history()
        portfolio.clear_cache()
        after = self.snapshot()
        for name in before:
            with self.subTest(endpoint=name):
                self.assertEqual(after[name], before[name])
        monthly_before = strip(self.monthly())
        self.assertTrue(monthly_before['historical_months'])
        months_only = {k: v for k, v in monthly_before.items() if k not in ('historical_months', 'sources')}
        MonthlySitePerformance.objects.filter(calculation_category=HIST).update(is_current=False)
        unchanged = {k: v for k, v in strip(self.monthly()).items() if k not in ('historical_months', 'sources')}
        self.assertEqual(unchanged, months_only)  # the calculated months and overall figure do not depend on history

    def test_calculated_monthly_results_are_unchanged(self):
        calculated = list(MonthlySitePerformance.objects.exclude(calculation_category=HIST).order_by('id')
                          .values_list('id', 'total_outage_minutes', 'reporting_days', 'revision', 'is_current'))
        self.load_history()
        calculations.calculate_month(SEP26)
        calculations.calculate_month(OCT26)
        self.assertEqual(list(MonthlySitePerformance.objects.exclude(calculation_category=HIST).order_by('id')
                              .values_list('id', 'total_outage_minutes', 'reporting_days', 'revision', 'is_current')), calculated)
