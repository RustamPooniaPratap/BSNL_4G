"""Consolidation Matrix import into the new data layer (apps.sitedata.matrix, /api/sitedata/matrix/).

Synthetic workbooks with the real "Raw Data" layout (header row found by "BSNL Site ID", title rows above it, the
November 2026 column names), in the test database only.
"""
from datetime import date, datetime
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.sitedata import matrix, portfolio
from apps.sitedata.models import DailySitePerformance, IdentifierConflict, MonthlySitePerformance, Site, SiteIdentifier, UploadBatch
from tests.auth_helpers import SignedInTestCase, portal_user
from tests.test_sitedata import MATRIX, MATRIX_HEADER, SiteDataTestCase, read_exceptions, write_sheet
from tests.workbook_factory import write_workbook

XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
TODAY = date(2026, 11, 5)
# The November 2026 matrix: commissioning columns renamed, no band ID / Master BTS ID / CCU/SMPS Make columns.
NOV_HEADER = ['SL', 'Entity', 'Site Type', 'Circle Name', 'BSNL Site ID', 'Site Name/Village Name', 'BA', 'OA', 'District',
              'Site Comm./Hoto Date', 'Site Comm./Hoto Status', 'O&M Status', 'O&M Start Date', 'DG Status', 'Site On Air Status',
              'Site On Air Date', 'IE Name', 'IE Contact', 'CI Name', 'CI Contact', 'Other Remarks (If Any)']


def nov(sl, entity, circle, site, name, *, om=datetime(2025, 1, 1), on_air=datetime(2025, 1, 1), ie='IE One', ci='CI East', ba='BHOPAL',
        dg='N-DG', remarks=''):
    return [sl, entity, entity, circle, site, name, ba, 'SEHORE', 'Sehore', datetime(2024, 12, 1), 'DONE', 'Yes', om, dg, 'Yes', on_air,
            ie, '9000000001', ci, '9000000002', remarks]


class MatrixImportCase(SignedInTestCase, SiteDataTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch('apps.sitedata.matrix.timezone.localdate', return_value=TODAY)
        patcher.start()
        self.addCleanup(patcher.stop)
        portfolio.clear_cache()
        self.addCleanup(portfolio.clear_cache)

    def nov_file(self, rows, name='nov.xlsx', header=NOV_HEADER):
        return write_sheet(self.tmp / name, header, rows)

    def preview(self, path):
        return matrix.preview(path, path.name, user=self.admin)

    def imported(self, path):
        batch = self.preview(path)
        self.assertNotEqual(batch.validation_status, UploadBatch.Validation.FAILED, batch.report)
        return matrix.commit(batch, user=self.admin)


class StructureAndMappingTests(MatrixImportCase):
    def test_reads_the_real_layout_and_maps_every_column_to_the_site_master(self):
        path = self.nov_file([nov(1, '4G Saturation', 'Madhya Pradesh', 'UVMP001', 'Alpha', remarks='Tower ok')])
        batch = self.imported(path)
        site = Site.objects.get(site_key='UVMP001')
        self.assertEqual((site.entity, site.technology, site.reporting_scope, site.circle, site.circle_raw), ('4G Saturation', '4G Saturation', 'dashboard', 'MP', 'Madhya Pradesh'))
        self.assertEqual((site.site_name, site.ba, site.oa, site.district), ('Alpha', 'BHOPAL', 'SEHORE', 'Sehore'))
        self.assertEqual((site.commissioning_date, site.commissioning_status), (date(2024, 12, 1), 'DONE'))  # "Site Comm./Hoto" columns
        self.assertEqual((site.om_status, site.om_start_date, site.on_air_status, site.on_air_date, site.on_air), ('Yes', date(2025, 1, 1), 'Yes', date(2025, 1, 1), True))
        self.assertEqual((site.dg_status, site.ie_name, site.ie_contact, site.ci_name, site.ci_contact, site.remarks),
                         ('N-DG', 'IE One', '9000000001', 'CI East', '9000000002', 'Tower ok'))
        self.assertEqual(site.matrix_batch_id, batch.pk)
        self.assertLessEqual({'bts_id_b1', 'bts_id_b28', 'master_bts_id', 'smps_make'}, set(batch.report['columns_not_in_file']))
        self.assertTrue(SiteIdentifier.objects.filter(site=site, kind='bsnl_site_id', key='UVMP001').exists())

    def test_a_workbook_without_raw_data_is_not_a_matrix(self):
        path = write_workbook(self.tmp / 'uptime.xlsx')  # an Up-Time Report workbook
        batch = self.preview(path)
        self.assertEqual(batch.validation_status, UploadBatch.Validation.FAILED)
        self.assertIn('has no "Raw Data" sheet, so it is not a Consolidation Matrix', batch.error)
        self.assertIn('choose the Up-Time Report type', batch.error)
        no_key = self.preview(write_sheet(self.tmp / 'nokey.xlsx', ['Entity', 'Circle Name', 'Site'], [['LWE', 'Odisha', 'X']]))
        self.assertIn('has no "BSNL Site ID" header row', no_key.error)


class InsertUpdateTests(MatrixImportCase):
    def test_new_existing_and_unchanged_sites_and_a_repeat_import_changes_nothing(self):
        first = [nov(1, '4G Saturation', 'Madhya Pradesh', 'UVMP001', 'Alpha'), nov(2, 'LWE', 'Odisha', 'LWEOD01', 'Foxtrot')]
        self.imported(self.nov_file(first, 'a.xlsx'))
        second = [nov(1, '4G Saturation', 'Madhya Pradesh', 'UVMP001', 'Alpha Renamed'), nov(2, 'LWE', 'Odisha', 'LWEOD01', 'Foxtrot'),
                  nov(3, '4G Saturation', 'Rajasthan', 'UVRJ001', 'Delta')]
        batch = self.preview(self.nov_file(second, 'b.xlsx'))
        p = batch.report['preview']
        self.assertEqual((p['total_rows'], p['new_sites'], p['updated_sites'], p['unchanged_sites'], p['rejected_rows']), (3, 1, 1, 1, 0))
        self.assertEqual(batch.report['changed_fields'], {'site_name': 1})
        matrix.commit(batch, user=self.admin)
        self.assertEqual(Site.objects.get(site_key='UVMP001').site_name, 'Alpha Renamed')
        again = self.imported(self.nov_file(second, 'c.xlsx'))
        self.assertEqual(again.report['preview']['unchanged_sites'], 3)
        self.assertEqual((Site.objects.count(), SiteIdentifier.objects.filter(kind='bsnl_site_id').count()), (3, 3))  # no duplicates

    def test_blank_cells_and_missing_columns_never_overwrite_stored_values(self):
        self.load_matrix(MATRIX)  # the October layout, with band IDs
        site = Site.objects.get(site_key='UVMP001')
        self.assertEqual(site.ie_name, 'IE One')
        bands = set(SiteIdentifier.objects.filter(site=site).exclude(kind='bsnl_site_id').values_list('kind', 'key'))
        self.assertTrue(bands)
        row = nov(1, '4G Saturation', 'Madhya Pradesh', 'UVMP001', 'Alpha', ie='', om=None)  # blank IE Name and O&M Start Date
        batch = self.imported(self.nov_file([row]))
        site.refresh_from_db()
        self.assertEqual((site.ie_name, site.om_start_date), ('IE One', date(2025, 10, 1)))  # kept
        self.assertEqual(batch.report['blank_values_kept'], {'ie_name': 1, 'om_start_date': 1, 'om_start_raw': 1})  # a date and its text
        self.assertEqual(set(SiteIdentifier.objects.filter(site=site).exclude(kind='bsnl_site_id').values_list('kind', 'key')), bands)  # no band columns: kept


class ValidationTests(MatrixImportCase):
    def test_duplicate_ids_identical_rows_import_once_differing_rows_are_rejected(self):
        rows = [nov(1, '4G Saturation', 'Madhya Pradesh', 'UVMP001', 'Alpha'), nov(2, '4G Saturation', 'Madhya Pradesh', 'UVMP001', 'Alpha'),
                nov(3, 'LWE', 'Odisha', 'LWEOD01', 'Foxtrot'), nov(4, 'LWE', 'Odisha', 'LWEOD01', 'Other name')]
        batch = self.preview(self.nov_file(rows))
        p = batch.report['preview']
        self.assertEqual((p['duplicate_site_ids'], p['new_sites'], p['rejected_rows']), (2, 1, 2))
        self.assertEqual([(r['row'], r['site_id'], r['code']) for r in batch.report['rejected']],
                         [(5, 'LWEOD01', 'duplicate_site_id'), (6, 'LWEOD01', 'duplicate_site_id')])  # header on row 2: data from row 3
        matrix.commit(batch, user=self.admin)
        self.assertEqual(list(Site.objects.values_list('site_key', flat=True)), ['UVMP001'])

    def test_missing_mandatory_values_and_invalid_entity_or_circle_are_rejected_with_reasons(self):
        rows = [nov(1, '4G Saturation', 'Madhya Pradesh', '', 'No ID'), nov(2, '', 'Madhya Pradesh', 'UVMP009', 'No entity'),
                nov(3, '4G Saturation', '', 'UVMP010', 'No circle'), nov(4, 'Unknown Co', 'Madhya Pradesh', 'UVMP011', 'Bad entity'),
                nov(5, 'LWE', 'Atlantis', 'LWEXX01', 'Bad circle'), nov(6, 'VI-HPSC', 'Delhi-NCR', 'VIDL001', 'Outside scope'),
                nov(7, '4G Saturation', 'Rajasthan', 'UVRJ001', 'Valid')]
        batch = self.preview(self.nov_file(rows))
        reasons = {r['code']: r['row'] for r in batch.report['rejected']}
        self.assertEqual(reasons, {'missing_site_id': 3, 'missing_entity': 4, 'missing_circle': 5, 'unknown_entity': 6, 'unknown_circle': 7})
        p = batch.report['preview']
        self.assertEqual((p['missing_mandatory'], p['invalid_circle_or_technology'], p['new_sites']), (3, 2, 2))
        self.assertIn('Atlantis', next(r['reason'] for r in batch.report['rejected'] if r['code'] == 'unknown_circle'))
        rejected = {r['code'] for r in read_exceptions(batch) if r['severity'] == 'rejected'}
        self.assertEqual(rejected, set(reasons))  # every rejected row is in the CSV report
        matrix.commit(batch, user=self.admin)
        self.assertEqual(dict(Site.objects.values_list('site_key', 'reporting_scope')), {'VIDL001': 'outside_scope', 'UVRJ001': 'dashboard'})

    def test_identity_changes_and_conflicting_identifiers_are_blocked(self):
        self.load_matrix(MATRIX)
        rows = [nov(1, '4G Saturation', 'Rajasthan', 'UVMP001', 'Alpha'),  # UVMP001 is an MP site: circle would change
                nov(2, 'LWE', 'Madhya Pradesh', 'UVMP002', 'Bravo'),           # a 4G site would become LWE
                nov(3, 'LWE', 'Odisha', 'LWEOD01', 'Foxtrot')]
        batch = self.preview(self.nov_file(rows))
        conflicts = {r['site_id']: r['reason'] for r in batch.report['identity_conflicts']}
        self.assertEqual(set(conflicts), {'UVMP001', 'UVMP002'})
        self.assertIn('circle MP -> RJ', conflicts['UVMP001'])
        self.assertIn('technology 4G Saturation -> LWE', conflicts['UVMP002'])
        self.assertEqual(batch.report['preview']['conflicting_mappings'], 2)
        matrix.commit(batch, user=self.admin)
        self.assertEqual((Site.objects.get(site_key='UVMP001').circle, Site.objects.get(site_key='UVMP002').technology), ('MP', '4G Saturation'))
        # A band ID claimed by two sites (October layout): assigned to neither and blocked.
        rows = [r[:] for r in MATRIX]
        rows[1][12] = rows[0][12]
        batch = self.preview(write_sheet(self.tmp / 'band.xlsx', MATRIX_HEADER, rows))
        self.assertEqual(len(batch.report['identifier_conflicts']), 1)
        matrix.commit(batch, user=self.admin)
        self.assertTrue(IdentifierConflict.objects.filter(key=rows[0][12].upper(), active=True).exists())
        self.assertFalse(SiteIdentifier.objects.filter(key=rows[0][12].upper()).exists())

    def test_effective_dates_are_validated_and_changes_listed(self):
        self.load_matrix(MATRIX)
        rows = [nov(1, '4G Saturation', 'Madhya Pradesh', 'UVMP001', 'Alpha', on_air=datetime(2024, 7, 1), om=datetime(2026, 12, 1)),  # future
                nov(2, '4G Saturation', 'Madhya Pradesh', 'UVMP002', 'Bravo', on_air=datetime(2025, 6, 1), om=datetime(2025, 3, 1)),  # O&M before On-Air
                nov(3, '4G Saturation', 'Rajasthan', 'UVRJ001', 'Delta', om='not a date', on_air=datetime(2025, 1, 1)),
                nov(4, 'LWE', 'Odisha', 'LWEOD01', 'Foxtrot', om=None, on_air=None)]
        batch = self.preview(self.nov_file(rows))
        review = {(r['site_id'], r['code']) for r in batch.report['effective_date_review_rows']}
        self.assertLessEqual({('UVMP001', 'om_start_date_in_future'), ('UVMP002', 'om_start_before_on_air'), ('UVRJ001', 'om_start_date_invalid'),
                              ('LWEOD01', 'om_start_date_missing'), ('LWEOD01', 'on_air_date_missing')}, review)
        changes = {(c['site_id'], c['field'], c['from'], c['to']) for c in batch.report['effective_date_changes']}
        self.assertIn(('UVMP001', 'om_start_date', '2025-10-01', '2026-12-01'), changes)
        matrix.commit(batch, user=self.admin)
        self.assertEqual(Site.objects.get(site_key='UVRJ001').om_start_date_issue, 'invalid')  # a new date column value that is text


class SafetyTests(MatrixImportCase):
    def test_a_failure_rolls_back_everything(self):
        self.load_matrix(MATRIX)
        before = list(Site.objects.order_by('site_key').values_list('site_key', 'site_name', 'present_in_latest_matrix'))
        batch = self.preview(self.nov_file([nov(1, '4G Saturation', 'Madhya Pradesh', 'UVMP001', 'Changed'),
                                            nov(2, '4G Saturation', 'Rajasthan', 'UVRJ999', 'New site')]))
        with mock.patch('apps.sitedata.matrix.SiteIdentifier.objects.bulk_create', side_effect=RuntimeError('disk full')):
            with self.assertRaises(RuntimeError):
                matrix.commit(batch, user=self.admin)
        self.assertEqual(list(Site.objects.order_by('site_key').values_list('site_key', 'site_name', 'present_in_latest_matrix')), before)
        batch.refresh_from_db()
        self.assertEqual(batch.processing_status, UploadBatch.Processing.PREVIEWED)

    def test_only_the_new_layer_site_master_is_written(self):
        self.load_matrix(MATRIX)
        self.load_uptime()
        daily, monthly = DailySitePerformance.objects.count(), MonthlySitePerformance.objects.count()
        snapshot = list(DailySitePerformance.objects.order_by('id').values_list('id', 'outage_minutes', 'updated_at'))
        self.imported(self.nov_file([nov(1, '4G Saturation', 'Madhya Pradesh', 'UVMP001', 'Alpha'), nov(2, 'LWE', 'Odisha', 'LWEOD01', 'Foxtrot')]))
        # Daily records are untouched; monthly results are only recalculated (revisions added, none removed).
        self.assertEqual(DailySitePerformance.objects.count(), daily)
        self.assertGreaterEqual(MonthlySitePerformance.objects.count(), monthly)
        self.assertEqual(list(DailySitePerformance.objects.order_by('id').values_list('id', 'outage_minutes', 'updated_at')), snapshot)
        self.assertEqual(Site.objects.filter(present_in_latest_matrix=False).count(), 5)  # not listed: flagged, never deleted


class DashboardIntegrationTests(MatrixImportCase):
    def test_the_dashboard_uses_the_imported_master_dates(self):
        self.load_matrix(MATRIX)
        self.load_uptime()
        self.client.force_login(self.admin)
        def on_air():
            return self.client.get(reverse('dashboard-summary'), {'scope': 'om_start', 'report_type': '4G Saturation'}).json()['metrics']['sites_in_scope']
        before = on_air()
        rows = [nov(i + 1, '4G Saturation', c, s, n, om=datetime(2025, 1, 1)) for i, (c, s, n) in
                enumerate((('Madhya Pradesh', 'UVMP001', 'Alpha'), ('Madhya Pradesh', 'UVMP002', 'Bravo'), ('Rajasthan', 'UVRJ001', 'Delta')))]
        self.imported(self.nov_file(rows))
        portfolio.clear_cache()
        self.assertEqual((before, on_air()), (1, 3))  # UVMP002 and UVRJ001 now have O&M Start Dates


class ApiTests(MatrixImportCase):
    def upload(self, path, url='sitedata-matrix-preview'):
        return self.client.post(reverse(url), {'file': SimpleUploadedFile(path.name, path.read_bytes(), XLSX)})

    def test_preview_confirm_commit_and_issue_report(self):
        self.client.force_login(self.admin)
        path = self.nov_file([nov(1, '4G Saturation', 'Madhya Pradesh', 'UVMP001', 'Alpha'), nov(2, '', 'Odisha', 'LWEOD01', 'No entity')])
        preview = self.upload(path)
        self.assertEqual(preview.status_code, 201, preview.content[:300])
        body = preview.json()
        self.assertEqual((body['status'], body['report']['preview']['new_sites'], body['report']['preview']['rejected_rows']), ('previewed', 1, 1))
        self.assertEqual(Site.objects.count(), 0)  # nothing written by the preview
        self.assertEqual(self.client.post(reverse('sitedata-matrix-commit', args=[body['id']]), {}, content_type='application/json').status_code, 400)
        done = self.client.post(reverse('sitedata-matrix-commit', args=[body['id']]), {'confirm': True}, content_type='application/json')
        self.assertEqual((done.status_code, done.json()['status'], done.json()['report']['committed']['inserted']), (200, 'committed', 1))
        self.assertEqual(self.client.post(reverse('sitedata-matrix-commit', args=[body['id']]), {'confirm': True}, content_type='application/json').status_code, 409)
        csv_text = self.client.get(reverse('sitedata-matrix-issues', args=[body['id']])).content.decode('utf-8-sig')
        self.assertIn('missing_entity', csv_text)
        self.assertEqual(self.client.get(reverse('sitedata-matrix-list')).json()['imports'][0]['id'], body['id'])

    def test_an_up_time_report_is_refused_and_the_up_time_pipeline_still_refuses_a_matrix(self):
        self.client.force_login(self.admin)
        refused = self.upload(write_workbook(self.tmp / 'uptime.xlsx'))
        self.assertEqual(refused.status_code, 400)
        self.assertIn('not a Consolidation Matrix', refused.json()['error'])

    def test_only_admins_may_import(self):
        self.client.force_login(portal_user('matrix-ci', 'ci'))
        self.assertEqual(self.upload(self.nov_file([nov(1, 'LWE', 'Odisha', 'LWEOD01', 'Foxtrot')])).status_code, 403)
