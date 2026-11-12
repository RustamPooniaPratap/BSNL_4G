"""Business-rule tests. Expected values are worked out by hand from DEFAULT_SITES."""
import tempfile
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from django.test import SimpleTestCase, override_settings

from apps.dashboard import metrics, workbook
from apps.dashboard.metrics import Selection

from .workbook_factory import write_workbook

OCT1, OCT2, OCT3 = date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3)


class MetricsTestCase(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._tmp = tempfile.TemporaryDirectory()
        path = write_workbook(Path(cls._tmp.name) / 'master.xlsx')
        workbook.clear_cache()
        with override_settings(MASTER_WORKBOOK_PATH=str(path)):
            cls.ds = workbook.get_dataset()

    @classmethod
    def tearDownClass(cls):
        workbook.clear_cache()
        cls._tmp.cleanup()
        super().tearDownClass()


class UptimeFormulaTests(SimpleTestCase):
    def test_uptime_is_outage_weighted(self):
        self.assertEqual(metrics.uptime_pct(1440, 2), 50.0)
        self.assertEqual(metrics.uptime_pct(0, 5), 100.0)
        self.assertIsNone(metrics.uptime_pct(0, 0))

    def test_bucket_thresholds_match_workbook_formula(self):
        values = np.array([98.5, 98.49, 97.0, 96.99, 90.0, 60.0, 59.99, np.nan])
        self.assertEqual(
            list(metrics.bucket_ids(values)),
            ['gte_98_5', '97_98_5', '97_98_5', '90_97', '90_97', '60_90', 'lt_60', None],
        )


class SummaryTests(MetricsTestCase):
    def test_selected_circle_daily_and_mtd_uptime(self):
        result = metrics.summary(self.ds, Selection('4G Saturation', 'MP', 'on_air'), OCT3)
        m = result['metrics']
        self.assertEqual(m['sites_total'], 3)
        self.assertEqual(m['sites_in_scope'], 2)
        mp = self.ds.sites[(self.ds.sites['report_type'] == '4G Saturation') & (self.ds.sites['circle'] == 'MP')]
        self.assertEqual(m['sites_converted'], int((mp['on_air'] & mp['om_start']).sum()))
        self.assertLessEqual(m['sites_converted'], m['sites_in_scope'])  # never more than the On-Air sites
        self.assertEqual(m['daily_uptime_pct'], 50.0)  # 1440 / (1440 x 2)
        self.assertEqual(m['daily_outage_minutes'], 1440)
        self.assertEqual(m['mtd_uptime_pct'], round(100 * (1 - 1656 / 8640), 4))
        self.assertEqual(m['sites_down_full_day'], 1)
        self.assertEqual(m['sites_without_outage'], 1)
        self.assertEqual(result['mtd_window'], {'start': '2026-10-01', 'end': '2026-10-03',
                                                'days_reported': 3, 'days_missing': []})

    def test_all_circles_include_every_report_type_and_exclude_missing_values(self):
        m = metrics.summary(self.ds, Selection(None, None, 'on_air'), OCT3)['metrics']
        self.assertEqual(m['sites_in_scope'], 5)
        self.assertEqual(m['sites_reported'], 4)
        self.assertEqual(m['sites_missing'], 1)
        self.assertEqual(m['coverage_pct'], 80.0)
        self.assertEqual(m['daily_uptime_pct'], 75.0)  # missing site is not counted as 100%

    def test_overview_kpis_sla_sites_down_and_outage_comparison(self):
        result = metrics.summary(self.ds, Selection(None, None, 'on_air'), OCT3)
        m = result['metrics']
        # SLA: sites with an MTD value below 98.5%, the complement of the 98.5% bucket over the same population.
        self.assertEqual(m['sites_not_meeting_sla_mtd'], m['sites_with_mtd_value'] - m['sites_at_or_above_98_5_mtd'])
        self.assertGreaterEqual(m['sites_not_meeting_sla_mtd'], m['sites_below_60_mtd'])
        c = result['outage_comparison']
        day = c['day']  # 3 Oct against 2 Oct
        self.assertEqual((day['period'], day['previous_period']), ('03 Oct', '02 Oct'))
        expected = metrics.period_summary(self.ds, Selection(None, None, 'on_air'), dates=[OCT3 - timedelta(days=1)], label='')['outage_minutes']
        self.assertEqual(day['previous'], expected)
        self.assertEqual(day['direction'], None if day['current'] is None else
                         'same' if day['current'] == expected else 'down' if day['current'] < expected else 'up')
        self.assertIsNone(c['month']['change_pct'])  # October is not complete: no direction, no %
        self.assertIsNone(c['month']['direction'])
        self.assertTrue(c['month']['note'])

    def test_circle_filter_spans_report_types_after_alias_normalisation(self):
        m = metrics.summary(self.ds, Selection(None, 'MP', 'all'), OCT1)['metrics']
        self.assertEqual(m['sites_in_scope'], 4)
        self.assertEqual(m['daily_uptime_pct'], 68.75)  # (0+72+1440+288) / (1440 x 4)

    def test_scopes(self):
        counts = {scope: metrics.summary(self.ds, Selection(None, None, scope), OCT1)['metrics']['sites_in_scope']
                  for scope in metrics.SCOPES}
        self.assertEqual(counts, {'on_air': 5, 'om_start': 5, 'all': 7})

    def test_report_type_filter(self):
        m = metrics.summary(self.ds, Selection('LWE', None, 'all'), OCT3)['metrics']
        self.assertEqual(m['sites_in_scope'], 3)
        self.assertEqual(m['daily_uptime_pct'], 99.5)  # 14.4 / (1440 x 2)

    def test_mtd_buckets(self):
        m = metrics.summary(self.ds, Selection('4G Saturation', 'MP', 'all'), OCT3)['metrics']
        # Alpha 63.3% (60-90), Bravo 98.3% (97-98.5), Charlie 0% (<60)
        self.assertEqual(m['sites_below_60_mtd'], 1)
        self.assertEqual(m['sites_at_or_above_98_5_mtd'], 0)


class TrendTests(MetricsTestCase):
    def test_daily_series_with_unreported_dates_as_null(self):
        result = metrics.trend(self.ds, Selection(None, None, 'on_air'), OCT1, date(2026, 10, 5))
        series = result['series']
        self.assertEqual([p['date'] for p in series][-1], '2026-10-05')
        self.assertEqual(series[1]['uptime_pct'], 88.0)  # 864 / (1440 x 5)
        self.assertEqual(series[2]['sites_reported'], 4)
        self.assertFalse(series[3]['reported'])
        self.assertIsNone(series[3]['uptime_pct'])
        self.assertEqual(series[0]['by_report_type'], {
            '4G Saturation': round(100 * (1 - 72 / 4320), 4),
            'LWE': 90.0,
        })

    def test_a_week_in_progress_shows_its_figures_as_not_complete(self):
        # Week 1 has 3 of its 7 days reported: its figures are shown, not complete (approved rule B-4; a workbook source
        # has no coverage information, so its status is None; Complete / Provisional are tested in test_reporting_status).
        selection = Selection('4G Saturation', None, 'on_air')
        weeks = metrics.trend(self.ds, selection, OCT1, OCT3)['weeks']
        mtd = metrics.summary(self.ds, selection, OCT3)['metrics']['mtd_uptime_pct']
        self.assertEqual((weeks[0]['days_reported'], weeks[0]['complete'], weeks[0]['uptime_pct'], weeks[0]['status']), (3, False, mtd, None))
        self.assertIsNone(weeks[1]['uptime_pct'])
        self.assertEqual(weeks[3]['days_in_week'], 10)


class OutageByPeriodTests(MetricsTestCase):
    def test_daily_and_weekly_outage_split_by_report_type(self):
        result = metrics.trend(self.ds, Selection(None, None, 'on_air'), OCT1, date(2026, 10, 4))
        day1 = result['series'][0]
        # 1 Oct On-Air: 4G Alpha 0 + Bravo 72 + Delta 0; LWE Echo 288 + Foxtrot 0
        self.assertEqual(day1['outage_by_report_type'], {'4G Saturation': 72, 'LWE': 288})
        self.assertEqual(day1['outage_minutes'], 360)
        self.assertEqual(result['series'][3]['outage_by_report_type'], {'4G Saturation': None, 'LWE': None})  # not reported
        week1 = result['weeks'][0]  # 3 of 7 days: in progress, its week-to-date outage is shown (not complete)
        self.assertFalse(week1['complete'])
        self.assertEqual(week1['outage_minutes'], sum(week1['outage_by_report_type'].values()))
        self.assertIsNone(result['weeks'][1]['outage_minutes'])  # no data is not zero


class CircleSeriesTests(MetricsTestCase):
    def test_trend_has_one_series_per_circle_and_network_using_the_same_formula(self):
        result = metrics.trend(self.ds, Selection(None, None, 'on_air'), OCT1, date(2026, 10, 4))
        keys = [c['key'] for c in result['circles']]
        self.assertIn('4G Saturation|MP', keys)
        self.assertIn('LWE|MP', keys)  # MP 4G and MP LWE stay separate
        for point in result['series']:
            for key, value in point['by_circle'].items():
                rows = metrics.circle_rows(self.ds, np.flatnonzero(metrics.scope_mask(self.ds, Selection(None, None, 'on_air'))))[key]
                column = self.ds.position(date.fromisoformat(point['date']))
                expected = metrics.uptime_pct(*metrics._window(self.ds.outage[rows, column])) if point['reported'] else None
                self.assertEqual(value, expected, (point['date'], key))
        self.assertTrue(all(v is None for v in result['series'][3]['by_circle'].values()))  # 4 Oct not reported: None, not 0
        self.assertEqual(set(result['weeks'][0]['by_circle']), set(keys))

    def test_report_type_and_circle_filters_limit_the_series(self):
        lwe = metrics.trend(self.ds, Selection('LWE', None, 'on_air'), OCT1, OCT3)
        self.assertTrue(all(c['report_type'] == 'LWE' for c in lwe['circles']))
        months = metrics.monthly(self.ds, Selection('4G Saturation', 'MP', 'all'), OCT3)
        self.assertEqual([c['key'] for c in months['circles']], ['4G Saturation|MP'])
        self.assertEqual(months['months'][-1]['by_circle']['4G Saturation|MP'], months['months'][-1]['by_report_type']['4G Saturation'])


class WeeklyComparisonTests(MetricsTestCase):
    def test_weeks_split_by_report_type_with_change(self):
        weeks = metrics.trend(self.ds, Selection(None, None, 'on_air'), OCT1, OCT3)['weeks']
        first = weeks[0]  # in progress (3 of 7 days): its figures per report type are shown, not complete
        summary = {t: metrics.summary(self.ds, Selection(t, None, 'on_air'), OCT3)['metrics']['mtd_uptime_pct'] for t in ('4G Saturation', 'LWE')}
        self.assertEqual((first['by_report_type'], first['complete']), (summary, False))
        self.assertIsNone(first['change_pts'])  # nothing earlier to compare with
        self.assertIsNone(weeks[1]['change_pts'])  # week 2 has no data
        self.assertEqual(weeks[1]['by_report_type'], {'4G Saturation': None, 'LWE': None})


class BreakdownAndTableTests(MetricsTestCase):
    def test_breakdown_groups_by_report_type_and_circle(self):
        result = metrics.breakdown(self.ds, Selection(None, None, 'all'), OCT3)
        keys = [(c['report_type'], c['circle']) for c in result['circles']]
        self.assertEqual(keys, [('4G Saturation', 'MP'), ('4G Saturation', 'RJ'),
                                ('LWE', 'BH'), ('LWE', 'MP'), ('LWE', 'OD')])
        mp = result['circles'][0]
        self.assertEqual(mp['buckets']['lt_60'], 1)
        self.assertEqual(sum(b['count'] for b in result['buckets']), 7)

    def test_site_table_search_sort(self):
        table = metrics.site_table(self.ds, Selection(None, None, 'all'), OCT3)
        self.assertEqual(len(metrics.search_sites(table, 'bravo')), 1)
        self.assertEqual(len(metrics.search_sites(table, 'uvmp')), 3)
        self.assertEqual(len(metrics.search_sites(table, bucket='lt_60')), 1)
        ordered = metrics.sort_sites(table, 'outage_minutes', descending=True)
        self.assertEqual(list(ordered['site_id'][:2]), ['UVMP001', 'UVMP003'])
        self.assertEqual(ordered['site_id'].iloc[-1], 'LWEOD01')  # missing value sorts last


class TeamNameTests(SimpleTestCase):
    def test_blank_dash_and_zero_are_unassigned(self):
        names = metrics.team_names(pd.Series([' Asha ', '', '-', '0', None]))
        self.assertEqual(list(names), ['Asha', 'Unassigned', 'Unassigned', 'Unassigned', 'Unassigned'])

    def test_team_counts_are_distinct_people_ignoring_case_and_spaces(self):
        sites = pd.DataFrame({'ci_name': ['Asha', 'asha ', 'Ravi', '-'], 'ie_name': ['A  Kumar', 'a kumar', '', 'Meena']})
        self.assertEqual(metrics.team_counts(sites), {'ci_count': 2, 'sites_without_ci': 1, 'ie_count': 2, 'sites_without_ie': 1})

    def test_breakdown_counts_teams_per_circle_and_people_once_in_totals(self):
        with tempfile.TemporaryDirectory() as tmp:
            ds = workbook.load_dataset(write_workbook(Path(tmp) / 'master.xlsx'))
        result = metrics.breakdown(ds, Selection(None, None, 'all'), OCT3)
        for c in result['circles']:
            names = ds.sites[(ds.sites['report_type'] == c['report_type']) & (ds.sites['circle'] == c['circle'])]
            self.assertEqual(c['ci_count'], metrics.team_counts(names)['ci_count'])
        self.assertEqual(result['team_totals']['all'], metrics.team_counts(ds.sites))
        self.assertLessEqual(result['team_totals']['all']['ci_count'], sum(c['ci_count'] for c in result['circles']))


# 1-3 Sep outage per DEFAULT_SITES row (Alpha, Bravo, Charlie, Delta, Echo, Foxtrot, Golf).
SEPTEMBER = [[0, 0, 0, 0], [1440, 0, 0], [0, 0, 0], [720, 0, 0], [0, 0, 0], [0, 0, 0], [0]]


class SameDaysComparisonTests(SimpleTestCase):
    def load(self, **kwargs):
        with tempfile.TemporaryDirectory() as tmp:
            return workbook.load_dataset(write_workbook(Path(tmp) / 'master.xlsx', **kwargs))

    def test_conversion_against_the_previous_months_om_start_flag(self):
        from tests.workbook_factory import DEFAULT_SITES
        # Sep-26 O&M Start = Yes on every On-Air site except the first; blank or 0 is "not recorded".
        sep = ['Yes' if on_air == 'Yes' and i else ('0' if i % 2 else '') for i, (_, _, _, _, on_air, _, _) in enumerate(DEFAULT_SITES)]
        ds = self.load(monthly={'O&M Start - Sep-26': sep})
        result = metrics.summary(ds, Selection(None, None, 'all'), OCT3)
        on_air = ds.sites['on_air'].to_numpy(dtype=bool)
        expected = int((on_air & ds.sites['om_start_previous'].to_numpy(dtype=bool)).sum())
        self.assertEqual(result['previous_month_conversion'], {'label': 'Sep-26', 'sites_converted': expected})
        self.assertEqual(expected, sum(1 for i, s in enumerate(DEFAULT_SITES) if s[4] == 'Yes' and i))
        # Without the column nothing is estimated.
        self.assertIsNone(metrics.summary(self.load(), Selection(None, None, 'all'), OCT3)['previous_month_conversion'])

    def test_previous_month_columns_before_october_do_not_change_the_reporting_month(self):
        ds = self.load(september=SEPTEMBER)
        self.assertEqual((ds.month_label, ds.dates[0], ds.latest_date), ('Oct-26', date(2026, 10, 1), OCT3))
        self.assertEqual([h['label'] for h in ds.daily_history], ['Sep-26'])
        self.assertIn('daily_history', {w['code'] for w in ds.warnings})

    def test_circle_comparison_uses_the_same_days_of_the_previous_month(self):
        ds = self.load(september=SEPTEMBER)
        result = metrics.breakdown(ds, Selection('4G Saturation', None, 'all'), date(2026, 10, 2))
        self.assertEqual(result['comparison'], {'key': '2026-09', 'label': 'Sep-26', 'available': True,
                                                'start': '2026-09-01', 'end': '2026-09-02', 'days_reported': 2})
        mp = next(c for c in result['circles'] if c['circle'] == 'MP')
        # Sep 1-2, MP 4G (Alpha, Bravo, Charlie): 1,440 minutes over 6 site-days; Oct 1-2: 0+144, 72+0, 1440+1440.
        self.assertEqual(mp['previous_uptime_pct'], round(100 * (1 - 1440 / (1440 * 6)), 4))
        self.assertEqual(mp['mtd_uptime_pct'], round(100 * (1 - 3096 / (1440 * 6)), 4))
        self.assertEqual(mp['mtd_change_pts'], round(mp['mtd_uptime_pct'] - mp['previous_uptime_pct'], 2))
        rj = next(c for c in result['circles'] if c['circle'] == 'RJ')
        self.assertEqual(rj['previous_uptime_pct'], 75.0)  # Delta: 720 of 2 days
        self.assertEqual((mp['mtd_outage_minutes'], mp['previous_outage_minutes']), (3096.0, 1440.0))

    def test_period_summary_reads_the_same_days_of_the_previous_month(self):
        ds = self.load(september=SEPTEMBER)
        sep = metrics.period_summary(ds, Selection('4G Saturation', 'MP', 'all'), dates=[date(2026, 9, 1), date(2026, 9, 2)], label='Sep 1-2')
        # Same figures as the circle comparison: 1,440 minutes over 6 site-days.
        self.assertEqual((sep['first_date'], sep['last_date'], sep['days_reported']), ('2026-09-01', '2026-09-02', 2))
        self.assertEqual(sep['uptime_pct'], round(100 * (1 - 1440 / (1440 * 6)), 4))
        self.assertEqual(sum(sep['buckets'].values()), sep['sites_reported'])
        self.assertEqual(metrics.filter_options(ds)['daily_history'][0]['key'], '2026-09')

    def test_without_previous_daily_data_nothing_is_estimated(self):
        result = metrics.breakdown(self.load(), Selection(None, None, 'all'), OCT3)
        self.assertEqual((result['comparison']['label'], result['comparison']['available']), ('Sep-26', False))
        self.assertTrue(all(c['previous_uptime_pct'] is None and c['mtd_change_pts'] is None for c in result['circles']))
        self.assertTrue(all(c['previous_outage_minutes'] is None for c in result['circles']))

    def test_without_previous_daily_data_a_previous_month_period_is_empty(self):
        ds = self.load()
        sep = metrics.period_summary(ds, Selection(None, None, 'all'), dates=[date(2026, 9, 1)], label='Sep 1')
        self.assertEqual((sep['days_reported'], sep['uptime_pct'], sep['first_date']), (0, None, None))
        self.assertEqual(metrics.filter_options(ds)['daily_history'], [])

    def test_period_summary_counts_every_bucket(self):
        ds = self.load()
        result = metrics.period_summary(ds, Selection(None, None, 'on_air'), dates=[OCT1, date(2026, 10, 2), OCT3], label='1-3 Oct')
        self.assertEqual(set(result['buckets']), {'lt_60', '60_90', '90_97', '97_98_5', 'gte_98_5'})
        self.assertEqual(sum(result['buckets'].values()), result['sites_reported'])
        self.assertEqual((result['buckets']['lt_60'], result['buckets']['gte_98_5']), (result['sites_below_60'], result['sites_at_or_above_98_5']))

    def test_uptime_fractions_are_not_read_as_outage_minutes(self):
        ds = self.load(september=SEPTEMBER, september_as_uptime=True)
        self.assertEqual(ds.daily_history, ())
        self.assertIn('history_not_minutes', {w['code'] for w in ds.warnings})


# (project, circle, site, name, On-Air, O&M Start, outage minutes on 1-3 Oct); None = no value reported that day.
USD_SITES = [
    ('4G Satu.', 'MP', 'UVMP101', 'One minute', 'Yes', 'Yes', [1, 0, 0]),         # 1 minute once: counted
    ('4G Satu.', 'MP', 'UVMP102', 'Many days', 'Yes', 'Yes', [100, 200, 300]),    # down on every day: counted once
    ('4G Satu.', 'MP', 'UVMP103', 'One bad day', 'Yes', None, [0, 0, 5]),         # up on most days: counted
    ('4G Satu.', 'MP', 'UVMP104', 'Always up', 'Yes', 'Yes', [0, 0, 0]),          # never down: not counted
    ('4G Satu.', 'MP', 'UVMP105', 'Not reported', 'Yes', None, [None, None, None]),  # missing is not zero and not down
    ('4G Satu.', 'MP', 'UVMP106', 'Inactive', None, 'Yes', [500, 500, 500]),      # not On-Air: out of count and denominator
    ('4G Satu.', 'RJ', 'UVRJ101', 'Rajasthan', 'Yes', 'Yes', [0, 30, 0]),
    ('LWE', 'MP', 'LWEMP101', 'LWE one', 'Yes', 'Yes', [10, 0, 0]),
]


class UniqueSitesDownTests(SimpleTestCase):
    """USD: distinct active sites with outage > 0 at least once in the period, over every active site of the selection."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._tmp = tempfile.TemporaryDirectory()
        path = write_workbook(Path(cls._tmp.name) / 'usd.xlsx', USD_SITES)
        workbook.clear_cache()
        with override_settings(MASTER_WORKBOOK_PATH=str(path)):
            cls.ds = workbook.get_dataset()

    @classmethod
    def tearDownClass(cls):
        workbook.clear_cache()
        cls._tmp.cleanup()
        super().tearDownClass()

    def usd(self, selection=Selection(), days=(1, 2, 3)):
        dates = [date(2026, 10, d) for d in days]
        return metrics.period_summary(self.ds, selection, dates=dates, label='')['unique_sites_down']

    def test_counts_each_site_once_and_only_active_sites(self):
        # 4G MP: UVMP101, 102, 103 down; 104 up; 105 unreported; 106 inactive (excluded from both values).
        self.assertEqual(self.usd(Selection('4G Saturation', 'MP', 'all')), {'count': 3, 'eligible_sites': 5, 'pct': 60.0})
        self.assertEqual(self.usd(Selection('4G Saturation', 'MP')), {'count': 3, 'eligible_sites': 5, 'pct': 60.0})

    def test_projects_and_circles_are_separate_and_never_double_counted(self):
        self.assertEqual(self.usd(Selection('LWE', 'MP'))['count'], 1)
        self.assertEqual(self.usd(Selection('4G Saturation', 'RJ'))['count'], 1)
        everything = self.usd()
        self.assertEqual(everything, {'count': 5, 'eligible_sites': 7, 'pct': 71.43})  # 3 + 1 (RJ) + 1 (LWE MP)

    def test_om_start_scope_uses_the_same_population_for_count_and_denominator(self):
        # O&M Start = Yes and active: UVMP101, 102, 104 (+ RJ, LWE); UVMP103 and 105 have no O&M Start.
        self.assertEqual(self.usd(Selection('4G Saturation', 'MP', 'om_start')), {'count': 2, 'eligible_sites': 3, 'pct': 66.67})

    def test_the_reporting_period_decides_without_summing_daily_counts(self):
        self.assertEqual(self.usd(Selection('4G Saturation', 'MP'), days=(1,))['count'], 2)   # 101, 102
        self.assertEqual(self.usd(Selection('4G Saturation', 'MP'), days=(3,))['count'], 2)   # 102, 103
        self.assertEqual(self.usd(Selection('4G Saturation', 'MP'), days=(1, 2, 3))['count'], 3)  # not 2 + 1 + 2

    def test_no_eligible_site_gives_no_percentage(self):
        self.assertEqual(self.usd(Selection('LWE', 'RJ')), {'count': 0, 'eligible_sites': 0, 'pct': None})
