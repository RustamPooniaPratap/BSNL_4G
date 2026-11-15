"""RCA module: workbook parsing, idempotent import, cause mapping, workflow and permissions.

Synthetic workbooks only (the real RCA workbook is checked against the live database separately).
"""
import tempfile
from datetime import datetime
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from openpyxl import Workbook

from apps.rca import importer, parser
from apps.rca.models import RcaCauseMapping, RcaEvent, RcaImportBatch, RcaRecord, RcaWorkflow
from tests.auth_helpers import portal_user
from tests.sitedata_factory import make_site

HEADERS = ['Date', 'Project', 'Circle', 'Site ID', 'Site Name', 'OA', 'BA', 'O&M Start (Yes/No)', 'Outage Min.',
           'Final Bucket', 'Bucket - 2', 'RCA']
DAY = datetime(2026, 10, 21)
ROWS = [
    [DAY, 'LWE', 'Bihar', 'LWEBH0063', 'Haibatpur', 'Gaya', 'Gaya', 'Yes', 20.6, 'BSNL Media', 'BSNL Media', 'Media Flacuatation'],
    [DAY, 'LWE', 'Jharkhand', 'LWEJH0001', 'Alpha', 'Ranchi', 'Ranchi', 'YES', 1442.55, 'BSNL OFC', '-', 'SSA OFC Break'],
    [DAY, '4G Satu', 'Odisha', 'OD0001 ', 'Bravo', 'KORAPUT', 'KORAPUT', 'No', 90, 'IaasP OFC', 'BSNL MEDIA', 'Media Fluctuation'],
    [DAY, '4G Satu', 'Rajasthan', 'RJ0001', 'Charlie', 'Jaisalmer', 'JODHPUR', 'Yes', 5, 'Iaasp OFC', 'BSNL Media', 'media  fluctuation'],
    [DAY, '4G Satu', 'Madhya Pradesh', 'MP0001', 'Delta', 'Indore', 'Indore', 'Yes', 0.5, 'Others', '', ''],
]


def workbook(path: Path, rows=None, headers=HEADERS, sheet='Sheet1') -> Path:
    book = Workbook()
    ws = book.active
    ws.title = sheet
    ws.append(headers)
    for row in ROWS if rows is None else rows:
        ws.append(row)
    book.save(path)
    return path


def active_scope(units) -> None:
    """Keeps exactly these (project, circle) associations active in the Organization; the RCA expected scope follows them."""
    from apps.organization.models import ProjectCircle
    keep = {tuple(u) for u in units}
    for pc in ProjectCircle.objects.select_related('project', 'circle'):
        active = (pc.project.key, pc.circle.code) in keep
        if pc.is_active != active:
            pc.is_active = active
            pc.save(update_fields=['is_active'])


def uptime_sites(*sites) -> None:
    """Site master (sitedata, dashboard scope) sites (project, circle, site ID): an upload with report details accepts only these."""
    for project, circle, site in sites:
        make_site(site, technology=project, circle=circle)


ROW_SITES = [('LWE', 'BH', 'LWEBH0063'), ('LWE', 'JH', 'LWEJH0001'), ('4G Saturation', 'OD', 'OD0001'),
             ('4G Saturation', 'RJ', 'RJ0001'), ('4G Saturation', 'MP', 'MP0001')]
DETAILS = {'upload_type': 'consolidated', 'report_name': 'October 2026 RCA Report', 'period_start': '2026-10-21', 'project_scope': 'both'}


class RcaTestCase(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        override = override_settings(DATA_DIR=Path(self.tmp.name) / 'data')  # uploaded copies and reports stay out of Data/
        override.enable()
        self.addCleanup(override.disable)
        self.admin = portal_user('rca-admin', 'admin')
        self.ci = portal_user('rca-ci', 'ci', all_circles=True)

    def path(self, name='rca.xlsx', **kwargs) -> Path:
        return workbook(Path(self.tmp.name) / name, **kwargs)

    def imported(self, **kwargs) -> RcaImportBatch:
        return importer.commit(importer.preview(self.path(**kwargs), 'Book1_RCA.xlsx', user=self.admin), user=self.admin)


class ParserTests(RcaTestCase):
    def test_reads_every_field_keeps_source_values_and_flags_the_short_project_label(self):
        parsed = parser.parse(self.path(), 'rca.xlsx')
        rows, report = parsed['rows'], parsed['report']
        self.assertEqual((report['valid_rows'], report['rejected_rows']), (5, 0))
        self.assertEqual(report['projects'], {'LWE': 2, '4G Saturation': 3})
        self.assertEqual(report['projects_raw'], {'LWE': 2, '4G Satu': 3})
        self.assertIn('project_label_to_confirm', report['issue_counts'])
        od = next(r for r in rows if r['site_key'] == 'OD0001')
        self.assertEqual((od['project_raw'], od['project'], od['circle_raw'], od['circle'], od['site_id']),
                         ('4G Satu', '4G Saturation', 'Odisha', 'OD', 'OD0001'))  # trimmed, original label kept
        self.assertEqual((od['om_start_raw'], od['om_start']), ('No', False))
        jh = next(r for r in rows if r['site_key'] == 'LWEJH0001')
        self.assertEqual((jh['om_start_raw'], jh['om_start']), ('YES', True))  # case ignored for filtering only
        self.assertEqual((jh['bucket_2'], jh['bucket_2_key']), ('-', ''))  # placeholder = unclassified, value kept
        self.assertNotIn('outage_over_day', report['issue_counts'])  # more than 1,440 min is valid (no warning)
        # Case variants share a key; the source spellings are kept.
        self.assertEqual(od['final_bucket_key'], next(r for r in rows if r['site_key'] == 'RJ0001')['final_bucket_key'])
        # "IaasP OFC" and "Iaasp OFC" are the approved IaasP OFC (case ignored) and are kept exactly as uploaded: never renamed.
        self.assertEqual({r['final_bucket'] for r in rows if r['final_bucket_key'] == 'iaasp ofc'}, {'IaasP OFC', 'Iaasp OFC'})
        self.assertNotIn('bucket_spelling_approved', report['issue_counts'])
        self.assertEqual(next(r for r in rows if r['site_key'] == 'RJ0001')['rca_key'], 'media fluctuation')

    def test_rejects_bad_rows_with_reasons_and_never_repairs_them(self):
        bad = ROWS + [
            ['not a date', 'LWE', 'Bihar', 'X1', '', '', '', 'Yes', 1, 'TCS', 'TCS', 'x'],
            [DAY, 'Other', 'Bihar', 'X2', '', '', '', 'Yes', 1, 'TCS', 'TCS', 'x'],
            [DAY, 'LWE', 'Atlantis', 'X3', '', '', '', 'Yes', 1, 'TCS', 'TCS', 'x'],
            [DAY, 'LWE', 'Bihar', '', '', '', '', 'Yes', 1, 'TCS', 'TCS', 'x'],
            [DAY, 'LWE', 'Bihar', 'X5', '', '', '', 'Yes', 'abc', 'TCS', 'TCS', 'x'],
            list(ROWS[0]),  # identical to row 2 in every column
        ]
        report = parser.parse(self.path(rows=bad), 'rca.xlsx')['report']
        self.assertEqual((report['valid_rows'], report['rejected_rows']), (5, 6))
        self.assertEqual({c for c, n in report['issue_counts'].items() if c in {
            'invalid_date', 'unknown_project', 'unknown_circle', 'missing_site_id', 'invalid_outage', 'duplicate_record'}},
            {'invalid_date', 'unknown_project', 'unknown_circle', 'missing_site_id', 'invalid_outage', 'duplicate_record'})
        duplicate = next(i for i in report['all_issues'] if i['code'] == 'duplicate_record')
        self.assertEqual((duplicate['row'], duplicate['site_id']), (12, 'LWEBH0063'))
        self.assertIn('Duplicate of Excel row 2', duplicate['message'])
        self.assertIn('(identical in every column)', duplicate['message'])

    def test_missing_columns_or_sheet_reject_the_file(self):
        with self.assertRaisesRegex(parser.ParseError, 'missing required columns: RCA'):
            parser.parse(self.path(headers=HEADERS[:-1], rows=[r[:-1] for r in ROWS]), 'rca.xlsx')
        with self.assertRaisesRegex(parser.ParseError, 'No sheet of rca.xlsx has the RCA columns'):
            parser.parse(self.path(headers=['Count of RCA', 'Column Labels']), 'rca.xlsx')

    def test_reads_the_daily_rca_compilation_layout(self):
        # The data sheet is "RCA Backup" with a blank first row; "Sheet1" is a pivot table.
        book = Workbook()
        pivot = book.active
        pivot.title = 'Sheet1'
        pivot.append([])
        pivot.append(['Count of RCA', 'Column Labels'])
        pivot.append(['Row Labels', 'BB', 'Grand Total'])
        data = book.create_sheet('RCA Backup')
        data.append([])
        data.append(HEADERS)
        rows = [
            [DAY, 'LWE', 'Chhatisgarh', 'LWECG0001', 'A', '', '', 'Yes', 846, 'BSNL OFC', 'BSNL OFC', 'Ofc cut'],
            [DAY, 'LWE', 'Chhatisgarh', 'LWECG0001', 'A', '', '', 'Yes', 27, 'Others', 'IP site link', 'Media issue'],  # a second outage
            [DAY, 'LWE', 'Chhatisgarh', 'LWECG0001', 'A', '', '', 'Yes', 27, 'Others', 'IP site link', 'Media issue'],  # an exact copy
        ]
        for row in rows:
            data.append(row)
        path = Path(self.tmp.name) / 'daily.xlsx'
        book.save(path)
        parsed = parser.parse(path, 'daily.xlsx')
        report = parsed['report']
        self.assertEqual((report['sheet'], report['header_row'], report['valid_rows'], report['rejected_rows']), ('RCA Backup', 2, 2, 1))
        # Other buckets on the same date are a record of their own; the exact copy is a duplicate.
        self.assertEqual([(i['row'], i['code']) for i in report['all_issues'] if i['severity'] == 'error'], [(5, 'duplicate_record')])
        self.assertEqual(sorted((r['occurrence'], r['final_bucket']) for r in parsed['rows']), [(1, 'BSNL OFC'), (2, 'Others')])
        self.assertEqual({(r['circle'], r['circle_raw']) for r in parsed['rows']}, {('CG', 'Chhatisgarh')})


class ValidationPriorityTests(RcaTestCase):
    """Duplicates and Final Bucket reject rows; Sub Bucket and RCA description never block (business rules, 4 Nov 2026)."""

    def rows(self, *specs):
        return [[DAY, '4G Satu', 'Odisha', site, 'S', '', '', 'Yes', minutes, final, b2, rca] for site, minutes, final, b2, rca in specs]

    def test_missing_or_unapproved_final_bucket_rejects_rows_is_reported_and_blocks_the_file(self):
        rows = self.rows(('OD0001', 5, 'TCS', 'BBU', 'Card'), ('OD0002', 5, 'Vsat', 'Vsat', 'x'), ('OD0003', 5, 'Vsat', '', 'y'),
                         ('OD0004', 5, '', 'BBU', 'z'), ('OD0005', 5, '-', 'BBU', 'w'), ('OD0006', 5, 'Other Media', 'BSNL Media', 'm'))
        path = self.path(rows=rows)
        report = parser.parse(path, 'rca.xlsx')['report']
        self.assertEqual((report['valid_rows'], report['rejected_rows'], report['final_bucket_error_rows']), (1, 5, 5))
        problems = {(p['value'], p['code']): (p['rows'], p['example_rows']) for p in report['final_bucket_problems']}
        self.assertEqual(problems, {('Vsat', 'final_bucket_not_approved'): (2, [3, 4]), ('', 'missing_final_bucket'): (1, [5]),
                                    ('-', 'missing_final_bucket'): (1, [6]), ('Other Media', 'final_bucket_not_approved'): (1, [7])})
        self.assertIn('Nothing can be imported', parser.final_bucket_file_error(report))
        # Values are kept as written in the report, never renamed or reassigned.
        self.assertIn('Final Bucket "Vsat" is not one of the approved Final Buckets', next(
            i['message'] for i in report['all_issues'] if i['code'] == 'final_bucket_not_approved'))
        with self.assertRaisesRegex(importer.ImportRejected, '5 rows have a missing or unapproved Final Bucket'):
            importer.preview(path, 'rca.xlsx', user=self.admin)  # a command-line import is refused
        uptime_sites(*[('4G Saturation', 'OD', f'OD000{n}') for n in range(1, 7)])
        batch = importer.preview(path, 'rca.xlsx', user=self.admin, details={**DETAILS, 'period_start': DAY.date()})
        self.assertEqual(batch.status, RcaImportBatch.Status.REJECTED)  # an upload is rejected as a whole
        self.assertIn('missing or unapproved Final Bucket', batch.error)
        self.assertEqual(RcaRecord.objects.count(), 0)

    def test_a_batch_with_final_bucket_errors_is_never_committed(self):
        batch = importer.preview(self.path(rows=self.rows(('OD0001', 5, 'TCS', 'BBU', 'Card'))), 'rca.xlsx', user=self.admin)
        batch.report = {**batch.report, 'final_bucket_problems': [{'value': 'Vsat', 'code': 'final_bucket_not_approved', 'rows': 1, 'example_rows': [3]}]}
        batch.save()
        with self.assertRaisesRegex(importer.ImportRejected, 'missing or unapproved Final Bucket'):
            importer.commit(batch, user=self.admin)
        self.assertEqual(RcaRecord.objects.count(), 0)

    def test_sub_bucket_and_rca_description_problems_are_warnings_that_never_block(self):
        rows = self.rows(('OD0001', 5, 'TCS', 'BBU', 'Card'), ('OD0002', 5, 'IaasP Others', 'Natural Clamity', 'Storm'),
                         ('OD0003', 5, 'DMW', '', 'Radio'), ('OD0004', 5, 'HFCL', 'HFCL Radio', ''), ('OD0005', 5, 'TCS', 'TCS', '-'))
        batch = importer.preview(self.path(rows=rows), 'rca.xlsx', user=self.admin)
        report = batch.report
        self.assertEqual((report['valid_rows'], report['rejected_rows'], report['final_bucket_error_rows']), (5, 0, 0))
        # "Natural Clamity" is the approved spelling (no warning); "TCS" is no Sub Bucket of TCS; DMW's is blank.
        self.assertEqual({k: v for k, v in report['sub_bucket_warnings'].items() if k != 'values'},
                         {'rows': 2, 'missing_rows': 1, 'not_approved_rows': 1})
        self.assertEqual({(v['final_bucket'], v['value'], v['code']) for v in report['sub_bucket_warnings']['values']},
                         {('TCS', 'TCS', 'sub_bucket_not_approved'), ('DMW', '', 'sub_bucket_missing')})
        self.assertEqual(report['rca_description_warnings'], 2)
        self.assertEqual({i['severity'] for i in report['all_issues'] if i['code'].startswith('sub_bucket_')}, {'warning'})
        self.assertEqual({i['severity'] for i in report['all_issues'] if i['code'] == 'unclassified_rca_text'}, {'info'})
        importer.commit(batch, user=self.admin)
        stored = dict(RcaRecord.objects.values_list('site_key', 'bucket_2'))
        self.assertEqual((stored['OD0002'], stored['OD0003'], stored['OD0005']), ('Natural Clamity', '', 'TCS'))  # kept as written
        self.assertEqual(dict(RcaRecord.objects.values_list('site_key', 'rca_text'))['OD0005'], '-')

    def test_duplicate_key_is_site_date_final_bucket_and_sub_bucket(self):
        # The business example: one site, one date.
        rows = self.rows(('OD0001', 30, 'BSNL Media', 'Nokia mini link', 'Link fail'),    # row 2: valid
                         ('OD0001', 40, 'BSNL OFC', 'SSA OFC', 'Fibre cut'),               # row 3: valid (other Final Bucket)
                         ('OD0001', 50, 'BSNL Media', 'BSNL Link', 'Link fail'),          # row 4: valid (other Sub Bucket)
                         ('OD0001', 30, 'BSNL Media', 'Nokia mini link', 'Link fail'))    # row 5: duplicate of row 2
        report = parser.parse(self.path(rows=rows), 'rca.xlsx')['report']
        self.assertEqual((report['valid_rows'], report['rejected_rows']), (3, 1))
        self.assertEqual([(i['row'], i['site_id']) for i in report['all_issues'] if i['code'] == 'duplicate_record'], [(5, 'OD0001')])
        self.assertEqual(report['sites_with_several_records'], 1)

    def test_a_different_description_or_outage_does_not_make_a_duplicate_valid(self):
        rows = self.rows(('OD0001', 30, 'BSNL Media', 'Nokia mini link', 'Link fail'),
                         ('OD0001', 30, 'BSNL Media', 'Nokia mini link', 'Radio replaced'),   # other description
                         ('OD0001', 999, 'BSNL Media', 'Nokia mini link', 'Link fail'),       # other outage
                         ('OD0001', 5, 'BSNL Media', 'Nokia mini link', 'Another cause'),     # both differ
                         ('OD0001', 30, 'Bsnl media', 'NOKIA MINI LINK', 'Link fail'))       # spelling: the same buckets
        report = parser.parse(self.path(rows=rows), 'rca.xlsx')['report']
        self.assertEqual((report['valid_rows'], report['rejected_rows']), (1, 4))
        dup = report['duplicates']
        self.assertEqual({k: v for k, v in dup.items() if k != 'examples'},
                         {'rows': 4, 'groups': 1, 'sites': 1, 'identical_rows': 0, 'differing_rows': 4})
        self.assertEqual(dup['examples'][0], {'site_id': 'OD0001', 'project': '4G Saturation', 'reporting_date': '2026-10-21',
                                              'final_bucket': 'BSNL Media', 'sub_bucket': 'Nokia mini link', 'first_row': 2,
                                              'rejected_rows': [3, 4, 5, 6], 'identical': 0})
        message = next(i['message'] for i in report['all_issues'] if i['row'] == 3)
        self.assertIn('Duplicate of Excel row 2: same Site ID OD0001, date 2026-10-21, Final Bucket "BSNL Media" and Sub Bucket "Nokia mini link"', message)

    def test_a_blank_sub_bucket_is_a_value_for_duplicates(self):
        rows = self.rows(('OD0001', 5, 'TCS', '', 'a'), ('OD0001', 6, 'TCS', '-', 'b'), ('OD0001', 7, 'TCS', 'BBU', 'c'),
                         ('OD0002', 5, 'TCS', '', 'a'))  # another site: its own record
        rows.append([datetime(2026, 10, 22), *rows[0][1:]])  # another date: its own record
        report = parser.parse(self.path(rows=rows), 'rca.xlsx')['report']
        self.assertEqual((report['valid_rows'], report['rejected_rows']), (4, 1))
        self.assertEqual(report['duplicates']['examples'][0]['sub_bucket'], '')
        self.assertIn('Sub Bucket "blank"', next(i['message'] for i in report['all_issues'] if i['code'] == 'duplicate_record'))

    def test_duplicates_with_other_errors_are_counted_once_per_row(self):
        rows = self.rows(('OD0001', 5, 'TCS', 'BBU', 'Card'), ('OD0001', 5, 'TCS', 'BBU', 'Card'),
                         ('OD0002', 5, 'Vsat', 'Vsat', 'x'), ('OD0002', 7, 'Vsat', 'Vsat', 'y'))  # also Final Bucket errors
        report = parser.parse(self.path(rows=rows), 'rca.xlsx')['report']
        self.assertEqual((report['rows_read'], report['valid_rows'], report['rejected_rows']), (4, 1, 3))
        self.assertEqual({k: v for k, v in report['duplicates'].items() if k != 'examples'},
                         {'rows': 2, 'groups': 2, 'sites': 2, 'identical_rows': 1, 'differing_rows': 1})
        self.assertEqual(report['final_bucket_error_rows'], 2)

    def test_preview_and_import_apply_the_same_key_and_an_older_batch_with_duplicates_is_refused(self):
        rows = self.rows(('OD0001', 30, 'BSNL Media', 'Nokia mini link', 'Link fail'), ('OD0001', 31, 'BSNL Media', 'Nokia mini link', 'Other text'))
        batch = importer.preview(self.path(rows=rows), 'rca.xlsx', user=self.admin)
        self.assertEqual((len(batch.rows), batch.report['rejected_rows']), (1, 1))
        # A batch validated before this rule could still hold both rows: the import refuses it instead of storing two.
        batch.rows = batch.rows + [{**batch.rows[0], 'rca_text': 'Other text', 'rca_key': 'other text', 'source_row': 3}]
        batch.save()
        with self.assertRaisesRegex(importer.ImportRejected, 'earlier duplicate rule'):
            importer.commit(batch, user=self.admin)
        self.assertEqual(RcaRecord.objects.count(), 0)

    def test_outage_over_a_day_is_valid_without_a_warning_and_kept_as_submitted(self):
        result = parser.parse(self.path(rows=self.rows(('OD0001', 1441, 'TCS', 'BBU', 'Card'), ('OD0002', 1500, 'TCS', 'BBU', 'Card'),
                                                       ('OD0003', 4320.75, 'TCS', 'BBU', 'Card'), ('OD0004', '2,880', 'TCS', 'BBU', 'Card'))),
                              'rca.xlsx')
        report = result['report']
        self.assertEqual((report['valid_rows'], report['rejected_rows']), (4, 0))
        self.assertEqual({r['site_id']: r['outage_minutes'] for r in result['rows']},
                         {'OD0001': 1441.0, 'OD0002': 1500.0, 'OD0003': 4320.75, 'OD0004': 2880.0})  # never capped
        self.assertFalse([i for i in report['all_issues'] if 'outage' in i['code']])
        self.assertNotIn('outage_over_day_rows', report)

    def test_negative_and_non_numeric_outage_stay_invalid(self):
        result = parser.parse(self.path(rows=self.rows(('OD0001', -5, 'TCS', 'BBU', 'Card'), ('OD0002', 'abc', 'TCS', 'BBU', 'Card'),
                                                       ('OD0003', 'nan', 'TCS', 'BBU', 'Card'), ('OD0004', 'inf', 'TCS', 'BBU', 'Card'),
                                                       ('OD0005', '', 'TCS', 'BBU', 'Card'))), 'rca.xlsx')
        errors = {i['site_id']: i['code'] for i in result['report']['all_issues'] if i['severity'] == 'error'}
        self.assertEqual(errors, {'OD0001': 'negative_outage', 'OD0002': 'invalid_outage', 'OD0003': 'invalid_outage', 'OD0004': 'invalid_outage'})
        blank = next(r for r in result['rows'] if r['site_id'] == 'OD0005')
        self.assertIsNone(blank['outage_minutes'])  # blank = not recorded (a warning), never 0

    def test_outage_over_a_day_is_imported_and_summed_as_submitted(self):
        self.imported(rows=self.rows(('OD0001', 1500, 'TCS', 'BBU', 'Card'), ('OD0002', 2000.5, 'TCS', 'BBU', 'Card')))
        self.assertEqual(sorted(RcaRecord.objects.values_list('outage_minutes', flat=True)), [1500.0, 2000.5])
        self.client.force_login(self.admin)
        summary = self.client.get(reverse('rca-summary')).json()
        self.assertAlmostEqual(summary['kpis']['outage_minutes'], 3500.5, places=2)


class ImportTests(RcaTestCase):
    def test_preview_writes_no_records_and_commit_inserts_them(self):
        batch = importer.preview(self.path(), 'Book1_RCA.xlsx', user=self.admin)
        self.assertEqual(RcaRecord.objects.count(), 0)
        self.assertEqual(batch.report['new_rows'], 5)
        batch = importer.commit(batch, user=self.admin)
        self.assertEqual(batch.counts['inserted'], 5)
        rec = RcaRecord.objects.get(site_key='LWEBH0063')
        self.assertEqual((rec.source_file, rec.source_row, rec.batch_id, rec.rca_text), ('Book1_RCA.xlsx', 2, batch.pk, 'Media Flacuatation'))
        self.assertFalse(RcaWorkflow.objects.exists())  # no status is invented at import

    def test_a_repeat_import_is_idempotent(self):
        path = self.path()  # one file: a workbook saved again carries a new timestamp, hence a new checksum
        importer.commit(importer.preview(path, 'Book1_RCA.xlsx', user=self.admin), user=self.admin)
        again = self.imported(name='again.xlsx')
        self.assertEqual((again.counts['inserted'], again.counts['unchanged']), (0, 5))
        self.assertEqual(RcaRecord.objects.count(), 5)
        self.assertIsNotNone(importer.preview(path, 'Book1_RCA.xlsx').report['already_imported'])

    def test_conflicts_are_never_overwritten_silently(self):
        self.imported()
        changed = [list(r) for r in ROWS]
        changed[0][11] = 'Power failure'
        batch = importer.preview(self.path(name='changed.xlsx', rows=changed), 'changed.xlsx', user=self.admin)
        self.assertEqual(batch.report['conflict_rows'], 1)
        self.assertEqual(batch.report['conflicts'][0]['differences']['rca_text'], {'database': 'Media Flacuatation', 'file': 'Power failure'})
        with self.assertRaises(importer.ImportRejected):
            importer.commit(batch, user=self.admin)
        batch.refresh_from_db()
        skipped = importer.commit(batch, user=self.admin, conflict_action='skip')
        self.assertEqual(skipped.counts['skipped_conflicts'], 1)
        self.assertEqual(RcaRecord.objects.get(site_key='LWEBH0063').rca_text, 'Media Flacuatation')
        over = importer.commit(importer.preview(self.path(name='c2.xlsx', rows=changed), 'c2.xlsx'), user=self.admin, conflict_action='overwrite')
        self.assertEqual(over.counts['overwritten'], 1)
        rec = RcaRecord.objects.get(site_key='LWEBH0063')
        self.assertEqual(rec.rca_text, 'Power failure')
        self.assertEqual(RcaEvent.objects.get(record=rec, action='source_overwritten').changes['rca_text']['database'], 'Media Flacuatation')

    def test_records_of_a_site_and_date_differ_by_bucket_and_import_matches_them_by_the_same_key(self):
        rows = [ROWS[0], [DAY, 'LWE', 'Bihar', 'LWEBH0063', 'Haibatpur', 'Gaya', 'Gaya', 'Yes', 300, 'BSNL OFC', 'BSNL OFC', 'Ofc cut']]
        first = self.imported(rows=rows)
        self.assertEqual((first.counts['inserted'], first.report['rejected_rows']), (2, 0))
        again = self.imported(name='again.xlsx', rows=list(reversed(rows)))  # row order does not matter
        self.assertEqual((again.counts['inserted'], again.counts['unchanged']), (0, 2))
        self.assertEqual(sorted(RcaRecord.objects.values_list('occurrence', 'final_bucket')), [(1, 'BSNL Media'), (2, 'BSNL OFC')])
        # A new bucket pair later is a new record numbered after the stored ones; a changed description is a difference to review.
        later = [[DAY, 'LWE', 'Bihar', 'LWEBH0063', 'Haibatpur', 'Gaya', 'Gaya', 'Yes', 45, 'BSNL Media', 'BSNL Link', 'Link down'],
                 [*rows[1][:11], 'Fibre cut near pole']]
        batch = importer.preview(self.path(name='later.xlsx', rows=later), 'later.xlsx', user=self.admin)
        self.assertEqual((batch.report['new_rows'], batch.report['conflict_rows']), (1, 1))
        self.assertEqual(batch.report['conflicts'][0]['differences']['rca_text'], {'database': 'Ofc cut', 'file': 'Fibre cut near pole'})
        importer.commit(batch, user=self.admin, conflict_action='skip')
        self.assertEqual(sorted(RcaRecord.objects.values_list('occurrence', 'final_bucket', 'bucket_2')),
                         [(1, 'BSNL Media', 'BSNL Media'), (2, 'BSNL OFC', 'BSNL OFC'), (3, 'BSNL Media', 'BSNL Link')])
        self.assertEqual(RcaRecord.objects.get(bucket_2='BSNL OFC').rca_text, 'Ofc cut')  # kept: skip was chosen

    def test_a_later_reporting_date_is_a_new_incident_for_the_same_site(self):
        self.imported()
        later = [[datetime(2026, 10, 22), *r[1:]] for r in ROWS[:1]]
        batch = self.imported(name='later.xlsx', rows=later)
        self.assertEqual(batch.counts['inserted'], 1)
        self.assertEqual(RcaRecord.objects.filter(site_key='LWEBH0063').count(), 2)


class ApiTests(RcaTestCase):
    def upload(self, path: Path):
        with open(path, 'rb') as handle:
            return self.client.post(reverse('rca-import-preview'), {'file': SimpleUploadedFile(path.name, handle.read()), **DETAILS})

    def test_admin_imports_through_the_api_with_a_validation_report(self):
        uptime_sites(*ROW_SITES)
        self.client.force_login(self.admin)
        preview = self.upload(self.path())
        self.assertEqual(preview.status_code, 201, preview.content)
        body = preview.json()
        self.assertEqual((body['report_name'], body['period_start'], body['period_end'], body['status']),
                         ('October 2026 RCA Report', '2026-10-21', '2026-10-21', 'previewed'))
        self.assertNotIn('all_issues', body['report'])
        csv = self.client.get(reverse('rca-import-issues', args=[body['id']]))
        self.assertNotIn('outage_over_day', csv.content.decode('utf-8-sig'))
        commit = self.client.post(reverse('rca-import-commit', args=[body['id']]), {}, content_type='application/json')
        self.assertEqual((commit.status_code, commit.json()['records']), (200, 5))
        again = self.client.post(reverse('rca-import-commit', args=[body['id']]), {}, content_type='application/json')
        self.assertEqual(again.status_code, 409)

    def test_register_filters_search_and_placeholders(self):
        self.imported()
        self.client.force_login(self.ci)
        get = lambda **p: self.client.get(reverse('rca-records'), p).json()  # noqa: E731
        self.assertEqual(get()['count'], 5)
        self.assertEqual(get()['results'][0]['site_id'], 'LWEJH0001')  # largest outage first
        self.assertEqual(get(project='LWE')['count'], 2)
        self.assertEqual(get(circle='OD')['count'], 1)
        self.assertEqual(get(final_bucket='iaasp ofc')['count'], 2)  # both spellings
        self.assertEqual(get(bucket_2='__unclassified__')['count'], 2)  # "-" and blank
        self.assertEqual(get(q='flacuatation')['count'], 1)
        self.assertEqual(get(date='2026-10-21', page_size=2)['pages'], 3)
        self.assertEqual(get(date_from='2026-10-22')['count'], 0)
        self.assertEqual(self.client.get(reverse('rca-records'), {'date': 'x'}).status_code, 400)
        rec = get(q='OD0001')['results'][0]
        self.assertIsNone(rec['status'])  # follow-up not recorded

    def test_summary_counts_and_unclassified_handling(self):
        self.imported()
        self.client.force_login(self.admin)
        data = self.client.get(reverse('rca-summary')).json()
        self.assertEqual(data['kpis']['records'], 5)
        self.assertEqual(data['kpis']['affected_sites'], 5)
        self.assertAlmostEqual(data['kpis']['outage_minutes'], 20.6 + 1442.55 + 90 + 5 + 0.5, places=2)
        self.assertEqual(data['kpis']['incomplete_records'], 2)
        self.assertEqual(data['kpis']['incomplete_by_field'], {'final_bucket': 0, 'bucket_2': 2, 'rca': 1})
        # No Other Media record: an upload accepts only the approved Final Buckets (see the Other Media test for its handling).
        self.assertEqual((data['kpis']['rca_applicable_records'], data['kpis']['completeness_pct']), (5, 60.0))
        self.assertEqual(data['kpis']['rca_not_applicable']['records'], 0)
        # Bucket - 2 is grouped per Final Bucket; the blank ones are listed per Final Bucket too, never as a cause.
        self.assertEqual(sum(i['records'] for i in data['bucket_2'] if i['unclassified']), 2)
        b2 = {i['bucket_2']: i['records'] for i in data['bucket_2'] if not i['unclassified']}
        self.assertNotIn('-', b2)
        self.assertTrue(data['bucket_2'][-1]['unclassified'])  # listed last, never ranked as a cause
        iaasp = next(i for i in data['final_buckets'] if i['key'] == 'iaasp ofc')
        self.assertEqual((iaasp['label'], iaasp['records'], iaasp['variants'], iaasp['approved']), ('IaasP OFC', 2, ['IaasP OFC', 'Iaasp OFC'], True))  # approved label, uploaded spellings kept
        self.assertEqual(data['categories']['unreviewed']['records'], 4)
        self.assertEqual(data['top_records'][0]['site_id'], 'LWEJH0001')
        self.assertEqual(self.client.get(reverse('rca-summary'), {'project': 'LWE'}).json()['kpis']['records'], 2)

    def test_other_media_is_rca_not_applicable_by_final_bucket_not_by_a_blank_bucket_2(self):
        # Other Media is not an approved Final Bucket, so no upload can add it; records stored earlier keep this handling.
        self.imported()
        for site, minutes, b2, rca in (('LWEBH0063', 20.6, 'BSNL Media', 'Media Flacuatation'), ('OD0002', 30, '-', 'Media fluctuation')):
            RcaRecord.objects.filter(site_key=site).delete()
            project, circle = ('LWE', 'BH') if site.startswith('LWE') else ('4G Saturation', 'OD')
            RcaRecord.objects.create(reporting_date=DAY.date(), project=project, project_raw=project, circle=circle, circle_raw=circle,
                                     site_id=site, site_key=site, occurrence=1, outage_minutes=minutes, final_bucket='Other Media',
                                     final_bucket_key='other media', bucket_2=b2, bucket_2_key=parser.text_key(b2), rca_text=rca,
                                     rca_key=parser.text_key(rca), source='import')
        self.client.force_login(self.admin)
        data = self.client.get(reverse('rca-summary')).json()
        k = data['kpis']
        # Other Media (2: one with Bucket - 2 "-") is not applicable; the blank Bucket - 2 of BSNL OFC and Other stays missing.
        self.assertEqual(k['rca_not_applicable'], {'label': 'Other Media — RCA Not Applicable', 'final_buckets': ['Other Media'],
                                                   'records': 2, 'outage_minutes': 50.6, 'blank_bucket_2': 1})
        self.assertEqual((k['incomplete_records'], k['rca_applicable_records'], k['completeness_pct']), (2, 4, 50.0))
        self.assertEqual(k['records'], 6)  # nothing removed: every record is still counted once
        self.assertEqual(k['rca_not_applicable']['records'] + k['rca_applicable_records'], k['records'])
        other = next(i for i in data['final_buckets'] if i['key'] == 'other media')
        self.assertTrue(other['rca_not_applicable'])
        self.assertFalse(any(i['rca_not_applicable'] for i in data['final_buckets'] if i['key'] != 'other media'))
        self.assertEqual(sum(i['records'] for i in data['bucket_2']), 4)  # Bucket - 2 covers RCA-applicable records only
        get = lambda **p: self.client.get(reverse('rca-records'), p).json()  # noqa: E731
        self.assertEqual(get(rca='not_applicable')['count'], 2)
        self.assertEqual({r['site_id'] for r in get(rca='missing')['results']}, {'LWEJH0001', 'MP0001'})
        self.assertFalse(get(q='OD0002')['results'][0]['rca_applicable'])
        self.assertEqual(RcaRecord.objects.get(site_key='OD0002').bucket_2, '-')  # source value kept

    def test_mapping_is_explicit_and_leaves_the_source_text_unchanged(self):
        self.imported()
        self.client.force_login(self.admin)
        queue = self.client.get(reverse('rca-causes')).json()
        self.assertEqual(queue['stats']['mapped_descriptions'], 0)
        media = next(i for i in queue['queue'] if i['key'] == 'media fluctuation')
        self.assertEqual((media['records'], sorted(media['spellings'])), (2, ['Media Fluctuation', 'media  fluctuation']))
        category = self.client.post(reverse('rca-categories'), {'name': 'Media fluctuation'}, content_type='application/json').json()
        # Only the selected description is mapped: the similar "Media Flacuatation" stays in the queue.
        mapped = self.client.post(reverse('rca-mappings'), {'keys': ['media fluctuation'], 'category': category['id']},
                                  content_type='application/json').json()
        self.assertIn('media flacuatation', [i['key'] for i in mapped['queue']])
        self.assertEqual(mapped['stats']['mapped_records'], 2)
        self.assertEqual(sorted(RcaRecord.objects.filter(rca_key='media fluctuation').values_list('rca_text', flat=True)),
                         ['Media Fluctuation', 'media  fluctuation'])
        summary = self.client.get(reverse('rca-summary')).json()
        self.assertEqual(summary['categories']['mapped'][0], {'id': category['id'], 'name': 'Media fluctuation', 'records': 2, 'outage_minutes': 95.0})
        self.assertEqual(self.client.get(reverse('rca-records'), {'category': category['id']}).json()['count'], 2)
        self.assertEqual(self.client.get(reverse('rca-records'), {'category': 'unreviewed'}).json()['count'], 2)
        self.client.delete(reverse('rca-mappings'), {'keys': ['media fluctuation']}, content_type='application/json')
        self.assertFalse(RcaCauseMapping.objects.exists())

    def test_permissions_for_ci_users(self):
        self.imported()
        rec = RcaRecord.objects.get(site_key='OD0001')
        self.client.force_login(self.ci)
        for name, method in (('rca-summary', 'get'), ('rca-causes', 'get')):
            self.assertEqual(getattr(self.client, method)(reverse(name)).status_code, 403, name)
        self.assertEqual(self.client.get(reverse('rca-imports')).json()['imports'], [])  # their own uploads only (none)
        self.assertEqual(self.client.post(reverse('rca-categories'), {'name': 'x'}, content_type='application/json').status_code, 403)
        url = reverse('rca-workflow', args=[rec.pk])
        put = lambda body: self.client.put(url, body, content_type='application/json')  # noqa: E731
        ok = put({'status': 'action_pending', 'corrective_action': 'Replace patch cord', 'owner': 'OD O&M team', 'target_date': '2026-10-25'})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()['workflow']['owner'], 'OD O&M team')
        self.assertEqual(put({'status': 'action_completed'}).status_code, 400)  # needs the completion date
        self.assertEqual(put({'status': 'action_completed', 'completed_date': '2026-10-23'}).status_code, 200)
        self.assertEqual(put({'status': 'closed', 'verification': 'effective'}).status_code, 403)  # closure is Admin's
        self.assertEqual(put({'review_status': 'confirmed'}).status_code, 403)
        # Imported source facts are read-only for everyone.
        self.assertEqual(self.client.patch(reverse('rca-record', args=[rec.pk]), {'rca_text': 'x'}, content_type='application/json').status_code, 409)
        comment = self.client.post(reverse('rca-comments', args=[rec.pk]), {'text': 'Spoke to the SDE', 'evidence': 'Docket 123'},
                                   content_type='application/json')
        self.assertEqual(comment.json()['comments'][0]['evidence'], 'Docket 123')
        self.client.force_login(self.admin)
        closed = put({'status': 'closed', 'verification': 'effective', 'review_status': 'confirmed'}).json()
        self.assertEqual((closed['workflow']['status'], closed['workflow']['reviewer']), ('closed', 'rca-admin'))
        self.assertEqual(RcaRecord.objects.get(pk=rec.pk).rca_text, 'Media Fluctuation')
        self.assertGreaterEqual(RcaEvent.objects.filter(record=rec, action='workflow_updated').count(), 3)

    def test_ci_records_a_new_incident_and_only_the_author_or_an_admin_edits_it(self):
        self.client.force_login(self.ci)
        body = {'reporting_date': '2026-10-22', 'project': 'LWE', 'circle': 'BH', 'site_id': 'LWEBH0063', 'outage_minutes': 30,
                'final_bucket': 'TCS', 'bucket_2': 'TCS', 'rca_text': 'Hardware fault', 'om_start_raw': 'Yes'}
        created = self.client.post(reverse('rca-records'), body, content_type='application/json')
        self.assertEqual(created.status_code, 201, created.content)
        rid = created.json()['id']
        self.assertEqual(created.json()['source'], 'manual')
        self.assertEqual(self.client.post(reverse('rca-records'), {**body, 'circle': 'XX', 'rca_text': ''},
                                          content_type='application/json').json()['details'].keys() >= {'circle', 'rca_text'}, True)
        other = portal_user('other-ci', 'ci', all_circles=True)
        self.client.force_login(other)
        self.assertEqual(self.client.patch(reverse('rca-record', args=[rid]), {'outage_minutes': 40}, content_type='application/json').status_code, 403)
        self.client.force_login(self.admin)
        edited = self.client.patch(reverse('rca-record', args=[rid]), {'outage_minutes': 40}, content_type='application/json')
        self.assertEqual(edited.json()['outage_minutes'], 40)

    def test_unauthenticated_requests_are_refused(self):
        self.assertIn(self.client.get(reverse('rca-records')).status_code, (401, 403))
