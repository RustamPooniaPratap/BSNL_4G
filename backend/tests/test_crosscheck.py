"""Cross-check of the dashboard's calculations against the workbook's own summary sheets.

Dashboard values are worked out by hand from DEFAULT_SITES (1-3 Oct reported).
"""
import tempfile
from datetime import date, datetime
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from apps.dashboard import crosscheck, metrics, workbook

from .auth_helpers import SignedInTestCase
from .workbook_factory import write_workbook

MP_MTD = 1 - 1656 / 8640  # On-Air MP: Alpha + Bravo, 1-3 Oct (80.83%)
SUMMARY_SHEETS = {
    'Summ': [
        [],
        [None, '4G saturation - UpTime Details', None, None, 'Overall Up-Time', None, 'O&M Start - Up-Time'],
        [None, 'Circle', 'Total Site count', 'On-Air Done', 'Oct-26 MTD', 'O&M Start Site count', 'Oct-26 MTD',
         None, 'Circle', 'Sep-26'],  # a second table to the right must not be read as part of this one
        [None, 'MP', 3, 3, MP_MTD, 1, 1 - 1584 / 4320, None, 'MP', 0.5],  # D4: On-Air count is 2, not 3
        [None, 'Grand Total', 4, 3, 0.99, 2, 1 - 1584 / 8640],  # E5: 99% vs 87.22% (1656 / (1440 x 9))
    ],
    'Day wise Trend': [
        [],
        [None, 'Day wise Uptime Trend - Over On-Air Sites'],
        [None, 'Circle', 'On-Air ', 'Week-1 (1-7) Oct-26', 'Week-2 (8-14) Oct-26',
         datetime(2026, 10, 1), datetime(2026, 10, 2), datetime(2026, 10, 4)],
        # Week 1 is only partly reported and week 2 / 4 Oct not at all (the workbook shows 100%): skipped.
        [None, 'MP', 2, 0.9, 1, 0.979, 0.94, 1],  # F4: 97.5% vs 97.9% (within 0.5 pts); G4: 95% vs 94%
    ],
}


class CrossCheckTests(SignedInTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._tmp = tempfile.TemporaryDirectory()
        path = write_workbook(Path(cls._tmp.name) / 'master.xlsx', summary_sheets=SUMMARY_SHEETS)
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

    def test_figures_are_found_by_label(self):
        figures = crosscheck.find_figures(self.ds)
        self.assertEqual(len(figures), 12)  # Summ: 2 rows x 5 columns; Day wise Trend: 2 reported days
        cells = {f.cell: f for f in figures if f.sheet == 'Summ'}
        self.assertEqual((cells['E4'].metric, cells['E4'].scope), ('mtd', 'on_air'))
        self.assertEqual((cells['G4'].metric, cells['G4'].scope), ('mtd', 'om_start'))
        self.assertIsNone(cells['E5'].circle)  # Grand Total
        self.assertNotIn('J4', cells)
        trend_cells = {f.cell for f in figures if f.sheet == 'Day wise Trend'}
        self.assertEqual(trend_cells, {'F4', 'G4'})  # partial week, empty week and unreported 4 Oct skipped

    def test_major_differences_are_listed_counts_first(self):
        check = crosscheck.calculation_check(self.ds)
        self.assertEqual(check['checked'], 12)
        self.assertEqual(check['sheets'], ['Day wise Trend', 'Summ'])
        self.assertEqual([(d['sheet'], d['cell']) for d in check['differences']],
                         [('Summ', 'D4'), ('Summ', 'E5'), ('Day wise Trend', 'G4')])
        count, mtd, day = check['differences']
        self.assertEqual((count['workbook'], count['dashboard'], count['difference']), (3, 2, -1))
        self.assertEqual(count['description'], 'MP · 4G On-Air sites')
        self.assertEqual((mtd['workbook'], mtd['dashboard']), (99.0, 87.22))
        self.assertEqual(day['description'], 'MP · 4G On-Air uptime on 02 Oct')
        self.assertEqual(day['difference'], 1.0)

    def test_mismatch_is_a_critical_alert(self):
        alert = next(a for a in metrics.alerts(self.ds, date(2026, 10, 4)) if a['id'] == 'calculation_mismatch')
        self.assertEqual(alert['severity'], 'critical')
        self.assertEqual(alert['title'], "3 workbook figures differ from the dashboard's calculation")
        self.assertEqual(alert['detail'], 'Largest: Summ!D4 MP · 4G On-Air sites: workbook 3, dashboard 2.')
        self.assertEqual(alert['link'], '/data-source#calculation-check')

    def test_source_endpoint_includes_the_check(self):
        data = self.client.get(reverse('dashboard-source')).json()
        self.assertEqual(data['calculation_check']['difference_count'], 3)
        with mock.patch('apps.dashboard.views.timezone.localdate', return_value=date(2026, 10, 4)):
            alerts = self.client.get(reverse('dashboard-alerts')).json()
        self.assertEqual(alerts['alerts'][0]['id'], 'calculation_mismatch')


class NoSummarySheetsTests(SimpleTestCase):
    def test_workbook_without_summary_tables_has_nothing_to_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            ds = workbook.load_dataset(write_workbook(Path(tmp) / 'master.xlsx'))
        check = crosscheck.calculation_check(ds)
        self.assertEqual((check['checked'], check['difference_count']), (0, 0))
        self.assertNotIn('calculation_mismatch', [a['id'] for a in metrics.alerts(ds, date(2026, 10, 4))])


class FormulaScopeTests(SimpleTestCase):
    """The population of a Summ MTD cell comes from the site-count column its formula divides by."""
    COUNTS = {'C': 'all', 'D': 'on_air', 'L': 'om_start'}

    def test_denominator_decides_the_scope(self):
        scope = crosscheck._denominator_scope
        # Summ!K17: all LWE MP outage over Total Site count (C) -> all sites, not On-Air.
        self.assertEqual(scope("1-SUMIFS('Up-Time Report'!BQ:BQ,'Up-Time Report'!$B:$B,$B17)/(1440*14*$C17)", self.COUNTS, 17), 'all')
        self.assertEqual(scope('1-BL15/(1440 *$D33*14)', self.COUNTS, 33), 'on_air')  # Summ!K33
        self.assertEqual(scope('1-BY15/(1440*$L33*14)', self.COUNTS, 33), 'om_start')
        self.assertIsNone(scope('1-BL15/(1440*$D33*$C33)', self.COUNTS, 33))  # ambiguous
        self.assertIsNone(scope('0.95', self.COUNTS, 33))
        self.assertIsNone(scope(None, self.COUNTS, 33))

    def test_shared_formulas_are_expanded_down_a_column(self):
        from apps.dashboard.workbook import _shift_rows
        self.assertEqual(_shift_rows('1-BL12/(1440 *$D30*14)', 3), '1-BL15/(1440 *$D33*14)')
        # Absolute rows, other sheets' column ranges and function names stay unchanged.
        self.assertEqual(_shift_rows("SUMIFS('Up-Time Report'!BQ:BQ,$A$4)+LOG10(B2)", 1), "SUMIFS('Up-Time Report'!BQ:BQ,$A$4)+LOG10(B3)")
