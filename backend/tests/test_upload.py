import tempfile
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from tests.auth_helpers import SignedInTestCase
from rest_framework import status

CSV_CONTENT = b"BTS IP ID,Nw Avail (4G TCS),Report Date\nUV_MP_001,99.5,16-10-2026\nUV_MP_002,98.2,16-10-2026\n"


class UploadTests(SignedInTestCase):
    def setUp(self):
        # Uploads go to a temporary directory so tests never write into Data/raw.
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.raw_dir = Path(self._tmp.name)
        self._override = override_settings(RAW_UPLOAD_DIR=self.raw_dir, MAX_UPLOAD_BYTES=1024)
        self._override.enable()

    def tearDown(self):
        self._override.disable()
        self._tmp.cleanup()

    def upload(self, name, content, content_type='text/csv'):
        return self.client.post(reverse('upload-file'), {'file': SimpleUploadedFile(name, content, content_type)})

    def test_list_raw_files(self):
        (self.raw_dir / 'a.csv').write_bytes(b'x')
        response = self.client.get(reverse('list-raw-files'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['files'][0]['name'], 'a.csv')

    def test_upload_csv_file(self):
        response = self.upload('test_sample_upload.csv', CSV_CONTENT)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data.get('status'), 'success')
        self.assertEqual(response.data.get('row_count'), 2)
        self.assertIn('BTS IP ID', response.data.get('columns'))
        self.assertIn('not been applied to the dashboard', response.data['message'])
        self.assertTrue((self.raw_dir / 'test_sample_upload.csv').exists())

    def test_existing_file_is_never_overwritten(self):
        (self.raw_dir / 'daily.csv').write_bytes(b'original')
        response = self.upload('daily.csv', CSV_CONTENT)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertNotEqual(response.data['filename'], 'daily.csv')
        self.assertEqual((self.raw_dir / 'daily.csv').read_bytes(), b'original')

    def test_path_components_are_stripped_from_filename(self):
        response = self.upload('../../evil.csv', CSV_CONTENT)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['filename'], 'evil.csv')
        self.assertTrue((self.raw_dir / 'evil.csv').exists())

    def test_rejects_unsupported_extension(self):
        response = self.upload('notes.txt', b'hello', 'text/plain')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Unsupported file extension', response.data['error'])

    def test_rejects_oversized_file(self):
        response = self.upload('big.csv', b'a,b\n' + b'1,2\n' * 400)
        self.assertEqual(response.status_code, status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

    def test_missing_file(self):
        response = self.client.post(reverse('upload-file'), {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unparseable_file_does_not_leak_exception_text(self):
        response = self.upload('broken.xlsx', b'not really excel', 'application/octet-stream')
        self.assertEqual(response.data['status'], 'partial_success')
        self.assertNotIn('zip', response.data['warning'].lower())
