"""RCA import preview: the reporting period (period_start / period_end) of an upload and the stored audit copy.

An upload without a valid period is a 4xx validation response, never a 500; no copy is filed without a period and no
date is ever substituted. Synthetic workbooks in a temporary DATA_DIR only.
"""
from datetime import date
from pathlib import Path
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.rca import importer
from apps.rca.models import RcaImportBatch, RcaRecord
from tests.test_rca import workbook
from tests.test_rca_uploads import OD_21, OD_22, UploadCase


class PeriodCase(UploadCase):
    def stored_files(self) -> list[Path]:
        root = Path(self.tmp.name) / 'data' / 'processed' / 'rca_uploads'
        return sorted(p for p in root.rglob('*') if p.is_file()) if root.exists() else []

    def unreadable(self, **details):
        """A workbook without the RCA columns (the parser rejects it before any row date is read)."""
        path = workbook(Path(self.tmp.name) / 'wrong.xlsx', rows=[['x', 'y']], headers=['Foo', 'Bar'])
        return self.client.post(reverse('rca-import-preview'), {
            'file': SimpleUploadedFile('wrong.xlsx', path.read_bytes()),
            **{'upload_type': 'consolidated', 'report_name': 'Daily RCA', 'project_scope': 'both', **details}})


class ValidPeriodTests(PeriodCase):
    def test_circle_upload_with_its_reporting_date_previews_and_stores_the_copy_under_the_period(self):
        r = self.circle(OD_21)
        self.assertEqual(r.status_code, 201, r.content)
        batch = RcaImportBatch.objects.get(pk=r.json()['id'])
        self.assertEqual((batch.status, batch.period_start, batch.period_end), ('previewed', date(2026, 10, 21), date(2026, 10, 21)))
        stored = Path(batch.stored_path)
        self.assertEqual(stored.parent.name, '2026-10-21_2026-10-21')
        self.assertEqual(stored.read_bytes(), (Path(self.tmp.name) / 'circle.xlsx').read_bytes())  # the upload, unmodified
        self.assertEqual(self.stored_files(), [stored])

    def test_consolidated_upload_with_equal_period_start_and_end_previews(self):
        r = self.consolidated(OD_21, period_start='2026-10-21', period_end='2026-10-21')
        self.assertEqual(r.status_code, 201, r.content)
        batch = RcaImportBatch.objects.get(pk=r.json()['id'])
        self.assertEqual((batch.period_start, batch.period_end), (date(2026, 10, 21), date(2026, 10, 21)))
        self.assertTrue(Path(batch.stored_path).is_file())

    def test_consolidated_upload_without_a_date_takes_the_workbooks_latest_date(self):
        r = self.consolidated(OD_21 + OD_22)
        self.assertEqual(r.status_code, 201, r.content)
        batch = RcaImportBatch.objects.get(pk=r.json()['id'])
        self.assertEqual((batch.period_start, batch.period_end), (date(2026, 10, 22), date(2026, 10, 22)))
        self.assertEqual(Path(batch.stored_path).parent.name, '2026-10-22_2026-10-22')


class MissingPeriodTests(PeriodCase):
    def test_unreadable_consolidated_upload_without_a_date_is_a_400_not_a_500(self):
        """The reported failure: _store() called with period_start None after a parse error."""
        r = self.unreadable()
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn('RCA_Data', r.json()['error'])
        batch = RcaImportBatch.objects.get(original_filename='wrong.xlsx')
        self.assertEqual((batch.status, batch.period_start, batch.period_end, batch.stored_path), ('failed', None, None, ''))
        self.assertEqual(self.stored_files(), [])  # no copy filed without a period

    def test_unreadable_upload_with_a_date_keeps_its_audit_copy(self):
        r = self.unreadable(period_start='2026-10-21')
        self.assertEqual(r.status_code, 400, r.content)
        batch = RcaImportBatch.objects.get(original_filename='wrong.xlsx')
        self.assertEqual(batch.status, 'failed')
        self.assertEqual(Path(batch.stored_path).parent.name, '2026-10-21_2026-10-21')

    def test_circle_upload_without_its_reporting_date_is_refused(self):
        r = self.post(OD_21, 'circle.xlsx', upload_type='circle', project='4G Saturation', circle='OD')
        self.assertEqual(r.status_code, 400)
        self.assertIn('period_start', r.json()['details'])
        self.assertFalse(RcaImportBatch.objects.exists())

    def test_period_end_without_period_start_is_refused(self):
        r = self.consolidated(OD_21, period_end='2026-10-21')
        self.assertEqual(r.status_code, 400)
        self.assertIn('period_start', r.json()['details'])
        self.assertFalse(RcaImportBatch.objects.exists())

    def test_missing_period_end_is_the_reporting_date_itself(self):
        """Daily periods: the end of a one-date upload is its start (existing semantics; not a substituted date)."""
        r = self.consolidated(OD_21, period_start='2026-10-21')
        self.assertEqual(r.status_code, 201, r.content)
        batch = RcaImportBatch.objects.get(pk=r.json()['id'])
        self.assertEqual(batch.period_end, date(2026, 10, 21))


class InvalidPeriodTests(PeriodCase):
    def assert_refused(self, field, **details):
        r = self.consolidated(OD_21, **details)
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn(field, r.json()['details'])
        self.assertFalse(RcaImportBatch.objects.exists())
        self.assertEqual(self.stored_files(), [])

    def test_unreadable_period_start(self):
        self.assert_refused('period_start', period_start='not-a-date')

    def test_unreadable_period_end(self):
        self.assert_refused('period_end', period_start='2026-10-21', period_end='31/31/2026')

    def test_period_end_other_than_the_reporting_date(self):
        self.assert_refused('period_end', period_start='2026-10-21', period_end='2026-10-22')

    def test_future_reporting_date(self):
        self.assert_refused('period_start', period_start='2099-01-01')


class StoreGuardTests(PeriodCase):
    """_store() itself: a missing or invalid period is ImportRejected (a 400), never an AttributeError; nothing is copied."""

    def batch(self, start, end):
        return RcaImportBatch.objects.create(original_filename='x.xlsx', checksum_sha256='a' * 64, sheet_name='Sheet1',
                                             period_start=start, period_end=end, status=RcaImportBatch.Status.FAILED)

    def check(self, start, end):
        path = workbook(Path(self.tmp.name) / 'x.xlsx', rows=OD_21)
        batch = self.batch(start, end)
        with self.assertRaises(importer.ImportRejected) as ctx:
            importer._store(path, batch)
        self.assertEqual(ctx.exception.status, 400)
        batch.refresh_from_db()
        self.assertEqual(batch.stored_path, '')
        self.assertEqual(self.stored_files(), [])

    def test_missing_period_start(self):
        self.check(None, date(2026, 10, 21))

    def test_missing_period_end(self):
        self.check(date(2026, 10, 21), None)

    def test_both_missing(self):
        self.check(None, None)

    def test_end_before_start(self):
        self.check(date(2026, 10, 22), date(2026, 10, 21))

    def test_valid_period_stores_the_copy(self):
        path = workbook(Path(self.tmp.name) / 'x.xlsx', rows=OD_21)
        batch = self.batch(date(2026, 10, 21), date(2026, 10, 21))
        importer._store(path, batch)
        batch.refresh_from_db()
        self.assertTrue(Path(batch.stored_path).is_file())


class ConsistencyTests(PeriodCase):
    def test_a_storage_failure_leaves_no_batch_and_no_records(self):
        records = RcaRecord.objects.count()
        path = workbook(Path(self.tmp.name) / 'circle.xlsx', rows=OD_21)
        details = {'upload_type': 'circle', 'report_name': 'OD RCA', 'period_start': date(2026, 10, 21), 'project_scope': '4G Saturation',
                   'circle': 'OD', 'remarks': ''}
        with mock.patch('apps.rca.importer.shutil.copyfile', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):  # a real storage fault stays a server error, but leaves nothing behind
                importer.preview(path, 'circle.xlsx', user=self.admin, details=details)
        self.assertFalse(RcaImportBatch.objects.exists())  # the batch and its copy together, or neither
        self.assertEqual(RcaRecord.objects.count(), records)  # a preview never touches stored records
        self.assertEqual(self.stored_files(), [])
