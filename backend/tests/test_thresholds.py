"""Threshold Analysis: sites at or above 98.5% and below 60% uptime, per circle and period.

Expected values are worked out by hand from SITES below (O&M Start scope, reporting date 3 Oct).
98.5% of a day is 21.6 outage minutes; 60% is 576. For Sep-26 (30 days): 648 and 17,280.
"""
import tempfile
from datetime import date
from pathlib import Path

from unittest import mock

from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from apps.dashboard import metrics, workbook
from apps.dashboard.metrics import Selection

from .auth_helpers import SignedInTestCase
from .workbook_factory import write_workbook

SITES = [
    ('4G Satu.', 'MP', 'T1', 'Exactly 98.5', 'Yes', 'Yes', [21.6, 0, None]),
    ('4G Satu.', 'MP', 'T2', 'Just under 98.5', 'Yes', 'Yes', [21.61, 576, 0]),
    ('4G Satu.', 'MP', 'T3', 'Just under 60', 'Yes', 'Yes', [576.01, 1440, None]),
    ('4G Satu.', 'RJ', 'T4', 'Never reported', 'Yes', 'Yes', [None, None, None]),
    ('LWE', 'Odisha', 'L1', 'Always up', 'Yes', 'Yes', [0, 0, 0]),
    ('4G Satu.', 'MP', 'T5', 'Not O&M Start', 'Yes', None, [1440, 1440, 1440]),
    ('4G Satu.', 'MP', 'T1', 'Duplicate row, ignored', 'Yes', 'Yes', [1440, 1440, 1440]),
]
MONTHLY = {'Sep-26 Outage Min.': [648, 17280, 17280.01, None, 0, 0, 43200]}
OCT1, OCT2, OCT3 = '2026-10-01', '2026-10-02', '2026-10-03'


class ThresholdTestCase(SignedInTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._tmp = tempfile.TemporaryDirectory()
        path = write_workbook(Path(cls._tmp.name) / 'master.xlsx', SITES, monthly=MONTHLY)
        cls._override = override_settings(MASTER_WORKBOOK_PATH=str(path))
        cls._override.enable()
        workbook.clear_cache()
        cls.ds = workbook.get_dataset()

    @classmethod
    def tearDownClass(cls):
        cls._override.disable()
        workbook.clear_cache()
        cls._tmp.cleanup()
        super().tearDownClass()

    def analyse(self, report_type=None, circle=None, day=date(2026, 10, 3)):
        return metrics.threshold_analysis(self.ds, Selection(report_type, circle, 'om_start'), day)

    @staticmethod
    def counts(row, key):
        value = row['values'][key]
        return None if value is None else (value['gte_98_5']['count'], value['lt_60']['count'])

    def row(self, result, report_type, circle):
        return next(r for r in result['rows'] if (r['report_type'], r['circle']) == (report_type, circle))


class ThresholdBoundaryTests(ThresholdTestCase):
    def test_daily_boundaries_are_inclusive_at_98_5_and_60(self):
        mp = self.row(self.analyse(), '4G Saturation', 'MP')
        self.assertEqual(self.counts(mp, OCT1), (1, 1))  # T1 98.50% counts; T2 98.499% does not; T3 59.999% is below 60
        self.assertEqual(self.counts(mp, OCT2), (1, 1))  # T2 exactly 60.00% is not below 60; T3 0%
        self.assertEqual(self.counts(mp, OCT3), (1, 0))  # only T2 reported (100%)

    def test_monthly_boundaries(self):
        mp = self.row(self.analyse(), '4G Saturation', 'MP')
        self.assertEqual(self.counts(mp, '2026-09'), (1, 1))  # 648 min = 98.5%; 17,280 = 60%; 17,280.01 < 60%

    def test_duplicate_rows_and_other_scopes_do_not_inflate_counts(self):
        mp = self.row(self.analyse(), '4G Saturation', 'MP')
        self.assertEqual(mp['sites_in_scope'], 3)  # T1 once; T5 is not O&M Start

    def test_missing_values_are_not_counted_and_never_reported_is_none(self):
        result = self.analyse()
        mp = self.row(result, '4G Saturation', 'MP')
        self.assertEqual(mp['values'][OCT3]['sites_reported'], 1)
        rj = self.row(result, '4G Saturation', 'RJ')
        self.assertTrue(all(value is None for value in rj['values'].values()))


class ThresholdPeriodTests(ThresholdTestCase):
    def test_percentages_use_all_sites_in_scope(self):
        total = self.analyse()['total']
        self.assertEqual(total['sites_in_scope'], 5)
        day = total['values'][OCT1]
        self.assertEqual(day['sites_reported'], 4)  # T4 not reported
        self.assertEqual(day['gte_98_5'], {'count': 2, 'pct': 40.0})  # T1, L1 of 5 sites in scope
        self.assertEqual(day['lt_60'], {'count': 1, 'pct': 20.0})

    def test_mtd_and_week_windows(self):
        result = self.analyse()
        periods = {p['key']: p for p in result['periods']}
        self.assertEqual([p['kind'] for p in result['periods']], ['month', 'mtd', 'week', 'week', 'week', 'week', 'day', 'day', 'day'])
        self.assertEqual((periods['mtd']['days'], periods['mtd']['days_reported'], periods['mtd']['partial']), (3, 3, True))
        # Week 1 is in progress (3 of 7 days): no week-to-date values.
        self.assertEqual((periods['w1']['start'], periods['w1']['end'], periods['w1']['days_reported'], periods['w1']['partial']),
                         ('2026-10-01', '2026-10-07', 0, True))
        self.assertEqual((periods['w4']['end'], periods['w4']['days']), ('2026-10-31', 10))
        mp = self.row(result, '4G Saturation', 'MP')
        # MTD: T1 99.25%, T2 86.17%, T3 30.00% (reported days only)
        self.assertEqual(self.counts(mp, 'mtd'), (1, 1))
        self.assertIsNone(self.counts(mp, 'w1'))  # a week in progress has no values
        self.assertIsNone(mp['values']['w2'])  # no reported day yet

    def test_daily_columns_stop_at_the_reporting_date(self):
        keys = [p['key'] for p in self.analyse(day=date(2026, 10, 2))['periods'] if p['kind'] == 'day']
        self.assertEqual(keys, [OCT1, OCT2])
        mp = self.row(self.analyse(day=date(2026, 10, 1)), '4G Saturation', 'MP')
        self.assertEqual(self.counts(mp, 'mtd'), self.counts(mp, OCT1))

    def test_circles_reconcile_to_grand_total(self):
        result = self.analyse()
        for period in result['periods']:
            key = period['key']
            for threshold in metrics.THRESHOLDS:
                circles = sum(r['values'][key][threshold]['count'] for r in result['rows'] if r['values'][key])
                total = result['total']['values'][key]
                self.assertEqual(total[threshold]['count'] if total else 0, circles, (key, threshold))
        self.assertEqual(result['total']['sites_in_scope'], sum(r['sites_in_scope'] for r in result['rows']))

    def test_circle_and_report_type_filters(self):
        self.assertEqual([(r['report_type'], r['circle']) for r in self.analyse(circle='MP')['rows']], [('4G Saturation', 'MP')])
        lwe = self.analyse(report_type='LWE')
        self.assertEqual([r['circle'] for r in lwe['rows']], ['OD'])
        self.assertEqual(lwe['total']['values'][OCT1]['gte_98_5']['count'], 1)


class ThresholdApiTests(ThresholdTestCase):
    def test_endpoint(self):
        data = self.client.get(reverse('dashboard-thresholds'), {'scope': 'om_start', 'reporting_date': OCT2}).json()
        self.assertEqual([t['id'] for t in data['thresholds']], ['lt_60', 'gte_98_5'])
        self.assertEqual(data['reporting_date'], OCT2)
        self.assertEqual(data['filters']['scope'], 'om_start')

    def test_period_and_comparison_are_chosen_by_query_and_compared_by_the_backend(self):
        data = self.client.get(reverse('dashboard-thresholds'), {'scope': 'om_start', 'reporting_date': OCT3, 'period': OCT3, 'vs': OCT1}).json()
        self.assertEqual((data['selection']['period'], data['selection']['compare']), (OCT3, OCT1))
        change = data['total']['comparison']['below_98_5']
        self.assertEqual(change['change'], change['count'] - change['compare_count'])
        # An unknown comparison falls back to the natural one (the previous date), never to an invented period.
        fallback = self.client.get(reverse('dashboard-thresholds'), {'scope': 'om_start', 'reporting_date': OCT3, 'period': OCT3, 'vs': '1999-01'}).json()
        self.assertEqual(fallback['selection']['compare'], OCT2)

    def test_unreported_date_is_rejected(self):
        response = self.client.get(reverse('dashboard-thresholds'), {'reporting_date': '2026-10-20'})
        self.assertEqual(response.status_code, 400)

    def test_affected_sites_by_daily_or_mtd_uptime(self):
        params = {'scope': 'om_start', 'circle': 'MP', 'reporting_date': OCT3, 'bucket': 'lt_60'}
        mtd = self.client.get(reverse('dashboard-records'), params).json()
        self.assertEqual([r['site_id'] for r in mtd['records']], ['T3'])  # MTD 30%
        daily = self.client.get(reverse('dashboard-records'), {**params, 'bucket_basis': 'daily'}).json()
        self.assertEqual(daily['records'], [])  # T3 did not report on 3 Oct
        day1 = self.client.get(reverse('dashboard-records'), {**params, 'reporting_date': OCT1, 'bucket_basis': 'daily'}).json()
        self.assertEqual([r['site_id'] for r in day1['records']], ['T3'])


class AllBucketsTests(ThresholdTestCase):
    def test_every_period_has_all_five_buckets_with_their_bounds(self):
        result = self.analyse()
        self.assertEqual([(b['id'], b['lower'], b['upper']) for b in result['buckets']], [
            ('lt_60', None, 60.0), ('60_90', 60.0, 90.0), ('90_97', 90.0, 97.0), ('97_98_5', 97.0, 98.5), ('gte_98_5', 98.5, None),
        ])
        for key, value in result['total']['values'].items():
            if value:
                self.assertEqual(set(value) - {'sites_reported'}, {*metrics.BUCKET_IDS, 'below_98_5', 'no_value'}, key)

    def test_buckets_and_not_reported_add_up_to_the_population(self):
        result = self.analyse()
        for row in [*result['rows'], result['total']]:
            for key, value in row['values'].items():
                if value is None:
                    continue
                counted = sum(value[b]['count'] for b in metrics.BUCKET_IDS)
                self.assertEqual(counted, value['sites_reported'], (row['circle'], key))
                self.assertLessEqual(counted, row['sites_in_scope'])

    def test_boundaries_follow_the_workbook_formula(self):
        # 2 Oct: T1 100% (>=98.5), T2 exactly 60% (60-90, not below 60), T3 0% (<60).
        mp = self.row(self.analyse(), '4G Saturation', 'MP')['values'][OCT2]
        self.assertEqual({b: mp[b]['count'] for b in metrics.BUCKET_IDS},
                         {'lt_60': 1, '60_90': 1, '90_97': 0, '97_98_5': 0, 'gte_98_5': 1})
        # 1 Oct: T1 98.50% (>=98.5), T2 98.499% (97-98.5), T3 59.999% (<60).
        mp1 = self.row(self.analyse(), '4G Saturation', 'MP')['values'][OCT1]
        self.assertEqual({b: mp1[b]['count'] for b in metrics.BUCKET_IDS},
                         {'lt_60': 1, '60_90': 0, '90_97': 0, '97_98_5': 1, 'gte_98_5': 1})

    def test_mtd_buckets_match_the_site_bucket_breakdown(self):
        result = self.analyse()
        breakdown = metrics.breakdown(self.ds, Selection(None, None, 'om_start'), date(2026, 10, 3))
        expected = {b['id']: b['count'] for b in breakdown['buckets']}
        self.assertEqual({b: result['total']['values']['mtd'][b]['count'] for b in metrics.BUCKET_IDS}, expected)


class PenaltyAggregateTests(ThresholdTestCase):
    """Below 98.5% - Total: the buckets below the penalty threshold, summed in the backend for every period and row."""

    def test_the_aggregate_uses_the_bucket_boundaries_below_98_5(self):
        self.assertEqual(metrics.PENALTY_BUCKETS, ('lt_60', '60_90', '90_97', '97_98_5'))
        result = self.analyse()
        self.assertEqual(result['penalty'], {'id': 'below_98_5', 'label': 'Below 98.5% — Total', 'threshold': 98.5,
                                             'buckets': ['lt_60', '60_90', '90_97', '97_98_5']})

    def test_aggregate_equals_the_four_buckets_and_is_not_counted_twice(self):
        result = self.analyse()
        for row in [*result['rows'], result['total']]:
            scope = row['sites_in_scope']
            for key, value in row['values'].items():
                if value is None:
                    continue
                below = sum(value[b]['count'] for b in metrics.PENALTY_BUCKETS)
                self.assertEqual(value['below_98_5']['count'], below, (row['circle'], key))
                self.assertEqual(value['below_98_5']['pct'], round(100 * below / scope, 2))
                # Sites with no value are outside every bucket; below + 98.5%+ + no value = the population exactly.
                self.assertEqual(value['no_value']['count'], scope - value['sites_reported'])
                self.assertEqual(value['below_98_5']['count'] + value['gte_98_5']['count'] + value['no_value']['count'], scope)

    def test_exactly_98_5_is_not_below_and_missing_values_are_not_zero(self):
        total = self.analyse()['total']['values']
        # 1 Oct: T1 exactly 98.50% (not below), T2 98.499% and T3 59.999% (below), T4 never reported (no value).
        self.assertEqual((total[OCT1]['below_98_5']['count'], total[OCT1]['gte_98_5']['count'], total[OCT1]['no_value']['count']), (2, 2, 1))

    def test_the_selected_period_and_its_comparison_are_resolved_and_compared_in_the_backend(self):
        result = self.analyse()
        self.assertEqual((result['selection']['period'], result['selection']['compare']), ('mtd', '2026-09'))
        self.assertEqual(result['selection']['choices'][:2], ['mtd', '2026-09'])
        now, before = result['total']['values']['mtd'], result['total']['values']['2026-09']
        change = result['total']['comparison']['below_98_5']
        self.assertEqual((change['count'], change['compare_count']), (now['below_98_5']['count'], before['below_98_5']['count']))
        self.assertEqual(change['change'], now['below_98_5']['count'] - before['below_98_5']['count'])
        self.assertEqual(change['change_pts'], round(now['below_98_5']['pct'] - before['below_98_5']['pct'], 2))
        for row in result['rows']:  # per circle too, between the same two periods
            self.assertIn('lt_60', row['comparison'] or {'lt_60': None})
        # A date compares with the previous date by default; "none" turns the comparison off.
        day = metrics.threshold_analysis(self.ds, Selection(None, None, 'om_start'), date(2026, 10, 3), period=OCT3)
        self.assertEqual((day['selection']['period'], day['selection']['compare']), (OCT3, OCT2))
        off = metrics.threshold_analysis(self.ds, Selection(None, None, 'om_start'), date(2026, 10, 3), compare='none')
        self.assertIsNone(off['selection']['compare'])
        self.assertIsNone(off['total']['comparison'])

    def test_monthly_columns_report_a_missing_matching_month_honestly(self):
        columns = self.analyse()['monthly_comparison']['columns']
        self.assertEqual([c['key'] for c in columns], ['2026-09', '2026-09-mtd', 'mtd'])  # months found in the source
        previous = columns[1]
        self.assertEqual((previous['status'], previous['values']), ('missing', None))
        self.assertIn('no daily data', previous['reason'])
        self.assertEqual(columns[2]['values'], self.analyse()['total']['values']['mtd'])
        # No matching days in September: the MTD comparison is unavailable, never the full month instead.
        comparison = self.analyse()['monthly_comparison']['mtd_comparison']
        self.assertFalse(comparison['available'])
        self.assertTrue(all(v is None for v in comparison['values'].values()))


class MatchingDaysMonthlyTests(SimpleTestCase):
    """With September daily data, the Sep MTD column covers the same elapsed days as October (1..3)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._tmp = tempfile.TemporaryDirectory()
        september = [[0, 0, 1440, 0], [576.01, 0, 0, 0], [1440] * 4, [None] * 4, [0, 0, 0, 0], [0] * 4, [0] * 4]
        path = write_workbook(Path(cls._tmp.name) / 'master.xlsx', SITES, monthly=MONTHLY, september=september)
        cls.ds = workbook.load_dataset(path)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()
        super().tearDownClass()

    def test_previous_month_to_date_uses_the_same_elapsed_days(self):
        result = metrics.threshold_analysis(self.ds, Selection(None, None, 'om_start'), date(2026, 10, 3))
        column = next(c for c in result['monthly_comparison']['columns'] if c['kind'] == 'previous_mtd')
        self.assertEqual((column['status'], column['start'], column['end']), ('available', '2026-09-01', '2026-09-03'))
        same_days = metrics.period_summary(self.ds, Selection(None, None, 'om_start'),
                                           dates=[date(2026, 9, d) for d in (1, 2, 3)], label='Sep 1-3')
        self.assertEqual({b: column['values'][b]['count'] for b in metrics.BUCKET_IDS}, same_days['buckets'])
        self.assertEqual(column['values']['below_98_5']['count'], sum(same_days['buckets'][b] for b in metrics.PENALTY_BUCKETS))
        self.assertEqual(column['values']['no_value']['count'], same_days['sites_in_scope'] - same_days['sites_reported'])

    def test_month_to_date_is_compared_with_the_same_days_of_the_previous_month(self):
        monthly = metrics.threshold_analysis(self.ds, Selection(None, None, 'om_start'), date(2026, 10, 3))['monthly_comparison']
        now = next(c for c in monthly['columns'] if c['kind'] == 'mtd')['values']
        before = next(c for c in monthly['columns'] if c['kind'] == 'previous_mtd')['values']
        comparison = monthly['mtd_comparison']
        self.assertEqual((comparison['current'], comparison['previous'], comparison['available']), ('mtd', '2026-09-mtd', True))
        self.assertEqual(comparison['sites_reported'], {'current': now['sites_reported'], 'previous': before['sites_reported']})
        for key in ('lt_60', 'gte_98_5', 'below_98_5', 'no_value'):
            c = comparison['values'][key]
            self.assertEqual((c['count'], c['compare_count']), (now[key]['count'], before[key]['count']))
            self.assertEqual(c['change'], now[key]['count'] - before[key]['count'])
            self.assertEqual(c['change_pts'], round(now[key]['pct'] - before[key]['pct'], 2))


class CiIePerformanceTests(ThresholdTestCase):
    """NSLA (below 98.5%) per CI / IE. The factory names CI East on even rows and CI West on odd ones, and
    "IE <circle>" as the IE. O&M Start scope: CI East has T1, T3 (MP) and L1 (LWE Odisha); CI West T2 (MP), T4 (RJ)."""

    def nsla(self, group='ci', month=None, report_type=None):
        return metrics.team_monthly_nsla(self.ds, Selection(report_type, None, 'om_start'), date(2026, 10, 3), group, month)

    @staticmethod
    def cell(row, key):
        v = row['months'][key]
        return None if v is None else (v['nsla_sites'], v['nsla_pct'], v['no_value'])

    def test_months_and_rows_in_name_order_without_ranking(self):
        result = self.nsla()
        self.assertEqual([m['key'] for m in result['months']], ['2026-09', '2026-10'])
        self.assertEqual([m['kind'] for m in result['months']], ['month', 'mtd'])
        self.assertEqual(result['reporting_month'], '2026-10')
        self.assertEqual([(r['name'], r['report_type'], r['circle']) for r in result['rows']], [
            ('CI East', '4G Saturation', 'MP'), ('CI East', 'LWE', 'OD'),
            ('CI West', '4G Saturation', 'MP'), ('CI West', '4G Saturation', 'RJ')])
        self.assertNotIn('rank', result['rows'][0])

    def test_nsla_counts_per_person(self):
        rows = {(r['name'], r['circle']): r for r in self.nsla()['rows']}
        east = rows[('CI East', 'MP')]
        self.assertEqual(east['sites_in_scope'], 2)
        # MTD: T1 99.25% is within SLA, T3 is below; Sep: T1 exactly 98.5% is within SLA, T3 below.
        self.assertEqual(self.cell(east, '2026-10'), (1, 50.0, 0))
        self.assertEqual(self.cell(east, '2026-09'), (1, 50.0, 0))
        self.assertEqual(self.cell(rows[('CI West', 'MP')], '2026-10'), (1, 100.0, 0))  # T2 86.2%
        self.assertEqual(self.cell(rows[('CI East', 'OD')], '2026-10'), (0, 0.0, 0))

    def test_a_person_without_any_reported_site_has_no_value_not_zero(self):
        west_rj = next(r for r in self.nsla()['rows'] if r['circle'] == 'RJ')
        self.assertEqual(west_rj['months'], {'2026-09': None, '2026-10': None})

    def test_totals_reconcile_with_threshold_analysis(self):
        result = self.nsla()
        totals = result['totals']['months']['2026-10']
        self.assertEqual(sum(r['months']['2026-10']['nsla_sites'] for r in result['rows'] if r['months']['2026-10']),
                         totals['nsla_sites'])
        mtd = next(c for c in self.analyse()['monthly_comparison']['columns'] if c['kind'] == 'mtd')
        self.assertEqual((totals['nsla_sites'], totals['nsla_pct']),
                         (mtd['values']['below_98_5']['count'], mtd['values']['below_98_5']['pct']))
        self.assertEqual(result['totals']['sites_in_scope'], sum(r['sites_in_scope'] for r in result['rows']))

    def test_ie_view_and_project_filter(self):
        result = self.nsla('ie', report_type='4G Saturation')
        self.assertEqual([(r['name'], r['sites_in_scope']) for r in result['rows']], [('IE MP', 3), ('IE RJ', 1)])
        self.assertEqual(self.cell(result['rows'][0], '2026-10'), (2, 66.67, 0))

    def test_earlier_reporting_month_shows_it_and_the_months_before(self):
        result = self.nsla(month='2026-09')
        self.assertEqual(result['reporting_month'], '2026-09')
        self.assertEqual([m['key'] for m in result['months']], ['2026-09'])
        self.assertEqual([m['key'] for m in result['months_available']], ['2026-09', '2026-10'])
        with self.assertRaises(ValueError):
            self.nsla(month='2026-03')

    def test_rca_columns_are_reported_as_unsupported(self):
        self.assertIn('RCA', self.nsla()['unsupported'][0]['field'])

    def test_api(self):
        url = reverse('dashboard-teams-monthly')
        data = self.client.get(url, {'group': 'ie', 'scope': 'om_start'}).json()
        self.assertEqual(data['group'], 'ie')
        self.assertEqual(data['filters']['scope'], 'om_start')
        self.assertEqual(self.client.get(url, {'month': '2026-03', 'scope': 'om_start'}).status_code, 400)
        self.assertEqual(self.client.get(url, {'month': 'Oct', 'scope': 'om_start'}).status_code, 400)


class CiIePerformancePermissionTests(ThresholdTestCase):
    role = 'ci'

    def test_ci_users_cannot_open_it(self):
        self.assertEqual(self.client.get(reverse('dashboard-teams-monthly'), {'group': 'ci'}).status_code, 403)


def person(name, scope, nsla, no_value=0, circle='MP', report_type='4G Saturation'):
    value = None if no_value == scope else {'sites_reported': scope - no_value, 'nsla_sites': nsla,
                                             'nsla_pct': round(100 * nsla / scope, 2), 'no_value': no_value}
    return {'name': name, 'circle': circle, 'report_type': report_type, 'sites_in_scope': scope, 'months': {'m': value}}


class RankPeopleTests(SimpleTestCase):
    def rank(self, rows, assignments=None):
        return metrics._rank_people(rows, 'm', assignments or {})

    def test_lowest_nsla_share_first_with_competition_ties(self):
        result = self.rank([person('B', 20, 5), person('A', 10, 1), person('C', 40, 10), person('D', 30, 12)])
        self.assertEqual([(p['name'], p['rank']) for p in result['ranking']], [('A', 1), ('B', 2), ('C', 2), ('D', 4)])
        self.assertEqual((result['status'], result['top']), ('ranked', ['A']))

    def test_equal_best_share_is_a_tie_not_a_winner(self):
        result = self.rank([person('B', 10, 0), person('A', 30, 0), person('C', 10, 4)])
        self.assertEqual((result['status'], result['top']), ('tie', ['A', 'B']))

    def test_ties_use_exact_shares_not_rounded_percentages(self):
        # 1/3 and 33.33% would round alike; 333/1000 is a different share.
        result = self.rank([person('A', 30, 10), person('B', 1000, 333)])
        self.assertEqual(result['top'], ['B'])

    def test_small_incomplete_unreported_and_unassigned_are_not_ranked(self):
        result = self.rank([person('Big', 20, 10), person('Other', 12, 9), person('Small', 9, 0),
                            person('Partial', 20, 0, no_value=1), person('Silent', 15, 0, no_value=15),
                            person('Unassigned', 50, 0)])
        self.assertEqual(result['top'], ['Big'])  # Small, Partial, Silent and Unassigned all did better but are not comparable
        reasons = {p['name']: p['reason'] for p in result['ranking'] if not p['eligible']}
        self.assertIn('Fewer than 10', reasons['Small'])
        self.assertIn('Incomplete: 1 of 20', reasons['Partial'])
        self.assertIn('No assigned site reported', reasons['Silent'])
        self.assertIn('without a named person', reasons['Unassigned'])
        self.assertTrue(all(p['rank'] is None for p in result['ranking'][2:]))

    def test_one_eligible_person_is_insufficient_data(self):
        result = self.rank([person('Only', 50, 1), person('Tiny', 3, 0)])
        self.assertEqual((result['status'], result['top']), ('insufficient', []))
        self.assertEqual(result['ranking'][0]['rank'], 1)  # still listed, but not named top performer
        self.assertIn('1 of 2 eligible', result['reason'])

    def test_other_assignments_are_disclosed(self):
        result = self.rank([person('A', 20, 1), person('B', 20, 2)], {'A': ['MP 4G Saturation', 'OD LWE']})
        self.assertEqual(result['ranking'][0]['other_assignments'], ['OD LWE'])


class CircleTopPerformerTests(ThresholdTestCase):
    def top(self, **kwargs):
        with mock.patch.object(metrics, 'RANK_MIN_SITES', 1):  # the fixture's teams are tiny
            return metrics.circle_top_performers(self.ds, Selection(None, None, 'om_start'), date(2026, 10, 3), **kwargs)

    def test_ci_and_ie_ranked_separately_within_each_circle_and_project(self):
        circles = {(c['report_type'], c['circle']): c for c in self.top()['circles']}
        self.assertEqual(set(circles), {('4G Saturation', 'MP'), ('4G Saturation', 'RJ'), ('LWE', 'OD')})
        mp = circles[('4G Saturation', 'MP')]
        # MTD: CI East 1 of 2 (50%), CI West 1 of 1 (100%) -> CI East; one IE only -> insufficient.
        self.assertEqual((mp['ci']['status'], mp['ci']['top']), ('ranked', ['CI East']))
        self.assertEqual([p['nsla_pct'] for p in mp['ci']['ranking']], [50.0, 100.0])
        self.assertEqual(mp['ie']['status'], 'insufficient')
        self.assertEqual(circles[('4G Saturation', 'RJ')]['ci']['ranking'][0]['reason'], 'No assigned site reported in the period.')

    def test_values_match_the_ci_ie_performance_page(self):
        rows = metrics.team_monthly_nsla(self.ds, Selection(None, None, 'om_start'), date(2026, 10, 3), 'ci')['rows']
        east = next(r for r in rows if (r['name'], r['circle']) == ('CI East', 'MP'))['months']['2026-10']
        mp = next(c for c in self.top()['circles'] if c['circle'] == 'MP')
        self.assertEqual((mp['ci']['ranking'][0]['nsla_sites'], mp['ci']['ranking'][0]['nsla_pct']), (east['nsla_sites'], east['nsla_pct']))

    def test_circle_wise_monthly_nsla_matches_threshold_analysis_and_ranks_within_project(self):
        result = self.top()
        self.assertEqual([m['key'] for m in result['months']], ['2026-09', '2026-10'])
        circles = {(c['report_type'], c['circle']): c for c in result['circles']}
        mp = circles[('4G Saturation', 'MP')]
        self.assertEqual((mp['nsla']['2026-10']['nsla_sites'], mp['nsla']['2026-10']['nsla_pct']), (2, 66.67))
        self.assertEqual(mp['nsla']['2026-09']['nsla_sites'], 2)  # T2 and T3; T1 exactly 98.5% meets SLA
        self.assertIsNone(circles[('4G Saturation', 'RJ')]['nsla']['2026-10'])  # never reported: no value, no rank
        self.assertEqual((mp['nsla_rank'], circles[('4G Saturation', 'RJ')]['nsla_rank'], circles[('LWE', 'OD')]['nsla_rank']), (1, None, 1))
        mtd = next(c for c in self.analyse()['monthly_comparison']['columns'] if c['kind'] == 'mtd')
        total = sum(p['nsla']['2026-10']['nsla_sites'] for p in result['projects'] if p['nsla']['2026-10'])
        self.assertEqual(total, mtd['values']['below_98_5']['count'])
        g4 = next(p for p in result['projects'] if p['report_type'] == '4G Saturation')
        self.assertEqual((g4['sites_in_scope'], g4['nsla']['2026-10']['nsla_sites'], g4['nsla']['2026-10']['no_value']), (4, 2, 1))

    def test_previous_month_to_date_matches_threshold_analysis(self):
        result = self.top()
        previous = result['previous_mtd']
        columns = self.analyse()['monthly_comparison']['columns']
        before = next(c for c in columns if c['kind'] == 'previous_mtd')
        self.assertEqual((previous['key'], previous['label']), (before['key'], before['label']))
        if before['values'] is None:  # the fixture has no September daily columns: no value, never the full month
            self.assertFalse(previous['available'])
            self.assertIn('no daily data', previous['reason'])
            self.assertTrue(all(c['nsla'][previous['key']] is None for c in result['circles']))
        else:
            total = sum(p['nsla'][previous['key']]['nsla_sites'] for p in result['projects'] if p['nsla'][previous['key']])
            self.assertEqual(total, before['values']['below_98_5']['count'])
        self.assertIsNone(self.top(month='2026-09')['previous_mtd'])  # only beside a month to date

    def test_earlier_month(self):
        result = self.top(month='2026-09')
        self.assertEqual((result['reporting_month'], result['month']['label']), ('2026-09', 'Sep-26'))

    def test_api_and_permissions(self):
        self.assertEqual(self.client.get(reverse('dashboard-teams-top'), {'scope': 'om_start'}).status_code, 200)
        self.assertEqual(self.client.get(reverse('dashboard-teams-top'), {'month': '1999-01', 'scope': 'om_start'}).status_code, 400)


class CircleTopPerformerPermissionTests(ThresholdTestCase):
    role = 'ci'

    def test_ci_users_cannot_open_it(self):
        self.assertEqual(self.client.get(reverse('dashboard-teams-top')).status_code, 403)
