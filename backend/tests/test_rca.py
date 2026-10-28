"""RCA module: workbook parsing, idempotent import, cause mapping, workflow and permissions.

Synthetic workbooks only (the real RCA workbook is checked against the live database separately).
"""
import tempfile
from datetime import datetime
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from openpyxl import Workbook

from apps.rca import importer, parser
from apps.rca.models import RcaCauseMapping, RcaEvent, RcaImportBatch, RcaRecord, RcaWorkflow
from tests.auth_helpers import portal_user

HEADERS = ['Date', 'Project', 'Circle', 'Site ID', 'Site Name', 'OA', 'BA', 'O&M Start (Yes/No)', 'Outage Min.',
           'Final Bucket', 'Bucket - 2', 'RCA']
DAY = datetime(2026, 10, 21)
ROWS = [
    [DAY, 'LWE', 'Bihar', 'LWEBH0063', 'Haibatpur', 'Gaya', 'Gaya', 'Yes', 20.6, 'Other Media', 'BSNL Media', 'Media Flacuatation'],
    [DAY, 'LWE', 'Jharkhand', 'LWEJH0001', 'Alpha', 'Ranchi', 'Ranchi', 'YES', 1442.55, 'BSNL OFC', '-', 'SSA OFC Break'],
    [DAY, '4G Satu', 'Odisha', 'OD0001 ', 'Bravo', 'KORAPUT', 'KORAPUT', 'No', 90, 'IaasP OFC', 'BSNL MEDIA', 'Media Fluctuation'],
    [DAY, '4G Satu', 'Rajasthan', 'RJ0001', 'Charlie', 'Jaisalmer', 'JODHPUR', 'Yes', 5, 'Iaasp OFC', 'BSNL Media', 'media  fluctuation'],
    [DAY, '4G Satu', 'Madhya Pradesh', 'MP0001', 'Delta', 'Indore', 'Indore', 'Yes', 0.5, 'Other', '', ''],
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


class RcaTestCase(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.admin = portal_user('rca-admin', 'admin')
        self.ci = portal_user('rca-ci', 'ci')

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
        self.assertEqual(report['issue_counts']['outage_over_day'], 1)
        # Case variants share a key; the source spellings are kept.
        self.assertEqual(od['final_bucket_key'], next(r for r in rows if r['site_key'] == 'RJ0001')['final_bucket_key'])
        self.assertIn(['IaasP OFC', 'Iaasp OFC'], report['label_variants']['final_bucket'])
        self.assertEqual(next(r for r in rows if r['site_key'] == 'RJ0001')['rca_key'], 'media fluctuation')

    def test_rejects_bad_rows_with_reasons_and_never_repairs_them(self):
        bad = ROWS + [
            ['not a date', 'LWE', 'Bihar', 'X1', '', '', '', 'Yes', 1, 'TCS', 'TCS', 'x'],
            [DAY, 'Other', 'Bihar', 'X2', '', '', '', 'Yes', 1, 'TCS', 'TCS', 'x'],
            [DAY, 'LWE', 'Atlantis', 'X3', '', '', '', 'Yes', 1, 'TCS', 'TCS', 'x'],
            [DAY, 'LWE', 'Bihar', '', '', '', '', 'Yes', 1, 'TCS', 'TCS', 'x'],
            [DAY, 'LWE', 'Bihar', 'X5', '', '', '', 'Yes', 'abc', 'TCS', 'TCS', 'x'],
            [DAY, 'LWE', 'Bihar', 'lwebh0063', '', '', '', 'Yes', 1, 'TCS', 'TCS', 'x'],  # duplicate of row 2
        ]
        report = parser.parse(self.path(rows=bad), 'rca.xlsx')['report']
        self.assertEqual((report['valid_rows'], report['rejected_rows']), (5, 6))
        self.assertEqual({c for c, n in report['issue_counts'].items() if c in {
            'invalid_date', 'unknown_project', 'unknown_circle', 'missing_site_id', 'invalid_outage', 'duplicate_row'}},
            {'invalid_date', 'unknown_project', 'unknown_circle', 'missing_site_id', 'invalid_outage', 'duplicate_row'})
        duplicate = next(i for i in report['all_issues'] if i['code'] == 'duplicate_row')
        self.assertEqual(duplicate['row'], 12)

    def test_missing_columns_or_sheet_reject_the_file(self):
        with self.assertRaisesRegex(parser.ParseError, 'missing required columns: RCA'):
            parser.parse(self.path(headers=HEADERS[:-1], rows=[r[:-1] for r in ROWS]), 'rca.xlsx')
        with self.assertRaisesRegex(parser.ParseError, 'no "Sheet1" sheet'):
            parser.parse(self.path(sheet='Data'), 'rca.xlsx')


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
        self.imported()
        again = self.imported(name='again.xlsx')
        self.assertEqual((again.counts['inserted'], again.counts['unchanged']), (0, 5))
        self.assertEqual(RcaRecord.objects.count(), 5)
        self.assertIsNotNone(importer.preview(self.path(), 'Book1_RCA.xlsx').report['already_imported'])

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

    def test_a_later_reporting_date_is_a_new_incident_for_the_same_site(self):
        self.imported()
        later = [[datetime(2026, 10, 22), *r[1:]] for r in ROWS[:1]]
        batch = self.imported(name='later.xlsx', rows=later)
        self.assertEqual(batch.counts['inserted'], 1)
        self.assertEqual(RcaRecord.objects.filter(site_key='LWEBH0063').count(), 2)


class ApiTests(RcaTestCase):
    def upload(self, path: Path):
        with open(path, 'rb') as handle:
            return self.client.post(reverse('rca-import-preview'), {'file': SimpleUploadedFile(path.name, handle.read())})

    def test_admin_imports_through_the_api_with_a_validation_report(self):
        self.client.force_login(self.admin)
        preview = self.upload(self.path())
        self.assertEqual(preview.status_code, 201)
        body = preview.json()
        self.assertNotIn('all_issues', body['report'])
        csv = self.client.get(reverse('rca-import-issues', args=[body['id']]))
        self.assertIn('outage_over_day', csv.content.decode('utf-8-sig'))
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
        self.assertEqual((data['kpis']['rca_applicable_records'], data['kpis']['completeness_pct']), (4, 50.0))
        self.assertEqual(data['kpis']['rca_not_applicable']['records'], 1)
        b2 = {i['label']: i['records'] for i in data['bucket_2']}
        self.assertEqual(b2['Unclassified (blank or "-")'], 2)
        self.assertNotIn('-', b2)
        self.assertTrue(data['bucket_2'][-1]['unclassified'])  # listed last, never ranked as a cause
        iaasp = next(i for i in data['final_buckets'] if i['key'] == 'iaasp ofc')
        self.assertEqual((iaasp['records'], iaasp['variants']), (2, ['IaasP OFC', 'Iaasp OFC']))
        self.assertEqual(data['categories']['unreviewed']['records'], 4)
        self.assertEqual(data['top_records'][0]['site_id'], 'LWEJH0001')
        self.assertEqual(self.client.get(reverse('rca-summary'), {'project': 'LWE'}).json()['kpis']['records'], 2)

    def test_other_media_is_rca_not_applicable_by_final_bucket_not_by_a_blank_bucket_2(self):
        rows = [list(r) for r in ROWS] + [
            [DAY, '4G Satu', 'Odisha', 'OD0002', 'Echo', 'KORAPUT', 'KORAPUT', 'Yes', 30, 'Other Media', '-', 'Media fluctuation'],
        ]
        self.imported(rows=rows)
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
        for name, method in (('rca-summary', 'get'), ('rca-imports', 'get'), ('rca-causes', 'get')):
            self.assertEqual(getattr(self.client, method)(reverse(name)).status_code, 403, name)
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
        other = portal_user('other-ci', 'ci')
        self.client.force_login(other)
        self.assertEqual(self.client.patch(reverse('rca-record', args=[rid]), {'outage_minutes': 40}, content_type='application/json').status_code, 403)
        self.client.force_login(self.admin)
        edited = self.client.patch(reverse('rca-record', args=[rid]), {'outage_minutes': 40}, content_type='application/json')
        self.assertEqual(edited.json()['outage_minutes'], 40)

    def test_unauthenticated_requests_are_refused(self):
        self.assertIn(self.client.get(reverse('rca-records')).status_code, (401, 403))
