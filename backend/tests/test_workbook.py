import os
import tempfile
from datetime import date
from pathlib import Path

from django.test import SimpleTestCase, override_settings

from apps.dashboard import workbook
from apps.dashboard import store
from apps.dashboard.workbook import WorkbookError, get_dataset, resolve_workbook

from .workbook_factory import DEFAULT_SITES, write_workbook


class WorkbookTestCase(SimpleTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        workbook.clear_cache()

    def tearDown(self):
        workbook.clear_cache()
        self._tmp.cleanup()

    def load(self, sites=None, **kwargs):
        path = write_workbook(self.tmp / 'master.xlsx', sites, **kwargs)
        with override_settings(MASTER_WORKBOOK_PATH=str(path)):
            return get_dataset()

    def warning(self, dataset, code):
        return next((w for w in dataset.warnings if w['code'] == code), None)


class WorkbookPathTests(WorkbookTestCase):
    def store_settings(self):
        return override_settings(WORKBOOK_STORE_DIR=self.tmp / 'store')

    def test_nothing_uploaded_or_configured_is_a_no_workbook_error(self):
        with self.store_settings(), override_settings(MASTER_WORKBOOK_PATH=''):
            with self.assertRaises(WorkbookError) as ctx:
                resolve_workbook()
        self.assertEqual(ctx.exception.code, 'no_workbook')
        self.assertIn('No Master workbook has been uploaded', str(ctx.exception))

    def test_reference_folder_is_not_used(self):
        write_workbook(self.tmp / 'reference' / 'master.xlsx')
        with self.store_settings(), override_settings(MASTER_WORKBOOK_PATH='', DATA_DIR=self.tmp):
            with self.assertRaises(WorkbookError):
                resolve_workbook()

    def test_missing_configured_file_is_an_error(self):
        with self.store_settings(), override_settings(MASTER_WORKBOOK_PATH=str(self.tmp / 'absent.xlsx')):
            with self.assertRaisesMessage(WorkbookError, "'absent.xlsx' was not found"):
                resolve_workbook()

    def test_active_upload_takes_precedence_over_configured_path(self):
        configured = write_workbook(self.tmp / 'configured.xlsx')
        staged = write_workbook(self.tmp / 'staged.xlsx', DEFAULT_SITES[:2])
        with self.store_settings(), override_settings(MASTER_WORKBOOK_PATH=str(configured)):
            store.activate(staged, original_name='Uploaded Master.xlsx', sha256='a' * 64)
            path, name, uploaded_at = resolve_workbook()
            self.assertEqual(name, 'Uploaded Master.xlsx')
            self.assertIsNotNone(uploaded_at)
            self.assertEqual(len(get_dataset().sites), 2)

    def test_pointer_to_deleted_file_is_ignored(self):
        staged = write_workbook(self.tmp / 'staged.xlsx')
        with self.store_settings(), override_settings(MASTER_WORKBOOK_PATH=''):
            record = store.activate(staged, original_name='m.xlsx', sha256='b' * 64)
            record['path'].unlink()
            with self.assertRaises(WorkbookError):
                resolve_workbook()

    def test_error_messages_do_not_expose_directories(self):
        with self.store_settings(), override_settings(MASTER_WORKBOOK_PATH=str(self.tmp / 'absent.xlsx')):
            with self.assertRaises(WorkbookError) as ctx:
                resolve_workbook()
        self.assertNotIn(str(self.tmp), str(ctx.exception))


class WorkbookStructureTests(WorkbookTestCase):
    def test_missing_sheet_is_an_error(self):
        path = write_workbook(self.tmp / 'master.xlsx', sheet_name='Other')
        with override_settings(MASTER_WORKBOOK_PATH=str(path)):
            with self.assertRaisesMessage(WorkbookError, "no 'Up-Time Report' sheet"):
                get_dataset()

    def test_missing_required_column_is_an_error(self):
        path = self.tmp / 'master.xlsx'
        write_workbook(path)
        from openpyxl import load_workbook
        book = load_workbook(path)
        book['Up-Time Report']['C2'] = 'Site ID'  # rename btsIpId
        book.save(path)
        with override_settings(MASTER_WORKBOOK_PATH=str(path)):
            with self.assertRaisesMessage(WorkbookError, 'missing required columns: btsIpId'):
                get_dataset()

    def test_reads_outage_block_not_derived_uptime_block(self):
        dataset = self.load()
        self.assertEqual(dataset.dates[0], date(2026, 10, 1))
        self.assertEqual(len(dataset.dates), 31)
        self.assertEqual(dataset.month_label, 'Oct-26')
        alpha = dataset.sites.index[dataset.sites['site_id'] == 'UVMP001'][0]
        self.assertEqual(list(dataset.outage[alpha, :3]), [0, 144, 1440])

    def test_reporting_dates_come_from_values_not_headers(self):
        dataset = self.load()
        self.assertEqual(dataset.reported_dates, (date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3)))
        self.assertEqual(dataset.latest_date, date(2026, 10, 3))

    def test_report_types_and_circle_aliases_are_normalised(self):
        dataset = self.load()
        self.assertEqual(sorted(dataset.sites['report_type'].unique()), ['4G Saturation', 'LWE'])
        self.assertEqual(sorted(dataset.sites['circle'].unique()), ['BH', 'MP', 'OD', 'RJ'])
        echo = dataset.sites[dataset.sites['site_id'] == 'LWEMP01'].iloc[0]
        self.assertEqual((echo['circle'], echo['circle_raw']), ('MP', 'Madhya Pradesh'))
        self.assertEqual(self.warning(dataset, 'circle_alias')['count'], 2)

    def test_scope_flags(self):
        dataset = self.load()
        on_air = set(dataset.sites.loc[dataset.sites['on_air'], 'site_id'])
        om = set(dataset.sites.loc[dataset.sites['om_start'], 'site_id'])
        self.assertEqual(on_air, {'UVMP001', 'UVMP002', 'UVRJ001', 'LWEMP01', 'LWEOD01'})
        self.assertEqual(om, {'UVMP001', 'UVRJ001', 'LWEMP01', 'LWEOD01', 'LWEBH01'})
        self.assertEqual(self.warning(dataset, 'on_air_values')['examples'], ['0'])

    def test_source_row_points_at_excel_row(self):
        dataset = self.load()
        self.assertEqual(int(dataset.sites.iloc[0]['source_row']), 3)

    def test_missing_om_start_column_disables_scope_with_warning(self):
        dataset = self.load(include_om_start=False)
        self.assertFalse(dataset.has_om_start)
        self.assertIsNotNone(self.warning(dataset, 'om_start_missing'))


class WorkbookValidationTests(WorkbookTestCase):
    def test_blank_ids_and_unknown_projects_are_excluded(self):
        sites = DEFAULT_SITES + [
            ('4G Satu.', 'MP', None, 'No ID', 'Yes', 'Yes', [0, 0, 0]),
            ('Other', 'MP', 'X1', 'Unknown', 'Yes', 'Yes', [0, 0, 0]),
        ]
        dataset = self.load(sites)
        self.assertEqual(len(dataset.sites), len(DEFAULT_SITES))
        self.assertEqual(self.warning(dataset, 'blank_site_id')['count'], 1)
        self.assertEqual(self.warning(dataset, 'unknown_project')['examples'], ['Other'])

    def test_duplicate_site_keeps_first_row(self):
        sites = DEFAULT_SITES + [('4G Satu.', 'MP', 'UVMP001', 'Alpha copy', 'Yes', 'Yes', [9, 9, 9])]
        dataset = self.load(sites)
        rows = dataset.sites[dataset.sites['site_id'] == 'UVMP001']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.iloc[0]['site_name'], 'Alpha')
        self.assertEqual(self.warning(dataset, 'duplicate_site')['count'], 1)

    def test_same_id_in_different_report_types_is_not_a_duplicate(self):
        sites = DEFAULT_SITES + [('LWE', 'MP', 'UVMP001', 'Same ID', 'Yes', 'Yes', [0, 0, 0])]
        dataset = self.load(sites)
        self.assertIsNone(self.warning(dataset, 'duplicate_site'))

    def test_non_numeric_and_out_of_range_values_are_flagged(self):
        sites = [
            ('4G Satu.', 'MP', 'A', 'A', 'Yes', 'Yes', [0, 'n/a', 0]),
            ('4G Satu.', 'MP', 'B', 'B', 'Yes', 'Yes', [2000, 0, -5]),
        ]
        dataset = self.load(sites)
        self.assertEqual(self.warning(dataset, 'non_numeric_outage')['count'], 1)
        self.assertEqual(self.warning(dataset, 'outage_out_of_range')['count'], 2)

    def test_partial_and_missing_dates_are_flagged(self):
        sites = [
            ('4G Satu.', 'MP', 'A', 'A', 'Yes', 'Yes', [0, None, 0, 0]),
            ('4G Satu.', 'MP', 'B', 'B', 'Yes', 'Yes', [0, None, None, 0]),
        ]
        dataset = self.load(sites)
        self.assertEqual(self.warning(dataset, 'missing_dates')['examples'], ['2026-10-02'])
        self.assertEqual(self.warning(dataset, 'partial_dates')['examples'], ['2026-10-03 (1 sites)'])

    def test_month_total_mismatch_is_flagged(self):
        path = write_workbook(self.tmp / 'master.xlsx')
        from openpyxl import load_workbook
        book = load_workbook(path)
        book['Up-Time Report']['L3'] = 999999  # "Oct-26 Outage Min." of the first site
        book.save(path)
        with override_settings(MASTER_WORKBOOK_PATH=str(path)):
            dataset = get_dataset()
        self.assertEqual(self.warning(dataset, 'month_total_mismatch')['examples'], ['UVMP001'])


class WorkbookCacheTests(WorkbookTestCase):
    def test_dataset_is_cached_until_file_changes(self):
        path = write_workbook(self.tmp / 'master.xlsx')
        with override_settings(MASTER_WORKBOOK_PATH=str(path)):
            first = get_dataset()
            self.assertIs(get_dataset(), first)
            write_workbook(path, DEFAULT_SITES[:2])
            stat = path.stat()
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000))
            second = get_dataset()
        self.assertIsNot(second, first)
        self.assertEqual(len(second.sites), 2)
