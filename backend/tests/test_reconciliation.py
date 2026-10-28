"""Reconcile dashboard metrics with values cached in the real Master workbook.

The workbook is confidential and git-ignored, so these tests are skipped when it
is not present. Expected values were read from the Oct'26 workbook's summary
sheets (cell references in docs/business-rules.md). The workbook used is
RECONCILIATION_WORKBOOK, else the active upload, else Data/reference; the
expectations below apply only to the Oct'26 file.
"""
import json
import os
from datetime import date
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.test import SimpleTestCase

from apps.dashboard import metrics, workbook
from apps.dashboard.metrics import Selection

def _october_workbook() -> Path:
    """RECONCILIATION_WORKBOOK, else the active upload in the real store, else Data/reference."""
    configured = os.getenv('RECONCILIATION_WORKBOOK')
    if configured:
        return Path(configured)
    real_store = Path(getattr(settings, 'REAL_WORKBOOK_STORE_DIR', settings.WORKBOOK_STORE_DIR))
    pointer = real_store / 'active.json'
    if pointer.is_file():
        stored = real_store / json.loads(pointer.read_text(encoding='utf-8')).get('stored_name', '')
        if stored.is_file():
            return stored
    return settings.DATA_DIR / 'reference' / "4G_LWE_Consolidated_Oct'26-Last_Changes.xlsx"


OCT_WORKBOOK = _october_workbook()
OCT14 = date(2026, 10, 14)


@skipUnless(OCT_WORKBOOK.is_file(), 'Oct\'26 Master workbook is not available')
class OctoberWorkbookReconciliationTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        workbook.clear_cache()
        cls.ds = workbook.load_dataset(OCT_WORKBOOK)

    def mtd(self, report_type, circle, scope):
        return metrics.summary(self.ds, Selection(report_type, circle, scope), OCT14)['metrics']

    def test_dataset_shape(self):
        self.assertEqual(len(self.ds.sites), 6726)
        self.assertEqual(self.ds.latest_date, OCT14)
        self.assertEqual(len(self.ds.reported_dates), 14)

    def test_summ_sheet_site_counts(self):
        # Summ!C5:D7 and L5:L7 (4G), C14:D23 and L14:L23 (LWE)
        for report_type, circle, total, on_air, om in [
            ('4G Saturation', 'MP', 1483, 1351, 1332),
            ('4G Saturation', 'RJ', 1458, 1362, 1316),
            ('4G Saturation', 'OD', 1603, 1536, 1482),
            ('LWE', 'JH', 816, 816, 800),
            ('LWE', 'MP', 22, 20, 19),
        ]:
            with self.subTest(circle=circle, report_type=report_type):
                m = self.mtd(report_type, circle, 'on_air')
                self.assertEqual((m['sites_total'], m['sites_in_scope']), (total, on_air))
                self.assertEqual(self.mtd(report_type, circle, 'om_start')['sites_in_scope'], om)

    def test_summ_sheet_mtd_uptime(self):
        # Summ!K5:K8 (On-Air) and S5:S8 (O&M Start); LWE rows 30-39 (K and S).
        for report_type, circle, scope, expected in [
            ('4G Saturation', 'MP', 'on_air', 93.07),
            ('4G Saturation', 'RJ', 'on_air', 95.43),
            ('4G Saturation', 'OD', 'on_air', 91.18),
            ('4G Saturation', None, 'on_air', 93.14),
            ('4G Saturation', 'MP', 'om_start', 93.22),
            ('4G Saturation', None, 'om_start', 93.42),
            ('LWE', 'BH', 'on_air', 96.46),
            ('LWE', 'JH', 'om_start', 92.20),
            ('LWE', 'MP', 'om_start', 97.25),
        ]:
            with self.subTest(report_type=report_type, circle=circle, scope=scope):
                self.assertAlmostEqual(self.mtd(report_type, circle, scope)['mtd_uptime_pct'], expected, places=2)

    def test_day_wise_trend_sheet(self):
        # Day wise Trend!H4 (MP, 1 Oct), H5 (RJ, 1 Oct), U6 (OD, 14 Oct)
        series = metrics.trend(self.ds, Selection('4G Saturation', None, 'on_air'), OCT14, OCT14)
        self.assertEqual(series['series'][0]['reported'], True)
        for circle, day, expected in [('MP', date(2026, 10, 1), 89.60), ('RJ', date(2026, 10, 1), 97.09),
                                      ('OD', OCT14, 88.85)]:
            with self.subTest(circle=circle, day=day):
                point = metrics.trend(self.ds, Selection('4G Saturation', circle, 'on_air'), day, day)['series'][0]
                self.assertAlmostEqual(point['uptime_pct'], expected, places=2)

    def test_uptime_bucketization_sheet(self):
        # Uptime Bucketization!C4:G6 (4G, O&M Start scope) and C11:G11 (LWE BH, all sites)
        expected = {
            ('4G Saturation', 'MP', 'om_start'): [31, 260, 288, 120, 633],
            ('4G Saturation', 'OD', 'om_start'): [69, 319, 315, 86, 693],
            ('4G Saturation', 'RJ', 'om_start'): [17, 143, 237, 136, 783],
            ('LWE', 'BH', 'all'): [1, 26, 53, 29, 141],
        }
        for (report_type, circle, scope), counts in expected.items():
            with self.subTest(circle=circle):
                result = metrics.breakdown(self.ds, Selection(report_type, circle, scope), OCT14)
                self.assertEqual([b['count'] for b in result['buckets']], counts)

    def test_summ_monthly_history(self):
        # Summ!E5:P7 divide frozen monthly outage totals (AZ:BK, pasted values) by the current
        # On-Air count. Those totals still equal the site-level monthly columns only for the
        # months below; other months were frozen under earlier On-Air flags (docs/business-rules.md).
        # The workbook counts blank months as zero outage, i.e. uptime_pct_blank_as_zero.
        for circle, label, expected in [
            ('MP', 'Oct-25', 71.08),  # E5
            ('MP', 'Nov-25', 67.97),  # F5
            ('RJ', 'Jan-26', 90.81),  # H6
            ('RJ', 'Sep-26', 93.28),  # P6
            ('OD', 'Oct-25', 68.33),  # E7
        ]:
            with self.subTest(circle=circle, month=label):
                months = metrics.monthly(self.ds, Selection('4G Saturation', circle, 'on_air'), OCT14)['months']
                month = next(m for m in months if m['label'] == label)
                self.assertAlmostEqual(month['uptime_pct_blank_as_zero'], expected, places=2)

    def test_blank_months_are_reported_separately(self):
        months = metrics.monthly(self.ds, Selection('4G Saturation', 'MP', 'on_air'), OCT14)['months']
        oct25 = next(m for m in months if m['label'] == 'Oct-25')
        self.assertEqual((oct25['sites_in_scope'], oct25['sites_reported']), (1351, 1224))
        self.assertAlmostEqual(oct25['uptime_pct'], 68.08, places=2)

    def test_threshold_sheets(self):
        # 'All Circle - 98.5' and 'All Circle - Below 60', rows 4-16 (O&M Start sites). Only cells that are
        # live COUNTIFS formulas, or that equal the site data, are compared (docs/business-rules.md).
        def counts(report_type, circle, key):
            result = metrics.threshold_analysis(self.ds, Selection(report_type, circle, 'om_start'), OCT14)
            value = result['rows'][0]['values'][key]
            return value['gte_98_5']['count'], value['lt_60']['count']

        for report_type, circle, key, expected in [
            ('4G Saturation', 'MP', 'mtd', (633, 31)),         # H4
            ('4G Saturation', 'RJ', 'mtd', (783, 17)),         # H5
            ('4G Saturation', 'OD', 'mtd', (693, 69)),         # H6
            ('4G Saturation', 'MP', 'w1', (695, 67)),          # I4
            ('4G Saturation', 'RJ', 'w2', (896, 24)),          # J5
            ('4G Saturation', 'OD', '2026-10-01', (1110, 108)),  # M6
            ('4G Saturation', 'MP', '2026-10-14', (910, 86)),  # Z4
            ('4G Saturation', 'RJ', '2026-07', (355, 35)),     # E5
            ('4G Saturation', 'RJ', '2026-09', (516, 22)),     # G5
            ('LWE', 'BH', 'w1', (146, 2)),                     # I7
            ('LWE', 'JH', '2026-10-01', (606, 49)),            # M9
            ('LWE', 'BH', '2026-10-14', (218, 0)),             # Z7
        ]:
            with self.subTest(report_type=report_type, circle=circle, period=key):
                self.assertEqual(counts(report_type, circle, key), expected)

    def test_calculation_check_uses_each_formulas_population(self):
        # Works for both Summ layouts seen: two LWE tables (MP in rows 17 and 33) or one (MP in row 18).
        from apps.dashboard import crosscheck
        check = crosscheck.calculation_check(self.ds)
        lwe_mp = [d for d in check['differences'] if d['sheet'] == 'Summ' and d['description'].startswith('MP · LWE')]
        # An all-sites cell (e.g. /(1440*14*$C17)) equals the dashboard's all-sites figure, so it is never flagged.
        self.assertAlmostEqual(self.mtd('LWE', 'MP', 'all')['mtd_uptime_pct'], 94.95, places=2)
        self.assertFalse([d for d in lwe_mp if '$C' in (d['formula'] or '')])
        # The On-Air cell divides all 22 sites' outage (BL15) by the 20 On-Air sites: a genuine inconsistency.
        self.assertEqual(len(lwe_mp), 1)
        self.assertEqual((lwe_mp[0]['workbook'], lwe_mp[0]['dashboard']), (94.44, 95.98))
        self.assertRegex(lwe_mp[0]['formula'], r'^=1-BL15/\(1440 ?\*\$D\d+\*14\)$')

    def test_threshold_page_buckets_match_uptime_bucketization(self):
        # Uptime Bucketization C4:G6 (4G, O&M Start, MTD), as in test_uptime_bucketization_sheet.
        for circle, counts in [('MP', [31, 260, 288, 120, 633]), ('OD', [69, 319, 315, 86, 693]), ('RJ', [17, 143, 237, 136, 783])]:
            with self.subTest(circle=circle):
                result = metrics.threshold_analysis(self.ds, Selection('4G Saturation', circle, 'om_start'), OCT14)
                mtd = result['rows'][0]['values']['mtd']
                self.assertEqual([mtd[b]['count'] for b in metrics.BUCKET_IDS], counts)
