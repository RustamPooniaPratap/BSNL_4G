"""Excel downloads: Daily Uptime Report and Full Consolidated Report (apps.dashboard.report_export).

Synthetic workbooks only (tests/workbook_factory.py). Excel mode reads the workbook; PostgreSQL mode reads the same
workbook imported into the isolated test database with the existing importer. No reference file is used.
"""
import io
import re
import tempfile
from datetime import date, datetime
from pathlib import Path

from django.test import override_settings
from django.urls import reverse
from openpyxl import load_workbook

from apps.accounts.scope import set_circles
from apps.dashboard import report_export, workbook

from .auth_helpers import SignedInTestCase, portal_user
from .workbook_factory import write_workbook

SHEETS = ['Repeated Sites', 'Summ', 'Uptime Bucketization ', 'Up-Time Report', 'Day wise Trend', 'All Circle - 98.5',
          'All Circle - Below 60', 'OD - EB & NEB', 'Signoff status', 'Bucketization', "CI's Performance", "IE's Performance",
          'One Pager Summary']
SEPTEMBER = [[10] * 30, [0] * 30, [1440] * 30, [0] * 30, [100] * 30, [0] * 30, [0] * 30]


class ExportTestCase(SignedInTestCase):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = Path(self._tmp.name)
        self.path = write_workbook(tmp / 'master.xlsx', september=SEPTEMBER,
                                   monthly={'Sep-26 Outage Min.': [sum(s) for s in SEPTEMBER]})
        for override in (override_settings(MASTER_WORKBOOK_PATH=str(self.path)), override_settings(DATA_DIR=tmp / 'data')):
            override.enable()
            self.addCleanup(override.disable)
        workbook.clear_cache()
        self.addCleanup(workbook.clear_cache)
        report_export._details_cache.update(key=None, value=None)

    def download(self, kind, expected=200, **params):
        response = self.client.get(reverse(f'dashboard-export-{kind}'), params)
        self.assertEqual(response.status_code, expected, response.content[:400])
        if expected != 200:
            return response.json()
        self.assertEqual(response['Content-Type'], report_export.XLSX)
        name = re.search(r'filename="([^"]+)"', response['Content-Disposition']).group(1)
        return name, load_workbook(io.BytesIO(response.content))

    def daily_rows(self, wb):
        ws = wb.active
        return {r[0]: r for r in ws.iter_rows(min_row=5, values_only=True)}


class DailyReportTests(ExportTestCase):
    def test_one_date_with_site_outage_availability_and_bucket_only(self):
        name, wb = self.download('daily', date='2026-10-02')
        self.assertEqual(name, 'Daily_Uptime_All_Projects_All_Circles_2026-10-02.xlsx')
        ws = wb.active
        self.assertEqual([c.value for c in ws[4]], list(report_export.DAILY_HEADER))
        self.assertEqual(ws.max_column, 8)  # no monthly, weekly or technical columns
        rows = self.daily_rows(wb)
        self.assertEqual(len(rows), 7)
        self.assertEqual({r[4] for r in rows.values()}, {datetime(2026, 10, 2)})  # exactly the selected date
        self.assertEqual(rows['UVMP001'][1:], ('Alpha', '4G Saturation', 'MP', datetime(2026, 10, 2), 144, 0.9, '>90 To <97'))
        self.assertEqual(rows['UVMP003'][5:], (1440, 0, '<60'))
        self.assertEqual(ws['G5'].number_format, '0.00%')
        self.assertEqual((ws.freeze_panes, ws.auto_filter.ref), ('A5', 'A4:H11'))

    def test_a_site_without_a_value_is_not_reported_never_zero(self):
        rows = self.daily_rows(self.download('daily', date='2026-10-03')[1])
        self.assertEqual(rows['LWEOD01'][5:], (None, None, report_export.NOT_REPORTED))

    def test_project_and_circle_filters(self):
        def ids(**params):
            return sorted(self.daily_rows(self.download('daily', date='2026-10-01', **params)[1]))
        self.assertEqual(ids(report_type='4G Saturation'), ['UVMP001', 'UVMP002', 'UVMP003', 'UVRJ001'])
        self.assertEqual(ids(circle='MP'), ['LWEMP01', 'UVMP001', 'UVMP002', 'UVMP003'])  # both projects
        self.assertEqual(ids(report_type='LWE', circle='MP'), ['LWEMP01'])
        name, _ = self.download('daily', date='2026-10-01', report_type='LWE', circle='MP')
        self.assertEqual(name, 'Daily_Uptime_LWE_MP_2026-10-01.xlsx')

    def test_an_earlier_month_date_and_missing_dates(self):
        rows = self.daily_rows(self.download('daily', date='2026-09-05')[1])
        self.assertEqual(rows['UVMP001'][4:7], (datetime(2026, 9, 5), 10, 1 - 10 / 1440))
        self.assertIn('no daily values for 20 Oct 2026', self.download('daily', 404, date='2026-10-20')['error'])
        self.download('daily', 400)  # the date is required
        self.download('daily', 400, date='2026-10-01', circle='ZZ')



class ConsolidatedReportTests(ExportTestCase):
    def test_thirteen_sheets_in_the_template_order_with_the_filtered_sites(self):
        name, wb = self.download('consolidated', reporting_date='2026-10-03')
        self.assertEqual(name, '4G_LWE_Consolidated_Report_All_Projects_All_Circles_Oct-2026_to_2026-10-03.xlsx')
        self.assertEqual(wb.sheetnames, SHEETS)
        self.assertEqual([wb[s].sheet_state for s in SHEETS], [s.sheet_state for s in load_workbook(report_export.TEMPLATE_PATH).worksheets])
        ws = wb['Up-Time Report']
        self.assertEqual([c.value for c in ws[2][:4]], ['Project', 'Circle', 'btsIpId', 'Site name'])
        self.assertEqual(sorted(ws.cell(row=r, column=3).value for r in range(3, ws.max_row + 1)),
                         ['LWEBH01', 'LWEMP01', 'LWEOD01', 'UVMP001', 'UVMP002', 'UVMP003', 'UVRJ001'])
        headers = [c.value for c in ws[2]]
        self.assertIn('Sep-26 Outage Min.', headers)
        self.assertIn('Oct-26 Outage Min.', headers)
        # Weekly outage and weekly uptime; Week 1 (3 of 7 days) is not complete: labelled Provisional, values shown.
        self.assertEqual(headers.count('Wk-1 (Provisional)'), 2)
        self.assertEqual(ws.freeze_panes, 'A3')

    def test_formulas_stay_on_their_own_row_and_inside_the_sheet(self):
        ws = self.download('consolidated', reporting_date='2026-10-03')[1]['Up-Time Report']
        last = ws.max_row
        formulas = [(c.row, c.value) for row in ws.iter_rows(min_row=1) for c in row if isinstance(c.value, str) and c.value.startswith('=')]
        self.assertTrue(formulas)
        for row, formula in formulas:
            self.assertNotIn('#REF', formula)
            for ref_row in map(int, re.findall(r'[A-Z]{1,3}(\d+)', formula.replace('1440', '').replace('%', ''))):
                self.assertTrue(ref_row == row or (row == 1 and 3 <= ref_row <= last), (row, formula))
        uptime_col = [c.value for c in ws[2]].index('Oct-26 UpTime') + 1
        self.assertRegex(ws.cell(row=3, column=uptime_col).value, r'^=IF\(COUNT\(.+\)=0,"",1-SUM\(.+\)/\(1440\*COUNT\(.+\)\)\)$')
        self.assertEqual(report_export._bucket_formula('X3'),
                         '=IF(X3="","",IF(ROUND(X3*100,6)>=98.5,">98.5",IF(ROUND(X3*100,6)>=97,">97 To <98.5",'
                         'IF(ROUND(X3*100,6)>=90,">90 To <97",IF(ROUND(X3*100,6)>=60,">60 To <90","<60")))))')

    def test_every_summary_sheet_follows_the_filters(self):
        wb = self.download('consolidated', reporting_date='2026-10-03', report_type='4G Saturation', circle='RJ')[1]
        ws = wb['Up-Time Report']
        self.assertEqual([ws.cell(row=r, column=3).value for r in range(3, ws.max_row + 1)], ['UVRJ001'])
        for sheet in ('Summ', 'Uptime Bucketization ', 'Day wise Trend', 'All Circle - 98.5', 'All Circle - Below 60', "CI's Performance", "IE's Performance"):
            texts = {c.value for row in wb[sheet].iter_rows() for c in row if isinstance(c.value, str)}
            self.assertFalse({'MP', 'LWE', 'OD', 'BH'} & texts, sheet)
            self.assertIn('RJ', ' '.join(texts), sheet)

    def test_summary_values_use_the_dashboard_rules_and_leave_unreported_periods_blank(self):
        wb = self.download('consolidated', reporting_date='2026-10-03', report_type='4G Saturation', circle='MP')[1]
        summ = wb['Summ']
        header = [c.value for c in summ[4]]
        row = [c.value for c in summ[5]]
        self.assertEqual(row[1:4], ['MP', 3, 2])  # 3 sites, 2 On-Air
        mtd = row[header.index('Oct-26 MTD')]
        # On-Air MP sites UVMP001 (0, 144, 1440) and UVMP002 (72, 0, 0): pooled over six reported site-days.
        self.assertAlmostEqual(mtd, 1 - (0 + 144 + 1440 + 72) / (1440 * 6), places=6)
        trend = wb['All Circle - 98.5']
        head = [c.value for c in trend[3]]
        self.assertIsNone(trend.cell(row=4, column=head.index('Wk-4 (Provisional)') + 1).value)  # no day of week 4 yet: blank, not 0

    def test_no_template_data_and_hand_maintained_sheets_say_so(self):
        wb = self.download('consolidated', reporting_date='2026-10-03')[1]
        for sheet in ('Repeated Sites', 'Signoff status', 'Bucketization', 'One Pager Summary'):
            texts = [c.value for row in wb[sheet].iter_rows() for c in row if isinstance(c.value, str)]
            self.assertIn(report_export.MANUAL_NOTE, texts)
            numbers = [c.value for row in wb[sheet].iter_rows() for c in row if isinstance(c.value, (int, float))]
            self.assertEqual(numbers, [], sheet)

    def test_the_reporting_date_must_be_reported(self):
        self.assertIn('No data has been reported', str(self.download('consolidated', 400, reporting_date='2026-10-20')))

    def test_the_up_time_report_sheet_lists_the_selected_project(self):
        ws = self.download('consolidated', reporting_date='2026-10-03', report_type='LWE')[1]['Up-Time Report']
        self.assertEqual(sorted(ws.cell(row=r, column=3).value for r in range(3, ws.max_row + 1)), ['LWEBH01', 'LWEMP01', 'LWEOD01'])


class ExportPermissionTests(ExportTestCase):
    def test_ci_users_export_only_their_circles(self):
        ci = portal_user('export-ci', 'ci')
        set_circles(ci, ['RJ'])
        self.client.force_login(ci)
        self.assertIn('not assigned to circle MP', self.download('daily', 403, date='2026-10-01', circle='MP')['error'])
        self.download('consolidated', 403, reporting_date='2026-10-03', circle='MP')
        rows = self.daily_rows(self.download('daily', date='2026-10-01')[1])
        self.assertEqual(sorted(rows), ['UVRJ001'])
        ws = self.download('consolidated', reporting_date='2026-10-03')[1]['Up-Time Report']
        self.assertEqual([ws.cell(row=r, column=3).value for r in range(3, ws.max_row + 1)], ['UVRJ001'])
        nobody = portal_user('export-ci-none', 'ci')
        self.client.force_login(nobody)
        self.download('daily', 403, date='2026-10-01')

    def test_signed_out_users_get_nothing(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse('dashboard-export-daily'), {'date': '2026-10-01'}).status_code, 401)


class TemplateIndependenceTests(ExportTestCase):
    def test_the_template_is_an_application_asset_without_report_data(self):
        path = report_export.TEMPLATE_PATH
        self.assertEqual(path.parent.name, 'report_templates')
        self.assertNotIn('ref', path.parts)
        wb = load_workbook(path)
        self.assertEqual(wb.sheetnames, SHEETS)
        self.assertEqual(wb['Up-Time Report'].max_row, 3)
        for ws in wb.worksheets:
            if ws.title == 'Up-Time Report':
                continue
            data = [c.coordinate for row in ws.iter_rows() for c in row
                    if isinstance(c.value, (int, float, date)) or (isinstance(c.value, str) and (c.value.startswith('=') or re.search(r'\d{10}', c.value)))]
            self.assertEqual(data, [], ws.title)
