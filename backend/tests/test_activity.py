"""On-Air / O&M Start activity per month from the escalation matrix (Data/reference)."""
import tempfile
from datetime import date, datetime
from pathlib import Path

from django.test import SimpleTestCase, override_settings
from openpyxl import Workbook

from apps.dashboard import activity

HEADER = ['SL', 'Entity', 'Site Type', 'Circle Name', 'BSNL Site ID', 'Site Name/Village Name', 'O&M Status', 'O&M Start Date',
          'Site On Air Status', 'Site On Air Date', 'IE Contact']
ROWS = [
    ['4G Saturation', 'Madhya Pradesh', 'MP1', 'Yes', datetime(2026, 9, 1), 'Yes', datetime(2026, 9, 10)],
    ['4G Saturation', 'Odisha', 'OD1', 'Yes', datetime(2026, 9, 15), 'Yes', datetime(2026, 8, 20)],
    ['LWE', 'Jharkhand', 'JH1', 'Yes', datetime(2026, 8, 1), 'Yes', datetime(2026, 8, 3)],
    ['LWE', 'Bihar', 'BH1', None, 'NO', 'Yes', datetime(2026, 9, 25)],
    ['VI-HPSC', 'Delhi-NCR', 'VI1', 'Yes', datetime(2026, 9, 1), 'Yes', datetime(2026, 9, 1)],  # not a dashboard site
]


class ActivityTests(SimpleTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        folder = Path(self.tmp.name) / 'reference'
        folder.mkdir()
        book = Workbook()
        book.active.title = 'Summary'
        ws = book.create_sheet('Raw Data')
        ws.append([None, None, None, None, 5])  # totals row above the header, as in the real file
        ws.append(HEADER)
        for i, (entity, circle, site, om, om_date, on, on_date) in enumerate(ROWS, 1):
            ws.append([i, entity, entity, circle, site, 'x', om, om_date, on, on_date, '9999999999'])
        book.save(folder / "Consolidated Escalation Matrix _Oct'26.xlsx")
        override = override_settings(DATA_DIR=Path(self.tmp.name))
        override.enable()
        self.addCleanup(override.disable)
        activity._cache.update(key=None, value=None)

    def test_counts_sites_by_the_month_of_their_dates(self):
        r = activity.monthly_activity(date(2026, 9, 1))
        self.assertEqual((r['month']['label'], r['previous_month']['label'], r['sites']), ('Sep-26', 'Aug-26', 4))
        self.assertEqual((r['om_start']['this_month']['count'], r['om_start']['last_month']['count'], r['om_start']['change']), (2, 1, 1))
        self.assertEqual((r['on_air']['this_month']['count'], r['on_air']['last_month']['count'], r['on_air']['change']), (2, 2, 0))
        self.assertEqual(r['om_start']['latest_date'], '2026-09-15')  # "NO" is no date, not counted

    def test_a_month_the_file_does_not_cover_is_not_zero(self):
        r = activity.monthly_activity(date(2026, 10, 1))
        self.assertIsNone(r['on_air']['this_month']['count'])
        self.assertIsNone(r['on_air']['change'])
        self.assertEqual(r['on_air']['last_month']['count'], 2)

    def test_filters_by_project_and_circle_code(self):
        self.assertEqual(activity.monthly_activity(date(2026, 9, 1), 'LWE')['on_air']['this_month']['count'], 1)
        self.assertEqual(activity.monthly_activity(date(2026, 9, 1), '4G Saturation', 'OD')['om_start']['this_month']['count'], 1)
        self.assertEqual(activity.monthly_activity(date(2026, 9, 1), circle='BH')['om_start']['this_month']['count'], 0)

    def test_missing_file_is_reported(self):
        for p in (Path(self.tmp.name) / 'reference').iterdir():
            p.unlink()
        with self.assertRaises(activity.ActivityUnavailable):
            activity.monthly_activity(date(2026, 9, 1))
